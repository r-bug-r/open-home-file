# Privacy

This document states what Open Home File stores, where it stores it, and what
leaves the machine. It describes the code in `src/homefile/` as it exists.

## 1. Summary

- The default configuration makes no network calls. The provider is `fake`,
  which is a deterministic offline extractor, not a language model.
- Everything lives in one data directory chosen by `HOMEFILE_DATA_DIR` or the
  platform default. There is no account, no sync, no telemetry, and no update
  check.
- Original files are encrypted at rest. Extracted text, fields, reminders, and
  the search index are plaintext inside `homefile.sqlite3`.
- Nothing is uploaded unless you set `HOMEFILE_ALLOW_NETWORK=1` and select
  `ollama` or `cloud` as the provider. In that case only the extracted text of
  the document being imported is sent, capped at 6000 characters.
- Deletion removes rows and files and verifies the result. It is not secure
  erasure.

## 2. What is stored

| Data | Location | Protection |
|---|---|---|
| Original PDF, PNG, or JPEG bytes | `blobs/<sha256>.hbf` | AES-256-GCM, key in `key.bin`, content hash bound as associated data |
| Page text and the FTS5 index | `pages.text`, `pages_fts` in `homefile.sqlite3` | none; plaintext |
| Extracted fields and citations | `fields`, `field_history` | none; plaintext |
| Document provenance and processing notes | `documents.processed_by`, `documents.warnings` | none; names a remote provider only when one was used, never document text |
| Reminders | `reminders` | none; plaintext |
| Provider ledger | `ledger` | none; contains provider, model, token counts, estimated cost, and error class, never prompts or responses |
| Import and deletion records | `imports`, `deletion_log` | none; import rows keep the sanitized filename and an error class; deletion rows deliberately exclude document content and filename |
| Export bundles | `exports/<doc-id>-<timestamp>.zip`/`.hfe`, or `exports/library-<timestamp>.zip`/`.hfe` | plaintext zip by default; AES-256-GCM with an scrypt-derived key when a passphrase is supplied |
| Library key | `key.bin` | mode 0600 on POSIX; on Windows the profile ACL governs access |

`key.bin` sits beside the ciphertext. Anyone who can read the whole data
directory can decrypt every blob. The database is not encrypted at all. See
`docs/threat-model.md` for the reasoning and the accepted risk.

## 3. What leaves the machine

Nothing, in the default configuration.

Three things can change that, and all are explicit:

1. **`HOMEFILE_PROVIDER=ollama` with `HOMEFILE_ALLOW_NETWORK=1`.** The first
   6000 characters of extracted text for the document being imported are sent
   to `HOMEFILE_OLLAMA_URL` (default `http://127.0.0.1:11434`). The code does
   not verify that this URL is loopback; point it at a remote host and the text
   travels there.
2. **`HOMEFILE_PROVIDER=cloud`.** The same text is sent to
   `HOMEFILE_CLOUD_BASE_URL` with the API key from the environment variable
   named by `HOMEFILE_CLOUD_API_KEY_ENV`. This requires network access, a base
   URL, a model, both prices, non-zero per-run and daily cost caps, and the
   key. A zero cap refuses every paid call.
3. **You export a document or the whole library and move the bundle
   yourself.** Exports are not uploaded; they are written to `exports/`
   inside the data directory.

The test suite blocks socket connections, so an accidental network call in the
default configuration fails the tests rather than passing silently.

There is no telemetry, analytics, crash reporting, or update check in the code.
`/healthz` returns a literal `{"ok":true}` and is served on loopback only.

## 4. Data sent to a provider

When a remote provider is enabled:

- Input: at most 6000 characters of extracted page text per import, plus the
  prompt in `providers.py`. Page text is the document's own text layer or OCR
  output, so it can contain names, addresses, account numbers, and signatures.
- Output: a JSON object with a document type and candidate fields. It is
  validated and treated as a draft; a field is only stored if its quote can be
  located in a stored page.
- Ledger: one row per attempt with provider, model, token counts, estimated
  cost, and success or error class. No prompt, response, or document text is
  written to the ledger.
- Redaction: none. There is no field allowlist and no automatic removal of
  account numbers or names before sending.

The provider's own retention policy is outside this project's control. Use
Ollama on loopback if the text must stay on the machine.

## 5. Web UI

- Binds to `127.0.0.1`, `localhost`, or `::1` only. `serve` refuses any other
  host.
- Plain HTTP. If you put a proxy in front of it, the proxy owns TLS and access
  control.
- No accounts and no authentication. The CSRF token prevents cross-site form
  submission from a browser; it is not a login. Any local process that can
  reach the port can act as you.
- Loads no external assets. The CSP allows only self-hosted CSS and JS; there
  are no fonts, images, or scripts fetched from a third party.
- The `homefile_csrf` cookie is `HttpOnly` and `SameSite=Strict`, and is not
  marked `Secure` because the server is plain HTTP on loopback.
- The header shows the processing mode. A document detail page states whether
  it was processed locally or sent to a named remote provider, using
  `documents.processed_by`. The fake provider and a local Ollama instance are
  reported as local.

## 6. Retention and deletion

- Documents stay until you delete them. There is no automatic expiry.
- `homefile delete <doc-id>` or the web delete form removes the document row,
  pages, fields, field history, reminders, import records, the encrypted blob,
  and exports whose name starts with the document id. It then counts rows,
  checks the deleted pages' own FTS rows by `rowid`, and checks the blob file.
  If anything remains, the command raises `DeletionError` and records
  `verified=0`.
- `deletion_log` keeps the document id, SHA-256, timestamp, what was removed,
  whether verification passed, and the actor. It does not keep the filename or
  any text.
- Deletion is not secure erasure: SQLite may retain data in free pages, WAL
  frames, and backups, and filesystems, snapshots, and SSDs may retain the
  blob. Use full-disk encryption if that matters.
- `homefile verify` re-hashes and decrypts every blob and reports orphans and
  mismatches. It does not modify anything.

## 7. Backups

Copy the whole data directory, including `key.bin`, or the blobs are
unreadable. A backup of the database without the key still exposes all
extracted text, because the database is plaintext. Encrypt the backup with
your own tooling if it leaves the machine.

## 8. Children and sensitive documents

The tool is a local index, not a compliance product. It does not classify
documents as sensitive, does not redact, and does not give legal or financial
advice. Extracted values are candidates for a human to confirm.

## 9. Reporting a privacy problem

Open an issue that describes the behaviour without including real document
content, or report privately as described in `SECURITY.md`.
