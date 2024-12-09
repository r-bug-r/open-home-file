# Governance

## Current model

Open Home File is a single-maintainer project. The repository owner is the maintainer and has the final say on scope, releases, and merges. That is a description of the current state, not a permanent constitution; this document says how the project intends to make decisions while it is small and how that can change.

The maintainer is expected to explain decisions in public, not merely announce them. Disagreement is welcome; silent vetoes are not.

## How decisions are recorded

Decisions that change architecture, the storage format, a trust boundary, dependencies, or the project's scope are recorded as numbered files in `docs/decisions/`:

```text
docs/decisions/0001-local-first-stdlib-web-ui.md
docs/decisions/0002-sqlite-plus-encrypted-blobs.md
docs/decisions/0003-fake-provider-default.md
```

Each record uses this shape:

```markdown
# NNNN. Short title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context

The forces at play, including constraints and what was already tried.

## Decision

What was decided, in the present tense.

## Consequences

What becomes easier, what becomes harder, and what is now out of bounds.
```

Rules:

- Numbers are sequential and never reused, even if a record is rejected or superseded.
- An accepted record is not edited to change its decision. Supersede it with a new record and update the status line of the old one.
- A pull request that changes a recorded decision must add or update a record in the same pull request.
- Routine fixes, refactors that preserve behavior, and documentation edits do not need a record.

