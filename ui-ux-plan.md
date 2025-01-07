# Open Home File — UI/UX Plan

> Project-specific section extracted from `../open-source-projects-ui-ux-plan.md`. Shared UI/UX gates in that source remain authoritative.

## Shared UI/UX Quality Gate (authoritative source excerpt)

## 1. UI/UX quality gate

### 1.1 Product-wide design contract

Every project UI must:

- Put the primary user task first: orient, inspect, act, confirm.
- Use product-specific data and labels; never invent users, testimonials, metrics, or activity.
- Define loading, empty, error, success, disabled, permission, offline, and destructive-confirmation states before implementation.
- Keep primary actions visible at the point where the task ends; avoid scroll-back for approval, save, or export.
- Use semantic HTML, visible keyboard focus, labels, useful error copy, and screen-reader announcements.
- Never rely on color alone to communicate status.
- Use fixed-height persistent chrome and reserve space for transient status so loading or error text cannot move the layout.
- Preserve the user's context when a side panel, modal, filter, or tab changes.
- Make data deletion, provider use, retention, and permission boundaries visible at the moment they matter.
- Support 320, 390, 768, 1024, and 1440 CSS-pixel widths without horizontal overflow.

### 1.2 Shared design stance

**Aesthetic direction:** editorial industrial utility. The interface should feel like a trustworthy working instrument: crisp borders, compact data tables, deliberate whitespace, one restrained accent, and typography that makes hierarchy obvious. Avoid purple SaaS gradients, floating-card stacks, glassmorphism, excessive pills, giant marketing heroes, and decorative AI motifs.

**Differentiation anchor:** every project exposes its most important trust boundary as a visible structural element:

- Maintainer Autopilot: a proposal-to-approval rail.
- Trace-to-Eval: a trace timeline with pass/fail evidence.
- Agent Firewall: an allow/approval/deny decision ledger.
- Gateway: a live budget meter and routing decision.
- Home File: a document citation rail connecting extracted fields to the source page.

If the logo is removed, this anchor should still identify the product.

**DFII estimate:** 11/15 for developer tools and 9/15 for Home File. The direction fits operational products, is feasible with CSS and semantic HTML, performs well without effects, and remains maintainable when tokens are enforced.

### 1.3 Token architecture

Create one versioned token file per product, with names stable across light and dark themes. No component may use an unregistered color or spacing value.

```css
:root {
  --color-canvas: #f5f3ee;
  --color-surface: #fffdf8;
  --color-surface-raised: #ffffff;
  --color-ink: #20221f;
  --color-ink-muted: #646860;
  --color-border: #d6d2c8;
  --color-border-strong: #9a9d94;
  --color-accent: #b6422b;
  --color-accent-ink: #fffaf2;
  --color-success: #356b4b;
  --color-warning: #8c641e;
  --color-danger: #a72f2f;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --radius-control: 0.25rem;
  --radius-panel: 0.5rem;
  --focus-ring: 0 0 0 3px #f5f3ee, 0 0 0 5px #b6422b;
  --motion-fast: 150ms;
  --motion-standard: 220ms;
}
```

These are starting tokens, not measured brand values. Before production, calculate every text/background pair with a WCAG checker and record the ratio in a token register. The accent is for actions and emphasis, not body text unless it passes the contrast gate.

Typography:

- Display: a locally available, licensed serif or strong editorial face such as Newsreader only if its license is verified; otherwise use a local system fallback with no external download.
- Body/UI: a readable sans-serif already available on the platform or a checked open font; do not make a paid font a dependency.
- Data/code: a monospace face only for IDs, hashes, timestamps, policies, token counts, and logs.
- Use a type scale rather than viewport-scaled text. Keep letter spacing at 0 except where a documented all-caps label needs spacing.

Component primitives:

- `AppShell`, `SkipLink`, `PageHeader`, `Breadcrumbs`
- `Button` with text and familiar icon only when the icon improves recognition
- `IconButton` with a tooltip and accessible name
- `StatusBadge` with text plus icon/pattern
- `DataTable` with responsive stacked fallback
- `FilterBar`, `SearchField`, `SegmentedControl`
- `Panel` for genuinely framed tools; do not nest cards inside cards
- `Timeline`, `Diff`, `Citation`, `AuditEvent`
- `Dialog`, `Drawer`, `Toast`, `ConfirmAction`
- `Skeleton`, `EmptyState`, `ErrorState`, `PermissionState`

### 1.4 Interaction and motion

One motion personality per product: **Snap** for developer tools, **Silk** for Home File. Motion communicates state, never decorates the screen.

- 150ms control feedback.
- 220ms panel and drawer transitions.
- Skeleton shimmer only for known content shapes.
- Success confirmation uses a short, non-blocking pop-in.
- No animated KPI numbers, infinite ambient loops, parallax, or delayed primary content.
- Honor `prefers-reduced-motion` by removing transforms and keeping state changes immediate.

