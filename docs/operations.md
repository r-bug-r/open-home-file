# Operations

How to install, run, back up, and troubleshoot Open Home File as it exists in
this repository. Commands are shown for POSIX; on Windows use the same
arguments with `python -m homefile` or the activated `homefile.exe`.

## 1. Requirements

- Python 3.12 or newer.
- No system services for text PDFs.
- OCR is optional: `pip install -e ".[ocr]"` plus a local Tesseract binary.
  Without it, images and PDF pages with no text layer are stored with
  `text_source = none` and a warning; no text is invented.

## 2. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`homefile` and `python -m homefile` are equivalent. `pip install -e .` without
`[dev]` installs only the runtime dependencies.

## 3. Data directory

The library is one directory:

```text
<data-dir>/
  homefile.sqlite3   documents, pages, FTS index, fields, history, reminders, ledger
  homefile.sqlite3-wal / -shm   present while the database is open
  key.bin            32-byte AES key, created on first use
  blobs/             <sha256>.hbf, encrypted originals
  exports/           export bundles
```

Resolution order:

1. `--data-dir <path>` on any command.
2. `HOMEFILE_DATA_DIR`.
3. Windows: `%LOCALAPPDATA%\homefile`; otherwise
   `$XDG_DATA_HOME/homefile` or `~/.local/share/homefile`.

Every command, including read-only ones, creates the directory, schema, and
key if they are missing. `homefile stats` prints the resolved paths.

## 4. Daily use

```bash
homefile samples ./samples          # synthetic PDFs, no real data
homefile import ./samples/receipt.pdf
homefile list
homefile show <doc-id>
homefile search "northwind" --type receipt
homefile correct <field-id> "2026-04-01" --reason "receipt says April"
homefile history <field-id>
homefile reminders
homefile confirm-reminder <reminder-id>
homefile due
homefile export-all --passphrase "a long backup passphrase"
homefile serve
```

Every command except `serve` prints JSON; add `--human` before the subcommand
for a compact table or text form. Exit codes are `0` on success, `2` on any
`HomeFileError` (validation, integrity, provider, deletion) or argument error,
`1` when `smoke` reports a failed promise, and `130` on Ctrl+C.

## 5. Web server

```bash
homefile serve                 # 127.0.0.1:8765
homefile serve --port 8792
```

- `--host` accepts `127.0.0.1`, `localhost`, or `::1` and refuses anything
  else. There is no TLS and no authentication; do not proxy it to a network
  without adding both.
- `/healthz` returns `{"ok":true}` for a local supervisor.
- Stop with Ctrl+C. There is no daemon mode and no service file.
- The home page imports files (drop zone or picker, up to 20 at once) and lists
  recent import attempts, including failed and duplicate files with their
  error text. An empty library offers three synthetic samples, generated
  locally through the normal import path.
- `/documents` searches page text and structured fields. `/documents/<id>`
  shows the source pages, extracted fields, the selected citation with its
  character range, the correction form, and processing notes. Every field row
  is a link, so the workflow works without JavaScript; `app.js` adds in-place
  selection, page-tab keyboard navigation, and a per-file import queue.
- `/reminders` filters by status and keeps the source document beside every
  reminder. A suggested reminder never becomes active without confirmation.
- `/settings` runs `verify_integrity`, shows storage paths, processing mode,
  retained data classes, per-run and daily caps, and the export and
  delete-everything actions. Delete-all requires typing `DELETE`.
- `/settings/export` writes a whole-library archive to `exports/`; it is a
  plain ZIP unless a passphrase is supplied, in which case it is a single
  `.hfe` file.

## 6. Configuration

Settings come from environment variables and are read at process start.

| Variable | Default | Notes |
|---|---|---|
| `HOMEFILE_DATA_DIR` | platform default | Library root |
| `HOMEFILE_MAX_FILE_MB` | `25` | Per-file cap for import |
| `HOMEFILE_MAX_PAGES` | `200` | Per-PDF page cap |
| `HOMEFILE_MAX_PAGE_CHARS` | `200000` | Per-page text cap; longer text is truncated with a warning |
| `HOMEFILE_CONFIRM_BELOW` | `0.8` | Below this, the UI marks a field as needing review |
| `HOMEFILE_ALLOW_NETWORK` | `false` | Required for any provider other than `fake` |
| `HOMEFILE_PROVIDER` | `fake` | `fake`, `ollama`, `cloud` |
| `HOMEFILE_RUN_REQUEST_CAP` | `20` | Provider requests per run |
| `HOMEFILE_RUN_TOKEN_CAP` | `20000` | Input tokens per run |
| `HOMEFILE_RUN_COST_CAP_USD` | `0` | Must be non-zero for `cloud` |
| `HOMEFILE_DAILY_COST_CAP_USD` | `0` | Must be non-zero for `cloud` |
| `HOMEFILE_OLLAMA_URL` | `http://127.0.0.1:11434` | Not verified to be loopback |
| `HOMEFILE_OLLAMA_MODEL` | `llama3.2` | |
| `HOMEFILE_CLOUD_BASE_URL` | empty | Required for `cloud` |
| `HOMEFILE_CLOUD_MODEL` | empty | Required for `cloud` |
| `HOMEFILE_CLOUD_INPUT_PRICE_PER_1K` | unset | Required for `cloud` |
| `HOMEFILE_CLOUD_OUTPUT_PRICE_PER_1K` | unset | Required for `cloud` |
| `HOMEFILE_CLOUD_API_KEY_ENV` | `HOMEFILE_CLOUD_API_KEY` | Name of the variable holding the key |

