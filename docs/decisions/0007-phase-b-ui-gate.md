# Decision record: Phase B UI/UX gate

- Date: 2026-10-21
- Target: `open-home-file`
- Scope: Phase B (UI/UX) for the local web UI
- Result: **pass**, with the accepted limitations listed in §6

## 1. What this record decides

The UI/UX plan sets a release gate: axe-core clean, keyboard-complete flows,
measured contrast, 320-1440 px without horizontal overflow, and rendered
screenshots inspected at each breakpoint. This record states what was run, what
was observed, and what is deliberately not covered.

## 2. Defects found by the gate and fixed

| Defect | Cause | Fix |
|---|---|---|
| Confidence bars rendered empty in the browser | The meter set its fill with `style="width:90%"`, and the page CSP is `style-src 'self'`, so the browser dropped the attribute silently. No console error, no test failure. | `render.confidence_meter` now emits an inline `<svg>` with a `width` presentation attribute; the value is text as well (`90% · above confirmation threshold`). |
| Five static inline `style="margin-top: …"` attributes were also being dropped | Same CSP rule | Replaced with `.section-gap` / `.section-gap-sm` utilities in `app.css`. |
| Tapping a field on a narrow screen put the citation heading under the sticky header | `scrollIntoView({block:"start"})` ignored the two-row mobile header | `app.js` measures `.app-header` and scrolls with an explicit offset; `.citation-pane` also carries `scroll-margin-top`. |
| Page tabs had no gap between label and count | `display:inline-flex` without `gap` | `gap: var(--space-2)` on `.page-tab`. |
| A long data directory pushed the page wider than 320 px | `.mono` had no break opportunity, and `.notice-strip` children could not shrink | `overflow-wrap: anywhere` on `.mono`; the wrap is data-dependent, so it only appears when the configured path is long. |
| The 4 nav labels overflowed 320 px | `.nav-list` was a single non-wrapping row | `flex-wrap: wrap` below 26rem, so every destination stays visible. |
| The 6-column reminders table hid ~200 px of columns between 320 and 768 px | An inner scroller with no visible affordance | Below 48rem each row stacks into labelled lines (`data-label` + `td::before`); explicit `role` attributes keep table semantics under `display: block`. |

The CSP interaction is the important one: the failure mode is invisible to both
the test suite and the browser console, so `tests/unit/test_web_pages.py`
now asserts that no rendered page contains a `style="` attribute.

## 3. Commands run and observed output

Browser: Chrome (system install) driven by `playwright-core`, against
`python -m homefile --data-dir .ui-check serve --port 8795`.

```text
axe-core, violations (serious+critical) per page and width
  home@390 clean | home@1440 clean
  documents@390 clean | documents@1440 clean
  detail@390 clean | detail@1440 clean
  reminders@390 clean | reminders@1440 clean
  settings@390 clean | settings@1440 clean
  total violations: 0 on every page

horizontal overflow (scrollWidth - clientWidth) at 320/390/768/1024/1440
  every page: 0 px
zoom 200% (720 CSS px viewport, deviceScaleFactor 2): 0 px

CSP console errors on a full page load: none
inline style attributes in rendered HTML: 0 (asserted in tests)

`node scripts/ui-check.mjs` now also drives the flows and the keyboard, and
reports every check it executed so a skipped check cannot pass silently:

  ui gate clean: 5 pages x 5 widths, 15 flow/keyboard checks
  checks: search, search-snippet, field-selection, field-announcement,
          field-aria-current, correction, correction-history,
          reminder-confirm, reminder-visible, skip-link-first, focus-visible,
          slash-shortcut, tab-arrow, tab-single-selection, tab-panel-visible

confidence meter: fill/track = 278/309 px = 0.90, text "90% · above confirmation threshold"
table width per viewport (scrollWidth / clientWidth of .table-wrap)
  320 252/252  390 322/322  480 404/404  640 564/564  768 692/692
  900 808/808  1440 1124/1124   (reminders, 6 columns; documents and home equal)
  no table scrolls at any width; before the fix reminders was 599/404 at 480
mobile citation jump: citation top = 110 px, sticky header height = 98 px
flash message vs h1 bounding boxes: no overlap (flash y=814, h1 y=88)
focus ring: box-shadow "0 0 0 2px canvas, 0 0 0 4px focus"
```

Keyboard and screen reader behaviour:

- Tab order on home: skip link → brand → nav links → primary action → file
  input. Every stop had a visible focus ring.
- Detail page: `Enter` on a field row moves selection and the citation, focus
  lands on the citation pane (`data-citation-pane`), and the `aria-live`
  region announces "vendor on page 1. Citation: …".
- Page tabs: `ArrowRight` moves focus and selection, `Enter` keeps one panel
  visible.
- Delete flow: the phrase field is `required pattern="DELETE"`, and the
  confirmation page names the blob, page text and FTS entries, fields, history,
  reminders, import records, and export files.

Task flow exercised end to end in the browser (`.ui-check` library):

```text
import duplicate file      -> "1 file was already in the library." + import row marked DUPLICATE
open document              -> citation rail shows field, value, 90% confidence, page 1, offsets 409-419
correct vendor             -> "Correction saved. The original value is kept in history."
                              history keeps "NORTHWIND HARDWARE LTD -> NORTHWIND HARDWARE LIMITED"
confirm reminder (POST)    -> 303 to ?flash=reminder-confirmed, suggested list drops to 0
export document            -> exports/doc-<id>-<stamp>.hfe written
export library             -> exports/library-<stamp>.hfe, read back with the passphrase:
                              5 files, 4 originals, every original hash matches a document
delete document            -> "Document deleted and removal verified."
settings                   -> "Deletions verified 1"
first run (empty library)  -> "Your library is empty" + "Import synthetic samples"
                              -> "Imported 3 synthetic sample documents."
```

`read_export` round trip of the library archive: `format
open-home-file/library-export/1`, 4 documents, 5 pages, fields and reminders
present, all 4 original hashes present in the document set.

## 4. Design decisions taken here

- **Meter form.** An inline SVG rather than `<meter>`: `<meter>` styling is
  inconsistent across engines, and the fill must be exact. The value is also
  present as text, so the bar is never the only carrier of the number.
- **Spacing utilities instead of inline styles.** The CSP is the stronger
  constraint; utilities keep the rule enforceable by a test.
- **Scroll offset from measured header height**, not a hard-coded constant,
  because the header wraps to two rows below 48rem.

## 5. Permanent test added

`tests/unit/test_web_pages.py` renders every page from a real library and
asserts: no inline style attributes, flash/error live regions and escaping,
meter markup, a citation for every field, reminder actions matching reminder
state, named data classes on the delete page, storage and retention on the
settings page, provenance disclosure, the unreadable-document explanation, and
a CSRF token in every POST form.

## 6. Accepted limitations

- The UI was verified in Chrome only. Firefox and Safari are unverified. The
  stylesheet relies on `color-mix()` (7 uses, for tinted borders and the
  citation highlight) and on no `:has()`; both are supported in current
  Firefox and Safari, but that is an expectation, not a measurement.
- No real screen reader was driven. `aria-live`, tab semantics, and focus order
  were checked through the DOM and keyboard only.
- OCR was unavailable on the verification machine (no Tesseract), so the
  OCR-success path is covered by unit tests with a stub engine, not by the
  browser.
- Screenshots are stored under `.ui-tmp/` (git-ignored). They are evidence for
  this record, not shipped assets.
