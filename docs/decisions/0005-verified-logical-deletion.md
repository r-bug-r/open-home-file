# ADR 0005: Deletion is verified logical removal, not secure erasure

- Status: accepted
- Date: 2026-10-20

## Context

The plan requires deletion that the user can trust. Options were: best-effort
row deletion, verified logical removal with a failure report, or overwriting
storage.

Overwriting storage is not reliably implementable from an application:
SQLite free pages, WAL frames, filesystem snapshots, backups, and SSD wear
levelling all retain copies. Promising erasure would be false.

## Decision

Delete inside one transaction and then verify. `delete_document`:

1. Collects the page row ids, then removes `fields`, `field_history`,
   `reminders`, `imports`, `pages`, and the `documents` row.
2. Unlinks the encrypted blob and any export whose filename starts with the
   document id.
3. Runs count queries and counts the deleted pages' own `pages_fts` rows by
   `rowid`.
4. Writes a `deletion_log` row with `removed`, `remaining`, and `verified`.
5. Raises `DeletionError` if anything remains, so the caller cannot report a
   clean deletion that did not happen.

The log records the document id, hash, timestamp, what was removed, whether
verification passed, and the actor. It does not record the filename or text.

## Consequences

- A user sees a real failure instead of a silent partial delete.
- Verification is by row count and file existence, not byte-level inspection
  of the database file, so it cannot detect data in free pages or WAL.
- Secure erasure remains out of scope; full-disk encryption and encrypted
  backups are the documented mitigations.
- The append-only deletion log itself is a record that a document existed. It
  is deliberately minimal, but it is not erasable through the UI.
