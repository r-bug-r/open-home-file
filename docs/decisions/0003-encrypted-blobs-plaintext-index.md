# ADR 0003: Encrypt original blobs, keep the index plaintext

- Status: accepted
- Date: 2026-10-20

## Context

The plan asks for encrypted storage and searchable text. Options were:

1. Encrypt nothing.
2. Encrypt blobs and the whole database (SQLCipher or an encrypted container).
3. Encrypt blobs, leave SQLite plaintext, and document the gap.
4. Encrypt individual columns and build a separate encrypted index.

Option 2 adds a native dependency or a whole-container story and complicates
backup and migration. Option 4 requires a searchable-encryption scheme; a naive
one leaks through the index anyway, and a serious one is out of scope for a
prototype.

## Decision

Option 3. Original bytes are sealed with AES-256-GCM (`HBF1`) in a
content-addressed store, with the SHA-256 of the plaintext bound as associated
data. The key is 32 random bytes in `key.bin`. SQLite, including `pages.text`,
the FTS5 index, fields, and reminders, is plaintext.

The limitation is stated in `docs/architecture.md`, `docs/threat-model.md`
(T11), and `docs/privacy.md` rather than implied away.

## Consequences

- A stolen `blobs/` directory alone is not readable; a stolen data directory
  is, because the key sits beside it.
- Search is fast and simple: FTS5 over plaintext, no per-query decryption and
  no index leakage analysis.
- Anyone who can read the database can read every extracted value, which
  duplicates much of the sensitive content of the originals. Full-disk
  encryption is the recommended mitigation.
- Key loss means blob loss; extracted metadata survives.
- There is no key rotation. Adding one later requires re-sealing every blob and
  a schema field for key generation.
- Moving to SQLCipher is a contained change if it is ever justified, because
  only `db.py` opens connections.