A misconfigured provider fails closed: an unknown name, a missing price, a
zero cap, or a missing key raises instead of falling back to `fake`.

## 7. Cost control

- The default provider is free and offline. Every ledger row for it records
  cost `0`.
- For `cloud`, both `HOMEFILE_RUN_COST_CAP_USD` and
  `HOMEFILE_DAILY_COST_CAP_USD` must be greater than zero. `ProviderGuard`
  refuses a call that would exceed either cap and writes a ledger row for the
  refusal.
- Prices are operator-supplied per 1000 tokens, so the estimate is only as
  accurate as those values.
- Inspect spend with `homefile ledger` and `homefile stats`.

## 8. Backup and restore

Back up the whole data directory, including `key.bin`:

```bash
# stop the server first, or use SQLite's backup API
tar czf homefile-backup.tgz -C <parent> <data-dir>
```

Restore by extracting the archive and pointing `--data-dir` or
`HOMEFILE_DATA_DIR` at it. `init_db` migrates an older database to schema
version 4 on open (version 1 gains reminder/deletion actor columns, and
version 4 gains document provenance and warning columns).

For a portable copy that does not need `key.bin`, use
`homefile export-all --passphrase <passphrase>`. It writes one `.hfe` archive
under `exports/` containing metadata and every distinct original; without a
passphrase the archive is a plaintext `.zip`.

If `key.bin` is lost, blobs cannot be decrypted; `homefile verify` reports
every one as a mismatch. Extracted text and fields survive because they are in
SQLite.

## 9. Integrity checks

```bash
homefile verify     # exit 1 if any blob is missing, corrupt, or orphaned
homefile stats      # document, page, field, reminder, spend counts
```

`verify` re-reads each blob, checks SHA-256, decrypts with AES-GCM, and reports
files in `blobs/` that no document references. It does not modify anything.
Run it after a crash, a partial backup, or a suspicious filesystem event.

## 10. Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `No text layer and no OCR engine` | Image or scanned PDF without the OCR extra | `pip install -e ".[ocr]"` and install Tesseract, or import a text PDF |
| `That file is already in the library` | SHA-256 matches an existing document | Use `homefile list`; there is no second copy |
| `UnsafeContent: ... active content` | PDF contains a token from the active-content list or `/Encrypt` | Treat the file as untrusted; do not import it |
| `ProviderError: network access is disabled` | `HOMEFILE_ALLOW_NETWORK` is not `1` | Set it only if you intend to send text to that provider |
| `DeletionError: ... still present` | A row, blob, or FTS entry survived | Read `remaining`; the command already recorded `verified=0` in `deletion_log` |
| `Port already in use` | Another `homefile serve` is running | Use `--port` or stop the other process |
| `verify` reports a mismatch | Blob altered, truncated, or key replaced | Restore the data directory from backup; do not delete the report |

There is no log file. The server prints one line at startup and errors to
stderr; the CLI prints a JSON error object or a human message.

## 11. Upgrade and reset

- There is no released upgrade path. The schema version is stored in
  `schema_meta`; `init_db` migrates version 1 to version 3 in place. Back up
  before running a newer checkout against an existing library.
- To reset, stop the server and delete the data directory. This destroys the
  key, every blob, and every derived record. The web UI equivalent is
  `/settings` with the typed `DELETE` confirmation.
- To keep documents but start fresh metadata, export each document first;
  there is no bulk re-import path that preserves corrections.

## 12. Verification gates

Before shipping a change, run the same four gates as CI:

```bash
ruff check .
mypy
pytest -q
python -m homefile smoke --work-dir .smoke-ci
```

`smoke` runs the full import, search, correction, reminder, export, and
deletion workflow on synthetic documents in a temporary directory and exits
non-zero if any promise fails. It does not clear an existing `--work-dir`;
delete `.smoke-ci` before re-running locally.

### UI gate (optional, needs a browser)

`scripts/ui-check.mjs` drives the real pages in Chromium and fails on an
axe-core violation at serious or critical impact, horizontal page overflow, or
a CSP console error. It also writes screenshots to `.ui-tmp/shots`.

It is not part of `pytest` or CI: it needs a Chromium binary and two npm
packages, which the local-only, `$0` constraint keeps out of the repository.
Install them once next to the checkout, then run it from the repository root:

```bash
mkdir -p ../.ui-tools && cd ../.ui-tools && npm install playwright-core axe-core
cd - && UI_TOOLS=../.ui-tools node scripts/ui-check.mjs
```

It covers five pages at 320, 390, 768, 1024, and 1440 px. Re-run it after any
change to `app.css`, `render.py`, or a page template. The script also reports
the widest overflowing elements, which is faster than guessing from the
screenshot.
