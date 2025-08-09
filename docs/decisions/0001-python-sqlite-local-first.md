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

## Consequences

- Installation is `pip install -e .` plus a Python interpreter. No native
  packaging step and no Electron download.
- The web UI can be stopped by stopping the process; there is no supervisor,
  no restart policy, and no background processing to reason about.
- Everything is single-user and single-machine. Concurrency is limited to the
  server's request threads over SQLite with a 15-second busy timeout.
- There is no remote access story. Adding one would require authentication,
  TLS, and a different storage decision, so it is out of scope.
- Python's startup time makes short CLI calls slower than a native binary; this
  was accepted for auditability and dependency simplicity.
