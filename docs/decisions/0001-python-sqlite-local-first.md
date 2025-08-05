# ADR 0001: One Python process over one local directory

- Status: accepted
- Date: 2026-10-20

## Context

The portfolio plan requires a local-first prototype that a single household
can install and audit, with a $0 default path. The alternative designs were a
desktop shell application, a client/server split with a remote database, or a
Node/Electron bundle.

## Decision

Ship a single Python 3.12 package that runs as a CLI or as a loopback HTTP
server. All state lives in one directory: one SQLite database, one encrypted
blob directory, one key file. There is no daemon, job queue, or external
service in the default configuration. The CLI and the web layer are adapters
over one `Library` object; neither owns business rules or SQL.

