# Decision record: entry condition and Phase A gate

- Date: 2026-10-20
- Target: `open-home-file`
- Entry decision: **start**
- Phase A gate: **pass**
- Phase B: **entered on 2026-10-20 after this record**

## 1. Entry condition

The portfolio prompt requires a viable local document-security and deletion
approach before implementation. Evidence from the repository:

- At-rest protection exists in code: `crypto.seal`/`open_sealed` (AES-256-GCM,
  SHA-256 bound as associated data), `store.BlobStore` (content-addressed,
  0600 temporary file, fsync, rename), `crypto.load_or_create_key` (32 random
  bytes, `key.bin`, 0600 on POSIX). Verified by `tests/unit/test_crypto_store.py`
  and by `homefile verify` in the smoke scenario.
- Deletion is implemented and verified rather than asserted:
  `Library.delete_document` removes derived rows and the blob, counts the
  deleted pages' own FTS rows, checks the blob path, writes a `deletion_log`
  row, and raises `DeletionError` if anything remains. The integration suite
  covers the clean path and the failing path, and the smoke scenario deletes a
  document and re-checks integrity.
- The gaps are stated rather than hidden: the SQLite database and FTS index are
  plaintext, `key.bin` sits beside the ciphertext, there is no parser sandbox,
  and deletion is logical removal, not secure erasure. See
  `docs/threat-model.md` (T8, T11, T12) and `docs/privacy.md`.

No security review board, consent, or paid resource is required for the local
synthetic-data path. The entry condition is met on repository evidence, so the
target is not deferred.

## 2. Phase A implementation evidence

All ten MVP requirements from `../open-source-projects-plan.md` §7 are
implemented in `src/homefile/`:

| # | Requirement | Where |
|---|---|---|
| 1 | Import PDFs and images through a local UI or CLI | `cli.py:import`, `web/server.py:/import` |
| 2 | Store originals encrypted or user-controlled | `crypto.py`, `store.py`, `key.bin` |
| 3 | Extract text with OCR and classify type | `extract.py`, `classify.py`, `fixtures.py` |
| 4 | Fields with citations to page and text offsets | `parsers.py`, `models.Citation`, `fields` table |
| 5 | Search text, vendor, amount, date, serial, deadline | `Library.search` |
| 6 | Reminders for warranty, renewal, cancellation | `parsers.reminder_kind_for`, `reminders` table |
| 7 | Correction with provenance for every field | `correct_field`, `field_history` |
| 8 | Export originals, metadata, reminders | `export_document`, `read_export` |
| 9 | Local models and optional configured cloud | `providers.py`, `ProviderGuard` |
| 10 | Delete documents and derived data per documented behavior | `delete_document`, `delete_all`, `deletion_log` |

Implementation sequence 1-9 from the plan is complete. Item 10 is the consented
household pilot, which requires real people and consent; it is a rollout step,
not a code gate, and is not claimed here.

## 3. Commands run and observed outcomes

Run in this repository on 2026-10-20, Python 3.12:

```bash
python -m ruff check .
# All checks passed!

python -m mypy
# Success: no issues found in 21 source files

python -m pytest -q
# 112 tests collected; full run passed (72 + 40 progress marks, exit 0)

rm -rf .smoke-ci
python -m homefile smoke --work-dir .smoke-ci
# {"ok": true, "failures": [], ...}
```

Smoke scenario observed steps: import of `receipt.pdf`, `warranty.pdf`,
`subscription.pdf`, and an image without OCR; search by vendor and serial;
correction with history; reminder confirmation; encrypted export; verified
deletion; final integrity check. Every step reported success and the process
exited 0.

Before the gate, the actual web application was started
(`python -m homefile --data-dir web-demo/data serve --port 8794`) and exercised
in a real browser: file upload, duplicate detection, image import without OCR,
document detail, citation selection, correction, reminder confirmation,
export, and deletion. Two defects were found and fixed in that pass:

1. The detail page claimed "the text was indexed" for a page with no text
   layer; the empty state is now conditional on `TextSource.NONE`.
2. A page without text rendered an empty source panel; it now states why there
   is nothing to quote.

Known limitations carried into Phase B (documented, not regressions):

- SQLite and the FTS index are plaintext; the library key is not passphrase
  protected.
- Citation spans are character ranges; bounding boxes exist in the schema but
  are never populated.
- The PDF active-content check is a byte-token scan, not a parser sandbox.
- OCR requires the optional extra and a local Tesseract binary.
- The web UI has no authentication; the CSRF token is a request-forgery
  control, not a login.
- There is no rate limit beyond per-file, per-request, and page caps.

## 4. Decision

Phase A gate passes on the evidence above, so Phase B (UI/UX plan and design
implementation) is entered. The Phase B record is
`docs/decisions/0007-phase-b-ui-implementation.md`.

## 5. Cross-project work deferred

None. All changes so far are inside `open-home-file/`; no shared root file,
sibling project, or portfolio plan was modified.
