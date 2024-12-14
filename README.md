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

