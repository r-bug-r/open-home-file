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

