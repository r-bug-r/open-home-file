# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Whole-library export (`homefile export-all`, `/settings/export`): one archive with metadata, pages, fields, reminders, and each distinct original, plain ZIP or passphrase-encrypted `.hfe`.
- Import audit trail in the UI: recent attempts include failed and duplicate files with their error text, and a first-run button imports the three synthetic fixtures through the normal validated import path.
- Document provenance and processing notes: `documents.processed_by` records a remote provider that saw page text, `documents.warnings` records per-document processing notes, and the detail page states whether the document stayed local.
- Design token register (`docs/design/token-register.md`) with measured WCAG contrast for every light and dark text/background pair.
- Phase B gate record (`docs/decisions/0007-phase-b-ui-gate.md`) with the measured axe, overflow, keyboard, and end-to-end flow evidence.
- Static project landing page (`docs/index.html`) and social preview (`docs/assets/og.png`) with self-hosted fonts, light/dark themes, and no third-party requests; README now links the project page and separates user versus contributor install steps.

### Changed

- Web UI chrome keeps a fixed header and renders transient status below it, so long messages no longer move page content.
- Below 48rem tables stack each row into labelled lines instead of scrolling sideways; at 320px the navigation wraps so all four destinations stay visible, and long paths and hashes wrap instead of widening the page.
- Import shows a per-file processing queue and disables the submit button while the request is in flight.
- The citation workspace keeps the selected field on one rail, supports arrow/Home/End keys on page tabs, scrolls the citation into view on narrow screens, and keeps working without JavaScript.
- Confidence meters are inline SVG bars instead of `style="width:…"`, because the page CSP (`style-src 'self'`) made the browser drop the inline width and render every bar empty. Section spacing moved from inline `style` attributes to `.section-gap` utilities for the same reason; `tests/unit/test_web_pages.py` fails if any rendered page reintroduces one.
- On narrow screens the citation jump subtracts the measured sticky-header height, so the heading is not hidden under the two-row mobile header.
- Control borders use accessible `--color-border-strong` values; compact controls reach 44px at the mobile breakpoint.
- Schema version 4 adds `documents.processed_by` and `documents.warnings` with an in-place migration.

### Fixed

- Pillow is installed with the base package so PNG and JPEG import works without the OCR extra; the `ocr` extra now contains only the Tesseract binding.

## [0.1.0] - 2026-10-20

First pre-release. Single-user local install; no upgrade path from an earlier version because none exists.

### Added

- Import of PDF, PNG, and JPEG files with SHA-256 content hashing, duplicate detection, configurable file-size and page limits, filename sanitization, and rejection of PDFs containing JavaScript, embedded files, or encryption.
- Page-preserving text extraction with exact character offsets. PDF text layers are preferred; optional local Tesseract OCR handles pages and images without one. Pages that cannot be read are recorded with a warning instead of invented text.
- Deterministic document classification into receipt, warranty, bill, contract, subscription, or unknown, with a confidence score.
- Deterministic field parsers for vendor, amount, serial number, purchase date, warranty end, and other deadlines. Every extracted value carries a page number and character range into the page text.
- Field correction, confirmation, and rejection with actor, reason, and an append-only provenance history that retains the original value.
- Reminder suggestions derived from extracted deadlines with per-kind lead times. Suggestions stay unconfirmed until the user accepts them. In the web UI, extracted values below `HOMEFILE_CONFIRM_BELOW` are marked as needing review. Confirmed reminders can be listed as due, dismissed, completed, or snoozed through the service and web UI.
- Full-text search over page text using SQLite FTS5, plus structured filters for vendor, serial number, document type, amount range, and deadline range.
- Encrypted export bundles containing metadata, pages, fields, history, reminders, and the original file. Bundles are plain ZIP files by default and AES-256-GCM encrypted with a scrypt-derived key when a passphrase is supplied.
- Verified deletion of a document and all derived records, with a report of what was checked and removed, plus a library-wide delete-all path behind a confirmation phrase.
- Loopback-only web UI rendered with the standard library: import, document review with page citations, correction history, reminders, search, export, deletion, and a settings page. Forms use a per-process CSRF token, cross-origin submissions are refused, and a restrictive content security policy is set.
- Provider layer with a deterministic offline `fake` provider as the default, an optional local Ollama adapter, and an optional OpenAI-compatible cloud adapter. Remote providers require `HOMEFILE_ALLOW_NETWORK=1`; the cloud adapter also requires explicit prices, non-zero run and daily cost caps, and an API key from the environment.
- Provider budget enforcement and a cost ledger covering request, token, run-cost, and daily-cost caps, with validation that drops unquoted or unknown model output before it reaches business logic.
- Command-line interface with JSON output by default and a compact `--human` form: `import`, `list`, `show`, `search`, `correct`, `confirm-field`, `reject-field`, `history`, `reminders`, `confirm-reminder`, `dismiss-reminder`, `due`, `export`, `delete`, `verify`, `stats`, `ledger`, `serve`, `smoke`, and `samples`.
- End-to-end smoke scenario that imports synthetic documents and checks citations, search, correction history, reminder confirmation, encrypted export, verified deletion, and final integrity.
- Test suite: four unit suites (parsers, classification and providers, crypto and store, inspection) and one integration suite covering the full workflow.
