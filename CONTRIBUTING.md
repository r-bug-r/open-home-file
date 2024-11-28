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

