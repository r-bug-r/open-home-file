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

## Seeking consensus

For a non-urgent proposal:

1. Open an issue that states the problem, the constraints, and at least one alternative.
2. Leave it open for comment. Seven days is the usual minimum for a design change; longer is fine for anything that affects stored data or privacy.
3. Prefer lazy consensus: if no substantive objection remains and the maintainer agrees, proceed and record the decision.
4. If objections remain, the maintainer decides and writes the reasoning, including the dissenting view, into the decision record.

Consensus here means that concerns were heard and addressed, not that everyone voted yes. Contributors who cannot reach agreement with the maintainer should say so plainly in the issue; that objection is recorded even when the decision goes the other way.

Urgent fixes, documentation corrections, and dependency updates that do not change behavior may proceed by pull request without a separate issue.

## Adding maintainers

Maintainership is earned through sustained work, not requested by title. A candidate typically has:

- A track record of merged contributions over several months, not a single large patch.
- Reviews that show good judgment about citations, privacy, and failure modes.
- Participation in triage or documentation, not only code.
- A clear understanding of the local-first constraints: no default network access, no telemetry, no real user data in the repository.

The process:

1. An existing maintainer nominates the candidate in a decision record.
2. The nomination is public and open to comment for at least fourteen days.
3. The maintainer accepts or declines and records the result.

New maintainers start with review and triage responsibilities. Access to release credentials and security advisories is granted only when needed for a specific role. If a maintainer becomes inactive for twelve months, the remaining maintainers may move them to emeritus status in a decision record; this is not a judgment about the person.

## Security fixes

A confirmed security fix may be developed, reviewed, and merged without prior public discussion. The report stays private in a GitHub security advisory, the fix includes a regression test, and disclosure follows once users can update. See [SECURITY.md](SECURITY.md).

The maintainer may also make a minimal emergency change to a release or CI configuration without a decision record when waiting would leave users exposed. The change is documented afterward.

## Changing this document

Changes to governance use the same path as any other design change: an issue for discussion, then a decision record and a pull request. The maintainer does not edit this document unilaterally to expand their own authority.
