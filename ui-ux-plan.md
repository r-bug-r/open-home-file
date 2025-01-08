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

### 1.5 Accessibility and responsive gates

Before a UI release:

- Run axe-core and fix all serious/critical findings; document accepted false positives.
- Tab through every flow without a mouse; focus must remain visible and ordered.
- Test with a screen reader on the primary workflow and verify headings, labels, status announcements, dialog focus, and table relationships.
- Meet WCAG 2.2 AA contrast targets: 4.5:1 normal text, 3:1 large text and essential UI indicators.
- Use 44px minimum touch targets for compact controls where practical; never make a primary action smaller than 44px high.
- Use `aria-live="polite"` for asynchronous result/status updates and `role="alert"` only for urgent errors.
- Test zoom at 200% and text-only reflow at 320px.
- Check `document.documentElement.scrollWidth - document.documentElement.clientWidth === 0` at 390px, 768px, 1024px, and 1440px.
- Render screenshots at each breakpoint and inspect them for overlap, clipping, ragged alignment, unreadable density, and broken focus states.
- Use `min-width: 0`, `overflow-wrap: anywhere`, wrapping toolbars, reserved status heights, and `body { overflow-x: clip; }` as a backstop. The backstop does not replace root-cause fixes.

### 1.6 UI implementation sequence

1. Write the task flow and acceptance states.
2. Create tokens and a semantic component inventory.
3. Design the primary screen in a plain local fixture with real-length copy.
4. Add all states before adding visual polish.
5. Implement keyboard and screen-reader behavior.
6. Add responsive rules and verify narrow overflow.
7. Add restrained motion and reduced-motion behavior.
8. Run browser screenshots, axe checks, and a fresh-eyes critique.
9. Fix measured gates first, then deliberate visual signals.
10. Record the design decision and ship a changelog entry.

---

---

# 6. UI/UX Plan: Open Home File

## User task

A person imports a document, verifies extracted fields against the source, corrects an error, creates a reminder, and can later export or delete everything.

**Primary task flow:** import -> process locally -> inspect citation -> correct -> confirm reminder -> search later -> export/delete.

## Information architecture

- **Home:** upcoming deadlines, recent documents, processing queue.
- **Documents:** search, filters, document list, import.
- **Document detail:** source preview, extracted fields, citations, correction history.
- **Reminders:** upcoming, dismissed, completed, and source document.
- **Settings:** local/cloud mode, storage location, retention, export, deletion.

## Visual direction

Use calm editorial utility: warm paper canvas, clear document outline, restrained green for confirmed state, amber for needs review, and no dense dashboard chrome. The memorable anchor is a **citation rail** that visually links each extracted field to a page or text range in the original document.

## Screens and acceptance criteria

### A. Home and import

Make import the primary action. Show local-only status prominently. Use a drop zone plus file picker, with file-type and size rules before processing.

States:

- First-run empty state with a synthetic sample option.
- Processing queue with per-document state.
- Unsupported file, oversized file, OCR failure, and partial extraction states.
- Offline state that explains local processing remains available.

### B. Document detail

Desktop: source preview on the left, extracted fields in the center, citation/metadata rail on the right. Mobile: source and field sections stack; selecting a field scrolls to the citation and announces the connection.

Fields show value, confidence, source page/offset, last corrected time, and correction action. Reminder creation is adjacent to date fields and requires confirmation below the confidence threshold.

Acceptance:

- Every reminder has a source citation.
- A correction never removes the original extracted value from history.
- A user can tell whether the document stayed local or was sent to a provider.

### C. Search and reminders

Use real search terms and document-type filters. Empty search has an actionable explanation. Reminder rows show due date, source document, status, and quick complete/snooze controls.

### D. Privacy and deletion

Settings must show storage path, processing mode, provider status, retained data classes, export, and delete-all controls. Delete confirmation names originals, OCR, thumbnails, indexes, reminders, and backups that will be affected.

## UI verification

- Import synthetic receipt and warranty fixture.
- Correct warranty date, confirm reminder, search by vendor/serial, export, delete, and verify no result remains.
- Run local-only mode with network disabled; verify the UI does not imply cloud processing.
- Test citation focus and keyboard operation.
- Axe scan, 200% zoom, 320px reflow, and narrow overflow check.
- Review screenshots for document readability, source/field relationship, and absence of nested-card clutter.

---
