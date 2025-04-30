"""Classification, provider safety, payload validation, and budget tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from homefile import db, fixtures
from homefile.classify import classify_text
from homefile.config import Settings
from homefile.errors import BudgetExceeded, ProviderDisabled, ProviderError
from homefile.models import DocType
from homefile.providers import (
    CompletionRequest,
    CompletionResponse,
    FakeProvider,
    ModelProvider,
    ProviderGuard,
    build_provider,
    validate_extraction_payload,
)


def test_receipt_classification() -> None:
    result = classify_text("\n".join(fixtures.RECEIPT_LINES))
    assert result.doc_type is DocType.RECEIPT
    assert result.confidence > 0.5


def test_warranty_classification() -> None:
    result = classify_text("\n".join(fixtures.WARRANTY_LINES))
    assert result.doc_type is DocType.WARRANTY
    assert result.confidence > 0.5


def test_subscription_classification() -> None:
    result = classify_text("\n".join(fixtures.SUBSCRIPTION_LINES))
    assert result.doc_type is DocType.SUBSCRIPTION


def test_unrecognized_text_is_unknown_with_low_confidence() -> None:
    result = classify_text("lorem ipsum dolor sit amet")
    assert result.doc_type is DocType.UNKNOWN
    assert result.confidence == 0.0


def test_fake_provider_quotes_only_document_text() -> None:
    provider = FakeProvider()
    prompt = "Extract fields.\n---DOCUMENT---\n" + "\n".join(fixtures.WARRANTY_LINES)
    response = provider.complete(CompletionRequest(system="s", prompt=prompt))
    payload = json.loads(response.text)
    body = prompt.split("---DOCUMENT---", 1)[1]
    assert payload["doc_type"] == "warranty"
    for item in payload["fields"]:
        assert item["quote"] in body


def test_fake_provider_is_free_and_deterministic() -> None:
    provider = FakeProvider()
    request = CompletionRequest(system="s", prompt="---DOCUMENT---\nTotal: 10.00 GBP")
    first = provider.complete(request)
    second = provider.complete(request)
    assert first.estimated_cost_usd == Decimal("0")
    assert first.text == second.text


def test_payload_validation_drops_unknown_fields() -> None:
    payload = validate_extraction_payload(
        '{"doc_type":"receipt","fields":[{"name":"password","value":"x","quote":"x","confidence":0.9}]}'
    )
    assert payload["fields"] == []
    assert payload["dropped"] == 1


def test_payload_validation_rejects_unknown_doc_type() -> None:
    with pytest.raises(ProviderError):
        validate_extraction_payload('{"doc_type":"passport","fields":[]}')


def test_payload_validation_clamps_out_of_range_confidence() -> None:
    payload = validate_extraction_payload(
        '{"doc_type":"receipt","fields":[{"name":"vendor","value":"a","quote":"a","confidence":1.5}]}'
    )
    assert payload["fields"][0]["confidence"] == 1.0
    assert payload["dropped"] == 0


def test_payload_validation_drops_entries_without_a_quote() -> None:
    payload = validate_extraction_payload(
        '{"doc_type":"receipt","fields":[{"name":"vendor","value":"a","quote":"","confidence":0.5}]}'
    )
    assert payload["fields"] == []
    assert payload["dropped"] == 1


def test_payload_validation_accepts_fenced_json() -> None:
    payload = validate_extraction_payload(
        '```json\n{"doc_type":"receipt","fields":[{"name":"vendor","value":"Acme","quote":"Acme","confidence":0.5}]}\n```'
    )
    assert payload["fields"][0]["name"] == "vendor"


def test_payload_validation_rejects_non_json() -> None:
    with pytest.raises(ProviderError):
        validate_extraction_payload("I think this is a receipt.")


def test_default_settings_refuse_network_providers(settings: Settings) -> None:
    with pytest.raises(ProviderDisabled):
        build_provider(settings.__class__(data_dir=settings.data_dir, provider="ollama"))
    with pytest.raises(ProviderDisabled):
        build_provider(settings.__class__(data_dir=settings.data_dir, provider="cloud"))


def test_cloud_provider_requires_caps(settings: Settings) -> None:
    configured = settings.__class__(
        data_dir=settings.data_dir,
        provider="cloud",
        allow_network=True,
        cloud_base_url="https://example.invalid/v1",
        cloud_model="some-model",
        cloud_input_price_per_1k=Decimal("0.001"),
        cloud_output_price_per_1k=Decimal("0.002"),
    )
    with pytest.raises(ProviderDisabled):
        build_provider(configured)


def test_unknown_provider_is_refused(settings: Settings) -> None:
    with pytest.raises(ProviderDisabled):
        build_provider(settings.__class__(data_dir=settings.data_dir, provider="mystery"))


def _guard(settings: Settings, provider: ModelProvider) -> ProviderGuard:
    db.init_db(settings.db_path)
    return ProviderGuard(settings=settings, provider=provider)


def test_guard_records_ledger_entries(settings: Settings) -> None:
    guard = _guard(settings, FakeProvider())
    guard.complete(CompletionRequest(system="s", prompt="---DOCUMENT---\nTotal: 1.00 GBP"))
    with db.session(settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM ledger").fetchall()
    assert len(rows) == 1
    assert rows[0]["project"] == "open-home-file"
    assert rows[0]["provider"] == "fake"
    assert rows[0]["success"] == 1


def test_guard_enforces_request_cap(settings: Settings) -> None:
    limited = settings.__class__(data_dir=settings.data_dir, run_request_cap=1)
    guard = _guard(limited, FakeProvider())
    guard.complete(CompletionRequest(system="s", prompt="---DOCUMENT---\na"))
    with pytest.raises(BudgetExceeded):
        guard.complete(CompletionRequest(system="s", prompt="---DOCUMENT---\na"))


def test_guard_enforces_token_cap(settings: Settings) -> None:
    limited = settings.__class__(data_dir=settings.data_dir, run_token_cap=8)
    guard = _guard(limited, FakeProvider())
    with pytest.raises(BudgetExceeded):
        guard.complete(CompletionRequest(system="a" * 200, prompt="b" * 200))


def test_guard_records_failures(settings: Settings) -> None:
    class Broken(FakeProvider):
        name: str = "broken"

        def complete(self, request: CompletionRequest) -> CompletionResponse:
            raise ProviderError("upstream refused")

    guard = _guard(settings, Broken())
    with pytest.raises(ProviderError):
        guard.complete(CompletionRequest(system="s", prompt="---DOCUMENT---\na"))
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM ledger").fetchone()
    assert row["success"] == 0
    assert row["error_class"] == "ProviderError"


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOMEFILE_CONFIRM_BELOW", "0.8")
    monkeypatch.setenv("HOMEFILE_ALLOW_NETWORK", "1")
    loaded = Settings.from_env(tmp_path / "lib")
    assert loaded.confirm_below == 0.8
    assert loaded.allow_network is True


def test_settings_defaults_are_local_only(tmp_path: Path) -> None:
    loaded = Settings.from_env(tmp_path / "lib")
    assert loaded.allow_network is False
    assert loaded.provider == "fake"
    assert loaded.run_cost_cap_usd == Decimal("0")
