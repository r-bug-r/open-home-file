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
| Reminders | `reminders` | none; plaintext |
| Provider ledger | `ledger` | none; contains provider, model, token counts, estimated cost, and error class, never prompts or responses |
| Import and deletion records | `imports`, `deletion_log` | none; deletion rows deliberately exclude document content and filename |
| Export bundles | `exports/<doc-id>-<timestamp>.zip` or `.hfe` | plaintext zip by default; AES-256-GCM with an scrypt-derived key when a passphrase is supplied |
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
3. **You export a document and move the bundle yourself.** Exports are not
   uploaded; they are written to `exports/` inside the data directory.

The test suite blocks socket connections, so an accidental network call in the
default configuration fails the tests rather than passing silently.

There is no telemetry, analytics, crash reporting, or update check in the code.
`/healthz` returns a literal `{"ok":true}` and is served on loopback only.

