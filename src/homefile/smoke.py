"""End-to-end smoke scenario.

This is the executable version of the plan's acceptance checklist. It runs the
whole workflow on synthetic documents inside a temporary directory, asserts
each promise, and returns a report of what was actually observed.

Run with ``homefile smoke`` or ``python -m homefile.smoke``.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from . import crypto, fixtures
from .config import Settings
from .extract import NullOcr
from .models import FieldName, FieldStatus, ReminderStatus
from .service import Library


@dataclass(slots=True)
class SmokeReport:
    steps: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def step(self, name: str, **observed: Any) -> None:
        self.steps.append({"step": name, **observed})

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(message)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": not self.failures,
            "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "steps": self.steps,
            "failures": self.failures,
        }


def run_smoke(work_dir: Path | None = None) -> dict[str, Any]:
    root = (
        Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="homefile-smoke-"))
    )
    root.mkdir(parents=True, exist_ok=True)
    samples = fixtures.write_samples(root / "samples")
    settings = Settings(data_dir=root / "library")
    library = Library(settings, ocr=NullOcr())
    report = SmokeReport()

    # 1. Import synthetic documents.
    imported = {}
    for name, path in samples.items():
        outcome = library.import_file(path, date_order="dmy", actor="smoke")
        imported[name] = outcome
        report.step(
            "import",
            file=name,
            doc_id=outcome.document.id,
            doc_type=outcome.document.doc_type,
            type_confidence=outcome.document.doc_type_confidence,
            pages=outcome.document.page_count,
            fields=[field.name for field in outcome.fields],
            warnings=outcome.warnings,
        )
        report.require(outcome.document.page_count >= 1, f"{name}: no pages extracted")
        report.require(bool(outcome.fields), f"{name}: no fields extracted")

    image_outcome = library.import_bytes(fixtures.png_bytes(), "scan.png", actor="smoke")
    report.step(
        "import-image-without-ocr",
        doc_id=image_outcome.document.id,
        text_source=str(image_outcome.pages[0].source),
        warnings=image_outcome.warnings,
    )
    report.require(
        any("OCR" in warning for warning in image_outcome.warnings),
        "image import without OCR must warn instead of inventing text",
    )

    # 2. Every extracted value must quote its page.
    for name, outcome in imported.items():
        detail = library.get_document(outcome.document.id)
        for extracted in detail.fields:
            page = next(p for p in detail.pages if p.number == extracted.citation.page)
            quoted = page.text[extracted.citation.char_start : extracted.citation.char_end]
            report.require(bool(quoted.strip()), f"{name}: {extracted.name} citation is empty")
            report.require(
                extracted.value in quoted or quoted.strip() in extracted.value,
                f"{name}: {extracted.name} citation does not contain its value",
            )

    # 3. Search: text, vendor, amount, serial, deadline.
    drill = library.search("cordless")
    report.step("search-text", query="cordless", hits=[hit.doc_id for hit in drill])
    report.require(bool(drill), "text search for 'cordless' found nothing")

    serial_hits = library.search(serial="NWCD-4417-XZ")
    report.step(
        "search-serial",
        hits=[
            {"doc_id": hit.doc_id, "page": hit.page, "field": hit.matched_field}
            for hit in serial_hits
        ],
    )
    report.require(len(serial_hits) == 1, "serial search did not find exactly one document")

    amount_hits = library.search(min_amount="200", max_amount="300")
    report.step("search-amount", hits=[hit.snippet for hit in amount_hits])
    report.require(len(amount_hits) == 1, "amount range search did not find exactly one document")

    deadline_hits = library.search(deadline_before="2027-12-31")
    report.step("search-deadline", hits=[hit.matched_field for hit in deadline_hits])
    report.require(bool(deadline_hits), "deadline search found nothing")

    # 4. Correct the warranty date, then confirm the reminder.
    warranty = imported["warranty.pdf"]
    warranty_field = next(f for f in warranty.fields if f.name is FieldName.WARRANTY_END)
    corrected = library.correct_field(
        warranty_field.id, "2028-04-30", reason="smoke: certificate states April", actor="smoke"
    )
    history = library.history(warranty_field.id)
    report.step(
        "correct-field",
        field_id=corrected.id,
        value=corrected.value,
        original=corrected.original_value,
        version=corrected.version,
        status=str(corrected.status),
        history=[entry.action for entry in history],
    )
    report.require(corrected.value == "2028-04-30", "correction was not applied")
    report.require(corrected.original_value == "2028-03-14", "original value was overwritten")
    report.require(corrected.status is FieldStatus.CONFIRMED, "correction was not marked confirmed")

    reminder = next(item for item in library.list_reminders() if item.field_id == warranty_field.id)
    report.require(
        reminder.status is ReminderStatus.SUGGESTED,
        "a reminder must stay suggested until a human confirms it",
    )
    confirmed = library.confirm_reminder(reminder.id, actor="smoke")
    report.step(
        "confirm-reminder",
        reminder_id=confirmed.id,
        kind=confirmed.kind,
        due_date=confirmed.due_date.isoformat(),
        confirmed_by=confirmed.confirmed_by,
    )
    report.require(confirmed.status is ReminderStatus.CONFIRMED, "reminder was not confirmed")
    report.require(confirmed.due_date < date(2028, 4, 30), "reminder is not before its deadline")
    due = library.due_reminders(on=date(2028, 4, 29))
    report.require(
        confirmed.id in {item.id for item in due}, "confirmed reminder did not appear when due"
    )

    # 5. Encrypted export, verified by decrypting it again.
    passphrase = "smoke-test-passphrase"  # noqa: S105 - throwaway fixture, not a credential
    export_path = library.export_document(warranty.document.id, passphrase=passphrase)
    plaintext = crypto.open_with_passphrase(passphrase, export_path.read_bytes())
    with zipfile.ZipFile(io.BytesIO(plaintext)) as archive:
        names = sorted(archive.namelist())
        original = archive.read(next(name for name in names if name.startswith("original/")))
    report.step(
        "export",
        path=str(export_path),
        bytes=export_path.stat().st_size,
        entries=names,
        original_matches=samples["warranty.pdf"].read_bytes() == original,
    )
    report.require(
        original == samples["warranty.pdf"].read_bytes(), "export lost the original bytes"
    )
    report.require(b"NORTHWIND" not in export_path.read_bytes(), "export is not encrypted")

    # 6. Delete, and prove nothing survived.
    report_before = library.verify_integrity()
    report.require(report_before.verified, "integrity check failed before deletion")
    deletion = library.delete_document(warranty.document.id, actor="smoke")
    report.step(
        "delete",
        doc_id=deletion.doc_id,
        removed=deletion.removed,
        verified=deletion.verified,
        remaining=deletion.remaining,
    )
    report.require(deletion.verified, "deletion could not be verified")
    report.require(deletion.remaining == [], "deletion left artifacts behind")
    report.require(
        all(hit.doc_id != deletion.doc_id for hit in library.search("northwind")),
        "search still returns the deleted document",
    )
    remaining_docs = {document.id for document in library.list_documents()}
    report.require(warranty.document.id not in remaining_docs, "document row survived deletion")
    report.require(
        not (settings.blob_dir / f"{warranty.document.sha256}.hbf").exists(),
        "encrypted blob survived deletion",
    )
    report.require(
        list(settings.export_dir.glob(f"{warranty.document.id}-*")) == [],
        "export survived deletion",
    )

    # 7. Local-only guarantees.
    ledger = library.ledger()
    report.step(
        "ledger",
        calls=len(ledger),
        providers=sorted({entry["provider"] for entry in ledger}),
        spend=str(library.stats()["estimated_spend_usd"]),
        network_allowed=settings.allow_network,
    )
    report.require(
        {entry["provider"] for entry in ledger} == {"fake"},
        "smoke run used a non-local provider",
    )
    report.require(settings.allow_network is False, "network access was enabled")
    report.require(library.verify_integrity().verified, "integrity check failed at the end")

    return report.to_json()


if __name__ == "__main__":  # pragma: no cover - developer helper
    import json
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(run_smoke(target), indent=2))
