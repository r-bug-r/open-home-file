# Open Home File

Open Home File is a local-first index for household documents. It imports PDF, PNG, and JPEG files, stores the originals encrypted, extracts page text, classifies each document, pulls out the fields that matter (vendor, amount, serial number, dates, deadlines), attaches a page-and-character citation to every extracted value, and turns confirmed deadlines into reminders. A loopback-only web UI and a JSON-first CLI read and write the same SQLite library.

## Status

0.1.0 — pre-release, single-user local install.

The storage format, CLI flags, and HTTP routes may change before 1.0. There is no upgrade path from an earlier release because there has been no earlier release.

## The local-first promise

- No network access by default. `HOMEFILE_ALLOW_NETWORK` is `0` unless you set it.
- The default provider is `fake`: a deterministic, offline extractor that quotes the document text and costs nothing. It is not a language model.
- Ollama and OpenAI-compatible cloud providers are optional adapters. Remote providers require `HOMEFILE_ALLOW_NETWORK=1`; the cloud adapter is also disabled unless explicit prices, a non-zero run cost cap, a non-zero daily cost cap, and an API key are configured.
- With the default configuration, every document lives under one data directory, and nothing is uploaded, synced, or collected as telemetry.
- Deletion is verified: the command reports which tables and files were checked, and fails if anything remains.

## Requirements

- Python 3.12 or newer.
- No system services are required for text PDFs.
- OCR is optional: `pip install -e ".[ocr]"` plus a local Tesseract binary. Without it, image imports and PDF pages without a text layer are stored with a warning and no invented text.

## Install

```bash
python -m venv .venv
```

Activate the environment:

```bash
# POSIX
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the project and development tools:

```bash
pip install -e ".[dev]"
```

This installs the `homefile` console script. `python -m homefile` behaves identically.

## 60-second quickstart

```bash
# 1. Write synthetic sample documents (no real data involved).
homefile samples ./samples

# 2. Import one and read the JSON result: doc id, fields, citations, reminders.
homefile import ./samples/warranty.pdf

# 3. List documents if you need the id again.
homefile list

# 4. Inspect fields, page citations, and provenance.
homefile show <doc-id>

# 5. Correct a value; the original is kept in history.
homefile correct <field-id> "2028-04-30" --reason "corrected from the policy document"
homefile history <field-id>

# 6. Confirm the suggested reminder, then start the local UI.
homefile reminders
homefile confirm-reminder <reminder-id>
homefile serve
```

Open <http://127.0.0.1:8765>. The server binds to loopback only; `--host` accepts `127.0.0.1`, `localhost`, or `::1` and refuses anything else. Press Ctrl+C to stop.

Every command except `serve` prints JSON by default. Add `--human` before the subcommand for a compact readable form, for example `homefile --human list`. Use `--data-dir <path>` to point at a different library instead of the per-user default.

## Commands

| Command | Purpose |
| --- | --- |
| `import <path>` | Inspect, hash, store, extract, classify, and index one PDF, PNG, or JPEG. `--no-model` skips the provider; `--date-order dmy\|mdy` resolves ambiguous numeric dates. |
| `list` | List documents with id, type, page count, and filename. |
| `show <doc-id>` | Show one document with page text, fields, citations, reminders, and metadata. |
| `search [query]` | Full-text search over page text, with optional structured filters (`--vendor`, `--serial`, `--type`, `--min-amount`, `--max-amount`, `--deadline-before`, `--deadline-after`, `--limit`). |
| `correct <field-id> <value>` | Replace an extracted value, record the old value and reason, and mark the field confirmed. `--reason` is required. |
| `confirm-field <field-id>` | Accept an extracted value as-is. |
| `reject-field <field-id>` | Reject a field. `--reason` is required. |
| `history <field-id>` | Show the append-only provenance history for a field. |
| `reminders [--status]` | List reminders, optionally filtered by status. |
| `confirm-reminder <reminder-id>` | Confirm a suggested reminder so it can become due. |
| `dismiss-reminder <reminder-id>` | Dismiss a reminder. `--reason` is required. |
| `due` | List confirmed reminders whose due date is today or earlier. |
| `export <doc-id> [--passphrase]` | Write a bundle containing metadata, pages, fields, history, and the original. With a passphrase the bundle is encrypted as `.hfe`; without one it is a plain `.zip`. |
| `delete <doc-id>` | Delete the document and derived records, then verify that no rows or blobs remain. |
| `verify` | Check every stored blob against its SHA-256 and report problems. Exit code 1 on failure. |
| `stats` | Show document, page, field, reminder, and spend counts. |
| `ledger` | Show the provider call ledger (tokens, estimated cost, success). |
| `serve` | Start the loopback web UI. `--host` defaults to `127.0.0.1`, `--port` to `8765`. |
| `smoke` | Run the end-to-end scenario on synthetic documents in a temporary directory. `--work-dir` keeps the fixtures. Exit code 1 on failure. |
| `samples [directory]` | Write synthetic receipt, warranty, and subscription PDFs. Defaults to `./samples`. |

Global options: `--data-dir <path>` and `--human`.

## Configuration

Settings come from environment variables. Defaults are local-only and cost zero.

| Variable | Default | Effect |
| --- | --- | --- |
| `HOMEFILE_DATA_DIR` | platform per-user data directory | Library root. Windows: `%LOCALAPPDATA%\homefile`; otherwise `$XDG_DATA_HOME/homefile` or `~/.local/share/homefile`. |
| `HOMEFILE_MAX_FILE_MB` | `25` | Maximum input file size in mebibytes. |
| `HOMEFILE_MAX_PAGES` | `200` | Maximum pages per PDF. |
| `HOMEFILE_MAX_PAGE_CHARS` | `200000` | Maximum characters kept per page; longer text is truncated with a warning. |
| `HOMEFILE_CONFIRM_BELOW` | `0.8` | Confidence below which the web UI marks a field as needing review. |
| `HOMEFILE_ALLOW_NETWORK` | `false` | Required before the Ollama or cloud provider can be constructed. |
| `HOMEFILE_PROVIDER` | `fake` | `fake`, `ollama`, or `cloud`. |
| `HOMEFILE_RUN_REQUEST_CAP` | `20` | Maximum provider requests per run. |
| `HOMEFILE_RUN_TOKEN_CAP` | `20000` | Maximum input tokens per run. |
| `HOMEFILE_RUN_COST_CAP_USD` | `0` | Maximum estimated cost per run. Must be non-zero for `cloud`. |
| `HOMEFILE_DAILY_COST_CAP_USD` | `0` | Maximum estimated cost per UTC day. Must be non-zero for `cloud`. |
| `HOMEFILE_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama endpoint. |
| `HOMEFILE_OLLAMA_MODEL` | `llama3.2` | Ollama model name. |
| `HOMEFILE_CLOUD_BASE_URL` | empty | OpenAI-compatible base URL. Required for `cloud`. |
| `HOMEFILE_CLOUD_MODEL` | empty | Cloud model name. Required for `cloud`. |
| `HOMEFILE_CLOUD_INPUT_PRICE_PER_1K` | unset | Input price per 1000 tokens. Required for `cloud`. |
| `HOMEFILE_CLOUD_OUTPUT_PRICE_PER_1K` | unset | Output price per 1000 tokens. Required for `cloud`. |
| `HOMEFILE_CLOUD_API_KEY_ENV` | `HOMEFILE_CLOUD_API_KEY` | Name of the environment variable that holds the cloud API key. |

