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
- `/settings` runs `verify_integrity` and exposes the delete-everything action,
  which requires typing `DELETE`.

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

