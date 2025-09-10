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