Example opt-in to a local Ollama instance:

```bash
export HOMEFILE_ALLOW_NETWORK=1
export HOMEFILE_PROVIDER=ollama
homefile import ./samples/receipt.pdf
```

## Architecture

```text
CLI (cli.py)                    Web UI (web/server.py, web/pages.py)
      \                              /
       Library (service.py)
      /        |             \
 SQLite      encrypted blobs   providers
 (db.py)     (store.py,        (providers.py,
             crypto.py)        ProviderGuard)
      |
 inspect.py -> extract.py -> classify.py / parsers.py
```

The `Library` class is the only place that changes state. The CLI and HTTP server are thin adapters over it; every route and command calls the same methods. Original bytes are content-addressed by SHA-256 and sealed with AES-256-GCM before they reach disk. Page text and derived records live in SQLite, with an FTS5 external-content index over pages. Providers sit behind a narrow `ModelProvider` protocol and are wrapped by `ProviderGuard`, which enforces request, token, run-cost, and daily-cost caps and writes a ledger row for every call.

Data directory layout:

```text
<data-dir>/
  homefile.sqlite3   documents, pages, fields, history, reminders, ledger
  key.bin            locally generated 32-byte AES key
  blobs/             encrypted originals, named <sha256>.hbf
  exports/           export bundles
```

See [docs/architecture.md](docs/architecture.md) for the full picture, [docs/operations.md](docs/operations.md) for install, backup, and troubleshooting, and [docs/decisions/](docs/decisions/) for recorded design decisions.

## Privacy

- The default provider never opens a socket. The test suite also blocks socket connections, so an accidental network call fails the tests.
- Original files are encrypted at rest. `key.bin` is created locally with owner-only permissions where the platform supports them; it is not passphrase-protected, so anyone who can read the data directory can decrypt the blobs.
- Page text, extracted fields, citations, correction history, reminders, and provider ledger entries are stored as plaintext in `homefile.sqlite3`. The database is not encrypted.
- Exports are plaintext `.zip` files unless you pass `--passphrase`, in which case the bundle is encrypted with AES-256-GCM and an scrypt-derived key.
- The web UI binds to loopback only, uses a per-process CSRF token in a strict cookie and in every form, rejects cross-origin submissions, sets a restrictive content security policy, and loads no external assets.
- File inspection enforces size and page limits and rejects PDFs containing JavaScript, embedded files, or encryption. It is not an antivirus or malware scanner.

More detail is in [docs/privacy.md](docs/privacy.md) and [docs/threat-model.md](docs/threat-model.md).

## What this project does not do

- It does not give legal, financial, tax, or insurance advice, and it does not interpret contract terms. Extracted values are candidates for you to confirm.
- It does not cancel subscriptions, make payments, or contact vendors.
- It is not a hosted or multi-user service. There are no accounts, sharing, sync, or remote access.
- It does not promise OCR accuracy. OCR is optional and local; pages without a text layer are flagged rather than guessed.

## Verification

Run these before sending a change:

```bash
ruff check .
mypy
pytest -q
python -m homefile smoke --work-dir .smoke-ci
```

The smoke command runs the whole workflow on synthetic documents and exits non-zero if any promise fails. It does not clear an existing `--work-dir`; delete `.smoke-ci` before re-running locally. CI runs the same four gates on Linux and Windows.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [GOVERNANCE.md](GOVERNANCE.md), and the [code of conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
