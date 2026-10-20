"""Integration tests: the full workflow through the service layer."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from homefile import crypto, fixtures
from homefile.config import Settings
from homefile.errors import NotFound, UnsafeContent, ValidationError
from homefile.extract import NullOcr
from homefile.models import FieldName, FieldStatus, ReminderStatus, TextSource
from homefile.service import Library


def import_samples(library: Library, samples: dict[str, Path]) -> dict[str, object]:
    return {name: library.import_file(path, date_order="dmy") for name, path in samples.items()}


def test_import_extracts_fields_with_page_citations(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    detail = library.get_document(outcome.document.id)
    assert outcome.duplicate is False
    assert outcome.document.page_count == 1
    assert outcome.document.media_type == "application/pdf"

    for field in detail.fields:
        page = next(page for page in detail.pages if page.number == field.citation.page)
        quoted = page.text[field.citation.char_start : field.citation.char_end]
        assert quoted.strip(), f"citation for {field.name} is empty"
        assert quoted.strip() in field.value or field.value in quoted, (
            f"citation {quoted!r} does not support value {field.value!r}"
        )


def test_warranty_document_yields_deadline_and_suggested_reminder(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    fields = {field.name: field for field in outcome.fields}
    assert fields[FieldName.WARRANTY_END].normalized == "2028-03-14"
    assert fields[FieldName.SERIAL].normalized == "NWCD-4417-XZ"
    assert len(outcome.reminders) == 1
    reminder = outcome.reminders[0]
    assert reminder.status is ReminderStatus.SUGGESTED
    assert reminder.due_date == date(2028, 2, 29)
    assert reminder.due_date < date(2028, 3, 14)


def test_receipt_total_uses_the_grand_total(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"], date_order="dmy")
    fields = {field.name: field for field in outcome.fields}
    assert fields[FieldName.AMOUNT].normalized == "206.99"
    assert fields[FieldName.CURRENCY].normalized == "GBP"


def test_duplicate_import_is_reported_and_not_stored_twice(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    first = library.import_file(sample_paths["receipt.pdf"])
    second = library.import_file(sample_paths["receipt.pdf"])
    assert second.duplicate is True
    assert second.document.id == first.document.id
    assert len(library.list_documents()) == 1
    assert len(list(library.settings.blob_dir.iterdir())) == 1


def test_blob_on_disk_is_encrypted(library: Library, sample_paths: dict[str, Path]) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"])
    blob = library.settings.blob_dir / f"{outcome.document.sha256}.hbf"
    assert blob.is_file()
    raw = blob.read_bytes()
    assert b"NORTHWIND HARDWARE" not in raw
    assert b"%PDF" not in raw
    assert library.store.get(outcome.document.sha256) == sample_paths["receipt.pdf"].read_bytes()


def test_database_does_not_store_original_bytes(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    library.import_file(sample_paths["receipt.pdf"])
    db_bytes = library.settings.db_path.read_bytes()
    assert b"NORTHWIND HARDWARE LTD" in db_bytes  # extracted text is intentionally indexed
    assert b"%PDF-1.4" not in db_bytes


def test_unsafe_pdf_is_rejected_before_storage(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    malicious = (
        sample_paths["receipt.pdf"]
        .read_bytes()
        .replace(b"%%EOF", b"/JavaScript (app.alert(1)) %%EOF")
    )
    with pytest.raises(UnsafeContent):
        library.import_bytes(malicious, "evil.pdf")
    assert library.list_documents() == []


def test_text_search_returns_page_citation(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    hits = library.search("cordless")
    assert hits
    hit = hits[0]
    assert hit.page == 1
    assert "drill" in hit.snippet.lower()
    detail = library.get_document(hit.doc_id)
    assert detail.pages[0].text


def test_structured_search_by_serial(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    hits = library.search(serial="nwcd-4417-xz")
    assert len(hits) == 1
    assert hits[0].matched_field == "serial"


def test_structured_search_by_amount_range(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    hits = library.search(min_amount="100", max_amount="300")
    assert len(hits) == 1
    assert "206.99" in hits[0].snippet
    assert library.search(min_amount="500") == []


def test_structured_search_by_vendor_and_type(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    import_samples(library, sample_paths)
    assert len(library.search(vendor="northwind")) == 2
    assert len(library.search(doc_type="subscription")) == 1


def test_deadline_filter_uses_normalized_dates(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    import_samples(library, sample_paths)
    hits = library.search(deadline_before="2027-12-31")
    assert hits
    assert all(hit.matched_field in {"renewal_date", "cancellation_deadline"} for hit in hits)


def test_correction_keeps_provenance_and_updates_reminder(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    field = next(f for f in outcome.fields if f.name is FieldName.WARRANTY_END)
    corrected = library.correct_field(
        field.id, "2028-04-30", reason="certificate states April", actor="tester"
    )
    assert corrected.value == "2028-04-30"
    assert corrected.normalized == "2028-04-30"
    assert corrected.original_value == "2028-03-14"
    assert corrected.version == 2
    assert corrected.status is FieldStatus.CONFIRMED

    entries = library.history(field.id)
    assert [entry.action for entry in entries] == ["extracted", "corrected"]
    assert entries[1].reason == "certificate states April"
    assert entries[1].actor == "tester"

    reminder = library.list_reminders()[0]
    assert reminder.status is ReminderStatus.SUGGESTED
    assert reminder.due_date == date(2028, 4, 16)


def test_correction_requires_a_reason_and_valid_date(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    field = next(f for f in outcome.fields if f.name is FieldName.WARRANTY_END)
    with pytest.raises(ValidationError):
        library.correct_field(field.id, "2028-04-30", reason="  ")
    with pytest.raises(ValidationError):
        library.correct_field(field.id, "next spring", reason="vague")
    assert library.get_field(field.id).value == "2028-03-14"


def test_rejected_field_blocks_reminder_confirmation(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    field = next(f for f in outcome.fields if f.name is FieldName.WARRANTY_END)
    library.reject_field(field.id, reason="wrong document", actor="tester")
    with pytest.raises(ValidationError):
        library.confirm_reminder(outcome.reminders[0].id, actor="tester")


def test_reminder_confirmation_gate_and_due_list(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["subscription.pdf"], date_order="dmy")
    assert {r.status for r in outcome.reminders} == {ReminderStatus.SUGGESTED}
    assert library.due_reminders(on=date(2030, 1, 1)) == []

    reminder = outcome.reminders[0]
    confirmed = library.confirm_reminder(reminder.id, actor="tester")
    assert confirmed.status is ReminderStatus.CONFIRMED
    assert confirmed.confirmed_by == "tester"
    assert confirmed.confirmed_at is not None

    due = library.due_reminders(on=date(2030, 1, 1))
    assert reminder.id in {item.id for item in due}
    assert library.due_reminders(on=date(2020, 1, 1)) == []


def test_dismissed_reminder_cannot_be_confirmed(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["subscription.pdf"], date_order="dmy")
    reminder = outcome.reminders[0]
    library.dismiss_reminder(reminder.id, reason="no longer needed", actor="tester")
    with pytest.raises(ValidationError):
        library.confirm_reminder(reminder.id, actor="tester")


def test_reminders_never_require_an_uncited_field(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["subscription.pdf"], date_order="dmy")
    field_ids = {field.id for field in outcome.fields}
    for reminder in outcome.reminders:
        assert reminder.field_id in field_ids
        assert reminder.citation.page == 1
        assert reminder.citation.char_start < reminder.citation.char_end


def test_export_is_encrypted_and_round_trips(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"], date_order="dmy")
    path = library.export_document(outcome.document.id, passphrase="correct horse battery staple")
    assert path.suffix == ".hfe"
    sealed = path.read_bytes()
    assert b"NORTHWIND" not in sealed

    plaintext = crypto.open_with_passphrase("correct horse battery staple", sealed)
    with zipfile.ZipFile(__import__("io").BytesIO(plaintext)) as archive:
        names = archive.namelist()
        assert "metadata.json" in names
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["document"]["sha256"] == outcome.document.sha256
        original = archive.read(next(name for name in names if name.startswith("original/")))
        assert original == sample_paths["receipt.pdf"].read_bytes()


def test_export_without_passphrase_is_plain_zip(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"])
    path = library.export_document(outcome.document.id, passphrase=None)
    assert path.suffix == ".zip"
    with zipfile.ZipFile(path) as archive:
        assert "metadata.json" in archive.namelist()


def test_export_requires_a_document(library: Library) -> None:
    with pytest.raises(NotFound):
        library.export_document("doc-missing", passphrase="x")


def test_deletion_removes_every_derived_artifact(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["warranty.pdf"], date_order="dmy")
    doc_id = outcome.document.id
    sha = outcome.document.sha256
    field = next(f for f in outcome.fields if f.name is FieldName.WARRANTY_END)
    library.correct_field(field.id, "2028-04-30", reason="test", actor="tester")
    library.confirm_reminder(outcome.reminders[0].id, actor="tester")
    library.export_document(doc_id, passphrase="passphrase")

    report = library.delete_document(doc_id, actor="tester")
    assert report.verified is True
    assert report.remaining == []
    assert not (library.settings.blob_dir / f"{sha}.hbf").exists()
    assert library.store.leftover_files() == []
    assert library.list_documents() == []
    assert library.search("cordless") == []
    assert library.search("northwind") == []
    assert library.list_reminders() == []
    assert list(library.settings.export_dir.glob(f"{doc_id}-*")) == []

    with pytest.raises(NotFound):
        library.get_document(doc_id)


def test_deletion_verifies_only_its_own_index_rows(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    import_samples(library, sample_paths)
    receipt = next(d for d in library.list_documents() if d.filename == "receipt.pdf")

    report = library.delete_document(receipt.id, actor="tester")

    assert report.verified is True
    assert report.remaining == []
    # The remaining warranty mentions the same vendor, so a word-level probe
    # would have reported the index as dirty.
    assert [hit.filename for hit in library.search("northwind")] == ["warranty.pdf"]


def test_deletion_is_recorded_without_content(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"], date_order="dmy")
    library.delete_document(outcome.document.id, actor="tester")
    entries = library.deletion_log()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["doc_id"] == outcome.document.id
    assert entry["sha256"] == outcome.document.sha256
    assert entry["actor"] == "tester"
    serialized = json.dumps(entry)
    assert "NORTHWIND" not in serialized
    assert "receipt.pdf" not in serialized


def test_deleting_missing_document_raises(library: Library) -> None:
    with pytest.raises(NotFound):
        library.delete_document("doc-missing")


def test_verify_integrity_detects_tampered_blob(
    library: Library, sample_paths: dict[str, Path]
) -> None:
    outcome = library.import_file(sample_paths["receipt.pdf"])
    report = library.verify_integrity()
    assert report.verified is True

    blob = library.settings.blob_dir / f"{outcome.document.sha256}.hbf"
    data = bytearray(blob.read_bytes())
    data[-1] ^= 0xFF
    blob.write_bytes(bytes(data))

    broken = library.verify_integrity()
    assert broken.verified is False
    assert broken.problems


def test_image_without_ocr_is_stored_with_a_warning(settings: Settings, tmp_path: Path) -> None:
    library = Library(settings, ocr=NullOcr())
    outcome = library.import_bytes(fixtures.png_bytes(), "scan.png")
    assert outcome.document.page_count == 1
    assert outcome.pages[0].source is TextSource.NONE
    assert outcome.pages[0].text == ""
    assert any("OCR" in warning for warning in outcome.warnings)
    assert library.store.exists(outcome.document.sha256)


def test_multi_page_pdf_keeps_page_numbers(library: Library) -> None:
    outcome = library.import_bytes(fixtures.multi_page_pdf(), "two-pages.pdf")
    detail = library.get_document(outcome.document.id)
    assert [page.number for page in detail.pages] == [1, 2]
    assert "SALES RECEIPT" in detail.pages[0].text
    assert "LIMITED WARRANTY" in detail.pages[1].text
    assert all(1 <= field.citation.page <= 2 for field in detail.fields)


def test_stats_and_ledger_are_reported(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    stats = library.stats()
    assert stats["documents"] == 3
    assert stats["pages"] == 3
    assert stats["reminders"] >= 3
    ledger = library.ledger()
    assert ledger
    assert {entry["provider"] for entry in ledger} == {"fake"}
    assert all(entry["estimated_cost"] in {"0", "0.000000", "0E-8"} for entry in ledger)


def test_list_documents_is_newest_first(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    documents = library.list_documents()
    assert len(documents) == 3
    assert [document.imported_at for document in documents] == sorted(
        (document.imported_at for document in documents), reverse=True
    )


def test_search_limit_is_respected(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    assert len(library.search("northwind", limit=1)) == 1


def test_empty_search_returns_documents(library: Library, sample_paths: dict[str, Path]) -> None:
    import_samples(library, sample_paths)
    assert len(library.search()) == 3


def test_reminder_lead_always_precedes_the_deadline() -> None:
    from homefile.parsers import reminder_due, reminder_kind_for

    deadline = date(2030, 6, 1)
    for name in (FieldName.WARRANTY_END, FieldName.RENEWAL_DATE, FieldName.CANCELLATION_DEADLINE):
        kind = reminder_kind_for(name)
        assert kind is not None
        assert reminder_due(kind, deadline) < deadline
    assert reminder_kind_for(FieldName.VENDOR) is None


def test_unknown_document_type_is_not_fabricated(library: Library) -> None:
    outcome = library.import_bytes(fixtures.blank_pdf(), "blank.pdf")
    assert outcome.document.doc_type == "unknown"
    assert outcome.fields == []
    assert outcome.reminders == []
