"""Model provider adapters behind a narrow, auditable interface.

Contract (from the shared development guide):

    complete(request) -> response
    count_tokens(request) -> estimate
    stream(request) -> events

Three implementations:

* ``FakeProvider`` - deterministic, offline, zero cost. Default.
* ``OllamaProvider`` - local inference on 127.0.0.1, zero cash cost.
* ``CloudProvider`` - OpenAI-compatible endpoint, disabled unless the operator
  sets ``HOMEFILE_ALLOW_NETWORK=1``, supplies explicit per-1k prices, and sets
  non-zero cost caps. A zero cap refuses every call.

Every call goes through :class:`ProviderGuard`, which enforces per-run request,
token, and cost limits plus a daily cost cap read from the ledger, and records
one ledger row per attempt (success or failure).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from . import db
from .config import Settings
from .errors import BudgetExceeded, ProviderDisabled, ProviderError

EXTRACTION_SCHEMA_HINT = {
    "type": "object",
    "required": ["doc_type", "fields"],
    "properties": {
        "doc_type": {
            "type": "string",
            "enum": ["receipt", "warranty", "bill", "contract", "subscription", "unknown"],
        },
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "value", "quote"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}

ALLOWED_FIELDS = {
    "vendor",
    "amount",
    "currency",
    "purchase_date",
    "serial",
    "warranty_end",
    "renewal_date",
    "cancellation_deadline",
    "contract_end",
    "account",
}
ALLOWED_DOC_TYPES = {"receipt", "warranty", "bill", "contract", "subscription", "unknown"}


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    prompt: str
    system: str = ""
    max_output_tokens: int = 512
    temperature: float = 0.0


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    text: str
    provider: str
    model: str
    request_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class StreamEvent:
    delta: str
    done: bool = False


class ModelProvider(Protocol):
    name: str
    model: str
    is_remote: bool

    def count_tokens(self, request: CompletionRequest) -> int: ...

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]: ...


def estimate_tokens(text: str) -> int:
    """Cheap deterministic estimate: about four characters per token."""
    return max(1, (len(text) + 3) // 4)


class FakeProvider:
    """Deterministic provider used by tests, CI, and the default install.

    It does not paraphrase: it emits a fixed JSON envelope whose fields are
    copied from the document text with explicit quotes. Anything it cannot
    quote, it omits. This keeps the fake honest about citations.
    """

    name = "fake"
    model = "fake-deterministic-v1"
    is_remote = False

    def count_tokens(self, request: CompletionRequest) -> int:
        return estimate_tokens(request.system) + estimate_tokens(request.prompt)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = datetime.now(UTC)
        payload = self._payload(request.prompt)
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return CompletionResponse(
            text=text,
            provider=self.name,
            model=self.model,
            request_id=f"fake-{uuid.uuid4().hex[:12]}",
            input_tokens=self.count_tokens(request),
            output_tokens=estimate_tokens(text),
            latency_ms=elapsed,
            estimated_cost_usd=Decimal("0"),
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        response = self.complete(request)
        yield StreamEvent(delta=response.text)
        yield StreamEvent(delta="", done=True)

    def _payload(self, prompt: str) -> dict[str, Any]:
        """Quote-based extraction from the prompt body.

        The prompt is expected to contain the document text after a
        ``---DOCUMENT---`` marker; the fake only ever echoes that text.
        """
        body = prompt.split("---DOCUMENT---", 1)[-1]
        fields: list[dict[str, Any]] = []
        patterns = (
            ("vendor", r"(?:sold by|vendor|merchant|supplier)\s*:\s*(.+)"),
            ("amount", r"(?:grand total|total|amount due)\s*:?\s*([£$€]?\s?\d[\d,.\s]*\d|\d+)"),
            ("serial", r"(?:serial(?:\s*(?:no|number))?|s/n)\s*:?\s*([A-Z0-9][A-Z0-9-]{3,23})"),
            ("warranty_end", r"(?:warranty|guarantee)[^\n]{0,60}?(\d{4}-\d{2}-\d{2})"),
        )
        for name, pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match is None:
                continue
            quote = match.group(0).strip()
            fields.append(
                {"name": name, "value": match.group(1).strip(), "quote": quote, "confidence": 0.5}
            )
        lowered = body.lower()
        doc_type = "unknown"
        for candidate, words in (
            ("warranty", ("warranty", "guarantee")),
            ("subscription", ("subscription", "renews")),
            ("receipt", ("receipt", "sales receipt")),
            ("bill", ("invoice", "amount due")),
            ("contract", ("agreement", "contract")),
        ):
            if any(word in lowered for word in words):
                doc_type = candidate
                break
        return {"doc_type": doc_type, "fields": fields}


class OllamaProvider:
    """Local Ollama adapter. Loopback only; no cash cost."""

    name = "ollama"
    is_remote = True

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def count_tokens(self, request: CompletionRequest) -> int:
        return estimate_tokens(request.system) + estimate_tokens(request.prompt)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        body = {
            "model": self.model,
            "prompt": request.prompt,
            "system": request.system,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        started = datetime.now(UTC)
        data = _post_json(f"{self.base_url}/api/generate", body, {}, self.timeout)
        text = str(data.get("response", ""))
        elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return CompletionResponse(
            text=text,
            provider=self.name,
            model=self.model,
            request_id=f"ollama-{uuid.uuid4().hex[:12]}",
            input_tokens=int(data.get("prompt_eval_count") or self.count_tokens(request)),
            output_tokens=int(data.get("eval_count") or estimate_tokens(text)),
            latency_ms=elapsed,
            estimated_cost_usd=Decimal("0"),
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        yield StreamEvent(delta=self.complete(request).text)
        yield StreamEvent(delta="", done=True)


class CloudProvider:
    """OpenAI-compatible chat completions endpoint.

    Requires explicit configuration and non-zero caps; see ``ProviderGuard``.
    """

    name = "cloud"
    is_remote = True

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        input_price_per_1k: Decimal,
        output_price_per_1k: Decimal,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.input_price = input_price_per_1k
        self.output_price = output_price_per_1k
        self.timeout = timeout

    def count_tokens(self, request: CompletionRequest) -> int:
        return estimate_tokens(request.system) + estimate_tokens(request.prompt)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) / Decimal(1000) * self.input_price
            + Decimal(output_tokens) / Decimal(1000) * self.output_price
        ).quantize(Decimal("0.000001"))

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started = datetime.now(UTC)
        data = _post_json(f"{self.base_url}/chat/completions", body, headers, self.timeout)
        elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
        try:
            text = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider response did not contain a message") from exc
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or self.count_tokens(request))
        output_tokens = int(usage.get("completion_tokens") or estimate_tokens(text))
        return CompletionResponse(
            text=text,
            provider=self.name,
            model=self.model,
            request_id=str(data.get("id") or f"cloud-{uuid.uuid4().hex[:12]}"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed,
            estimated_cost_usd=self.estimate_cost(input_tokens, output_tokens),
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        yield StreamEvent(delta=self.complete(request).text)
        yield StreamEvent(delta="", done=True)


def _post_json(
    url: str, body: Mapping[str, Any], headers: Mapping[str, str], timeout: float
) -> Any:
    request = urllib.request.Request(  # noqa: S310 - fixed http(s) endpoint from settings
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"provider is unreachable: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("provider returned invalid JSON") from exc


def build_provider(settings: Settings) -> ModelProvider:
    """Construct the configured provider, failing closed on unsafe config."""
    choice = settings.provider
    if choice == "fake":
        return FakeProvider()
    if not settings.allow_network:
        raise ProviderDisabled(
            f"provider {choice!r} requires network access; set HOMEFILE_ALLOW_NETWORK=1 to opt in"
        )
    if choice == "ollama":
        return OllamaProvider(settings.ollama_url, settings.ollama_model)
    if choice == "cloud":
        import os

        if not settings.cloud_base_url or not settings.cloud_model:
            raise ProviderDisabled(
                "cloud provider requires HOMEFILE_CLOUD_BASE_URL and HOMEFILE_CLOUD_MODEL"
            )
        if settings.cloud_input_price_per_1k is None or settings.cloud_output_price_per_1k is None:
            raise ProviderDisabled(
                "cloud provider requires explicit per-1k input and output prices"
            )
        if settings.run_cost_cap_usd <= 0 or settings.daily_cost_cap_usd <= 0:
            raise ProviderDisabled(
                "cloud provider requires non-zero HOMEFILE_RUN_COST_CAP_USD and "
                "HOMEFILE_DAILY_COST_CAP_USD; the default cap is zero"
            )
        api_key = os.environ.get(settings.cloud_api_key_env, "")
        if not api_key:
            raise ProviderDisabled(f"cloud provider requires {settings.cloud_api_key_env}")
        return CloudProvider(
            settings.cloud_base_url,
            settings.cloud_model,
            api_key,
            settings.cloud_input_price_per_1k,
            settings.cloud_output_price_per_1k,
        )
    raise ProviderDisabled(f"unknown provider {choice!r}; expected fake, ollama, or cloud")


@dataclass(slots=True)
class RunUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    def add(self, response: CompletionResponse) -> None:
        self.requests += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.cost_usd += response.estimated_cost_usd


@dataclass(slots=True)
class ProviderGuard:
    """Budget enforcement plus ledger recording around a provider."""

    settings: Settings
    provider: ModelProvider
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
    workflow: str = "extract"
    usage: RunUsage = field(default_factory=RunUsage)

    def _daily_spend(self) -> Decimal:
        today = datetime.now(UTC).date().isoformat()
        with db.session(self.settings.db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(CAST(estimated_cost AS REAL)), 0) AS total "
                "FROM ledger WHERE substr(started_at, 1, 10) = ? AND success = 1",
                (today,),
            ).fetchone()
        return Decimal(str(row["total"] if row else 0))

    def _record(self, response: CompletionResponse, success: bool, error_class: str | None) -> None:
        with db.session(self.settings.db_path) as conn:
            conn.execute(
                "INSERT INTO ledger(run_id, project, workflow, provider, model, request_id, started_at,"
                " input_tokens, output_tokens, estimated_cost, cache_hit, success, error_class)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,
                    "open-home-file",
                    self.workflow,
                    response.provider,
                    response.model,
                    response.request_id,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    response.input_tokens,
                    response.output_tokens,
                    str(response.estimated_cost_usd),
                    0,
                    1 if success else 0,
                    error_class,
                ),
            )

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.usage.requests + 1 > self.settings.run_request_cap:
            raise BudgetExceeded(
                f"run request cap of {self.settings.run_request_cap} reached; "
                "start a new run or raise HOMEFILE_RUN_REQUEST_CAP"
            )
        estimated = self.provider.count_tokens(request)
        if self.usage.input_tokens + estimated > self.settings.run_token_cap:
            raise BudgetExceeded(
                f"run token cap of {self.settings.run_token_cap} reached "
                f"({self.usage.input_tokens} used, ~{estimated} needed)"
            )
        if self.settings.provider == "cloud" and isinstance(self.provider, CloudProvider):
            projected = self.provider.estimate_cost(estimated, request.max_output_tokens)
            if self.usage.cost_usd + projected > self.settings.run_cost_cap_usd:
                raise BudgetExceeded("run cost cap would be exceeded by this request")
            if self._daily_spend() + projected > self.settings.daily_cost_cap_usd:
                raise BudgetExceeded("daily cost cap would be exceeded by this request")
        try:
            response = self.provider.complete(request)
        except ProviderError:
            failure = CompletionResponse(
                text="",
                provider=self.provider.name,
                model=self.provider.model,
                request_id=f"failed-{uuid.uuid4().hex[:12]}",
                input_tokens=estimated,
                output_tokens=0,
                latency_ms=0,
                estimated_cost_usd=Decimal("0"),
            )
            self._record(failure, False, "ProviderError")
            raise
        if (
            self.settings.provider == "cloud"
            and self.usage.cost_usd + response.estimated_cost_usd > self.settings.run_cost_cap_usd
        ):
            self._record(response, False, "BudgetExceeded")
            raise BudgetExceeded("provider returned a response exceeding the run cost cap")
        self.usage.add(response)
        self._record(response, True, None)
        return response


def validate_extraction_payload(text: str) -> dict[str, Any]:
    """Validate model output before it reaches business logic.

    The envelope must be well-formed: a non-JSON payload or an unknown
    ``doc_type`` raises :class:`ProviderError`. Individual field entries that
    cannot be trusted (unknown name, missing value or quote, wrong type) are
    dropped and counted in ``dropped`` so the caller can warn the user instead
    of silently accepting a half-parsed answer.
    """
    try:
        payload = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        raise ProviderError("model output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderError("model output must be a JSON object")
    doc_type = payload.get("doc_type")
    if not isinstance(doc_type, str) or doc_type not in ALLOWED_DOC_TYPES:
        raise ProviderError(f"model output has an invalid doc_type: {doc_type!r}")
    fields = payload.get("fields", [])
    if not isinstance(fields, list):
        raise ProviderError("model output 'fields' must be a list")
    cleaned: list[dict[str, Any]] = []
    dropped = 0
    for item in fields:
        if not isinstance(item, dict):
            dropped += 1
            continue
        name = item.get("name")
        value = item.get("value")
        quote = item.get("quote")
        if not isinstance(name, str) or name not in ALLOWED_FIELDS:
            dropped += 1
            continue
        if not isinstance(value, str) or not isinstance(quote, str) or not quote.strip():
            dropped += 1
            continue
        confidence = item.get("confidence", 0.5)
        if not isinstance(confidence, int | float):
            confidence = 0.5
        cleaned.append(
            {
                "name": name,
                "value": value.strip()[:200],
                "quote": quote.strip()[:400],
                "confidence": max(0.0, min(1.0, float(confidence))),
            }
        )
    return {"doc_type": doc_type, "fields": cleaned, "dropped": dropped}


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)
    return stripped.strip()
