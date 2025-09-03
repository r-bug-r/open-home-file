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

## Consequences

- A malicious website cannot drive the UI through a form post from a browser
  without the token, which it cannot read cross-origin.
- The token is not authentication. Any local process can fetch a page, read
  the token, and submit, so the security boundary is the local account.
- There is no TLS. A reverse proxy would need to add TLS and access control,
  and the CSP assumes same-origin self-hosted assets only.
- The cookie is not `Secure`, because the transport is plain HTTP on loopback.
- `Origin: null` is accepted for non-browser clients, which keeps the CLI and
  scripts working at the cost of weakening the check for those callers.
- There is no `Host` header validation; DNS rebinding protection relies on
  loopback binding.
