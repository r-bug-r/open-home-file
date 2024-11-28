# Contributing

Thanks for helping. This project handles household documents, so the bar for correctness and privacy is higher than for a typical utility.

## Development setup

```bash
python -m venv .venv
```

Activate it (`source .venv/bin/activate` on POSIX, `.venv\Scripts\Activate.ps1` on Windows), then:

```bash
pip install -e ".[dev]"
```

Optional OCR support needs the extra and a local Tesseract binary:

```bash
pip install -e ".[dev,ocr]"
```

## The four gates

Every change must pass these locally and in CI:

```bash
ruff check .
mypy
pytest -q
python -m homefile smoke --work-dir .smoke-ci
```

- `ruff` and `mypy` are configured in `pyproject.toml`; mypy runs in strict mode over `src/`.
- `pytest` runs the unit and integration suites. Tests clear all `HOMEFILE_*` variables and block socket connections, so a test that tries to reach the network fails instead of passing silently.
- `homefile smoke` runs the whole workflow on generated documents and checks the promises end to end: citations, search, correction history, reminder confirmation, encrypted export, verified deletion, and integrity. It reuses `--work-dir` if it exists, so remove `.smoke-ci` before a local re-run.

CI runs the same gates on Ubuntu and Windows with Python 3.12. Do not weaken a test or skip a gate to get a green run; fix the cause or explain the exception in the pull request.

## Commit style

- Subject line in the imperative mood, no trailing period, 72 characters or fewer: `Reject PDFs with embedded files`, not `Rejected PDFs...` or `fix stuff`.
- Leave a blank line, then explain why in the body. The diff shows what changed; the body should say what would break without it, or which failure case it closes.
- Keep commits focused. A parser change and an unrelated CSS change belong in separate commits.
- Reference an issue when one exists.

## Adding a deterministic parser

Parsers live in `src/homefile/parsers.py` and are pure functions over a `Page`. They do not touch the database or the network.

1. Write the test first in `tests/unit/test_parsers.py`. Use synthetic lines from `src/homefile/fixtures.py` or a local string; never use a real document.
2. Return a `Candidate` with a `Citation` whose `char_start` and `char_end` select the exact supporting substring of `page.text`. A citation is required: values without one are dropped by the service layer.
3. Assert in the test that `page.text[citation.char_start:citation.char_end]` contains the value. This is the contract that keeps extraction auditable.
4. Register the parser inside `extract_candidates` so it participates in the strongest-candidate selection, and map the field to a reminder kind in `reminder_kind_for` if it has a deadline.
5. Handle ambiguity explicitly. Ambiguous numeric dates must be flagged or skipped according to `date_order`; invalid calendar dates must not be returned. Normalize values through the same helpers as existing fields.
6. Add fixture lines only if the existing synthetic documents cannot express the case, and keep them obviously fake.

Do not make a parser depend on a model. Deterministic parsing is the baseline that the optional provider can only supplement, never replace.

## Adding a provider

Providers live in `src/homefile/providers.py` behind the `ModelProvider` protocol:

```python
name: str
model: str
is_remote: bool

def count_tokens(self, request: CompletionRequest) -> int: ...
def complete(self, request: CompletionRequest) -> CompletionResponse: ...
def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]: ...
```

1. Implement all members of the protocol. `complete` must return token counts, a request id, latency, and an estimated cost; `stream` must end with `StreamEvent(delta="", done=True)`.
2. Wire the adapter into `build_provider`. Fail closed: a remote provider must require `HOMEFILE_ALLOW_NETWORK=1`, explicit configuration, and, for paid endpoints, non-zero run and daily cost caps plus explicit per-1k prices.
3. Never call the adapter directly from business logic. `ProviderGuard` enforces the request, token, and cost caps and writes the ledger; bypassing it would make spend invisible.
4. Validate model output with `validate_extraction_payload` before it reaches the service. Fields without a quote, unknown field names, and unknown document types must be dropped or rejected.
5. Add a fake-network test. The suite blocks sockets globally, so mock the transport (for example `urllib.request.urlopen`) and assert the request shape, the parsed response, and the failure path for malformed output. A test that would reach a real endpoint is not acceptable, even if it is skipped when offline.
6. Update the environment-variable table in `README.md` if you add a setting.

Providers must not log document text, API keys, or request bodies.

## Privacy rules for contributors

- Never commit a real receipt, invoice, contract, statement, ID, or scan. Do not commit personal names, addresses, account numbers, or serial numbers that belong to a real person or product.
- Use the synthetic documents from `homefile samples` or the fixtures module. If you need a new sample, generate it in code and keep the content fictional.
- Do not paste real document text into issues, pull requests, test names, or screenshots. Redact first; better, reproduce with a generated fixture.
- Do not add telemetry, analytics, remote logging, or a default network call. The default install must stay offline.
- Do not weaken the socket-blocking fixture in `tests/conftest.py`. If a test needs network behavior, mock the transport.

## Review expectations

- A maintainer reviews every change. Expect questions about failure modes, citations, and privacy before style.
- Pull requests should include tests for new behavior and a `CHANGELOG.md` entry under `[Unreleased]` when the change is user-visible.
- Keep changes scoped. Refactors that are not needed for the fix should be separate.
- Security fixes may be merged quickly and without prior public discussion; see [SECURITY.md](SECURITY.md) and [GOVERNANCE.md](GOVERNANCE.md).
- Review is a conversation about the code, not the person. Be specific, assume good faith, and explain the reasoning behind a request.
