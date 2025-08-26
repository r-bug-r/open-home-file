# ADR 0004: Loopback-only web UI with a CSRF token, no accounts

- Status: accepted
- Date: 2026-10-20

## Context

The web UI needs to be usable without a login for a single local user, while
not becoming a remote attack surface. Options were: bind to all interfaces with
a password, bind to loopback with no token, or bind to loopback with a
request-forgery token.

## Decision

Bind to `127.0.0.1`, `localhost`, or `::1` only; `serve` raises on any other
host instead of warning. There are no accounts. Every POST requires a
per-process token present both in a `homefile_csrf` cookie (`HttpOnly;
SameSite=Strict`) and in the form, compared with `hmac.compare_digest`, plus an
`Origin`/`Sec-Fetch-Site` check. Destructive actions additionally require the
literal word `DELETE`.

