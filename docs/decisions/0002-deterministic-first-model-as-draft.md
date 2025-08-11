# ADR 0002: Deterministic extraction first, model output as a draft

- Status: accepted
- Date: 2026-10-20

## Context

Field extraction could be model-first, rules-first, or rules-only. Model-first
would need network access, credentials, per-import cost, and a trust story for
every field. Rules-only would be free and auditable but brittle on unfamiliar
layouts. The portfolio plan requires a zero-cost default and forbids
unapproved cloud uploads.

## Decision

Deterministic parsers in `parsers.py` produce every field by default. The
default provider is `fake`, which is a deterministic offline extractor, not a
language model. A real provider is optional and opt-in.

When a provider is enabled, its output is a draft, not a value:

- It may only fill field names that deterministic parsing did not produce.
- Its quote must be locatable in the cited page, and its citation must fit the
  stored text.
- Confidence is capped at 0.6.
- Its `doc_type` is validated and then discarded; document type stays
  deterministic.
- It cannot create reminders.

Every field, whatever produced it, stores `source`, `confidence`, a citation,
and a `field_history` row with action `extracted`.

