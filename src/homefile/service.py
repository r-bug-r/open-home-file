"""Library service: the single entry point for every user workflow.

The CLI and the local web UI both call this module; no business rule lives in
either interface. Every write is transactional, every extracted value keeps its
citation, and every destructive action is verified afterwards.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import crypto, db, fixtures, parsers
from . import inspect as file_inspect
from .classify import classify_text
from .config import Settings
from .errors import (
    DeletionError,
    HomeFileError,
    IntegrityError,
    NotFound,
    ProviderError,
    ValidationError,
)
from .extract import OcrEngine, extract_pages
from .models import (
    Citation,
    DeletionReport,
    DocType,
    Document,
    ExtractedField,
    FieldName,
    FieldStatus,
    HistoryEntry,
    Page,
    Reminder,
    ReminderStatus,
    TextSource,
)
from .providers import (
    CompletionRequest,
    ModelProvider,
    ProviderGuard,
    build_provider,
    validate_extraction_payload,
)
from .store import BlobStore

MODEL_PROMPT = (
    "Extract household document fields as JSON with keys doc_type and fields. "
    "Every field must include a verbatim quote copied from the document. "
    "Allowed field names: vendor, amount, currency, purchase_date, serial, "
    "warranty_end, renewal_date, cancellation_deadline, contract_end, account. "
    "Never invent values. Return JSON only."
)
MODEL_TEXT_LIMIT = 6000
MODEL_CONFIDENCE_CEILING = 0.6

_REMINDER_SELECT = (
    "SELECT r.*, COALESCE(NULLIF(d.title, ''), d.filename, '') AS doc_label"
    " FROM reminders r LEFT JOIN documents d ON d.id = r.doc_id"
)


@dataclass(slots=True)
class ImportRecord:
    """One row of the import audit trail, as shown in the UI."""

    id: str
    filename: str
    status: str
    error: str | None
    imported_at: datetime
    doc_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "error": self.error,
            "imported_at": self.imported_at.isoformat(),
            "doc_id": self.doc_id,
        }


@dataclass(slots=True)
class ImportOutcome:
    document: Document
    fields: list[ExtractedField]
    reminders: list[Reminder]
    warnings: list[str] = field(default_factory=list)
    duplicate: bool = False
    pages: list[Page] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "document": self.document.to_json(),
            "fields": [f.to_json() for f in self.fields],
            "reminders": [r.to_json() for r in self.reminders],
            "warnings": self.warnings,
            "duplicate": self.duplicate,
            "pages": [
                {"page": p.number, "source": str(p.source), "chars": len(p.text)}
                for p in self.pages
            ],
        }


@dataclass(slots=True)
class DocumentDetail:
    document: Document
    pages: list[Page]
    fields: list[ExtractedField]
    reminders: list[Reminder]

    def to_json(self) -> dict[str, Any]:
        return {
            "document": self.document.to_json(),
            "pages": [
                {
                    "page": p.number,
                    "source": str(p.source),
                    "text": p.text,
                    "width": p.width,
                    "height": p.height,
                }
                for p in self.pages
            ],
            "fields": [f.to_json() for f in self.fields],
            "reminders": [r.to_json() for r in self.reminders],
        }


@dataclass(frozen=True, slots=True)
class SearchHit:
    doc_id: str
    filename: str
    doc_type: str
    page: int
    snippet: str
    matched_field: str | None = None
    field_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "doc_type": self.doc_type,
            "page": self.page,
            "snippet": self.snippet,
            "matched_field": self.matched_field,
            "field_id": self.field_id,
        }


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    documents: int
    blobs: int
    problems: list[str]
    verified: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "blobs": self.blobs,
            "problems": self.problems,
            "verified": self.verified,
        }


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _row_to_document(row: Any) -> Document:
    keys = row.keys()
    warnings: list[str] = []
    raw_warnings = row["warnings"] if "warnings" in keys else "[]"
    if raw_warnings:
        try:
            parsed = json.loads(raw_warnings)
        except (TypeError, ValueError):
            parsed = []
        if isinstance(parsed, list):
            warnings = [str(item) for item in parsed]
    return Document(
        id=row["id"],
        sha256=row["sha256"],
        filename=row["filename"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        doc_type=DocType(row["doc_type"]),
        doc_type_confidence=row["doc_type_confidence"],
        imported_at=datetime.fromisoformat(row["imported_at"]),
        title=row["title"],
        processed_by=row["processed_by"] if "processed_by" in keys else "",
        warnings=warnings,
    )


def _row_to_field(row: Any) -> ExtractedField:
    return ExtractedField(
        id=row["id"],
        doc_id=row["doc_id"],
        name=FieldName(row["name"]),
        value=row["value"],
        normalized=row["normalized"],
        citation=Citation(
            page=row["page_no"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            x0=row["x0"],
            y0=row["y0"],
            x1=row["x1"],
            y1=row["y1"],
        ),
        confidence=row["confidence"],
        source=row["source"],
        status=FieldStatus(row["status"]),
        original_value=row["original_value"],
        version=row["version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_reminder(row: Any) -> Reminder:
    keys = row.keys()
    return Reminder(
        id=row["id"],
        doc_id=row["doc_id"],
        field_id=row["field_id"],
        kind=row["kind"],
        due_date=date.fromisoformat(row["due_date"]),
        status=ReminderStatus(row["status"]),
        confidence=row["confidence"],
        citation=Citation(page=row["page_no"], char_start=0, char_end=0),
        note=row["note"],
        created_at=datetime.fromisoformat(row["created_at"]),
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]) if row["confirmed_at"] else None,
        confirmed_by=row["confirmed_by"],
        doc_label=row["doc_label"] if "doc_label" in keys else "",
    )


class Library:
    """Local document library. All state lives under ``settings.data_dir``."""

    def __init__(
        self,
        settings: Settings,
        ocr: OcrEngine | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db.init_db(settings.db_path)
        self.store = BlobStore(settings)
        self._ocr = ocr
        self._provider = provider
        self._provider_error: str | None = None

    # ------------------------------------------------------------------ model
    def provider(self) -> ModelProvider | None:
        if self._provider is not None:
            return self._provider
        try:
            self._provider = build_provider(self.settings)
        except HomeFileError as exc:
            self._provider_error = str(exc)
            return None
        return self._provider

    # --------------------------------------------------------------- importing
    def import_file(
        self,
        path: Path,
        *,
        actor: str = "local-user",
        date_order: parsers.DateOrder = "dmy",
        use_model: bool = True,
    ) -> ImportOutcome:
        source = Path(path)
        if not source.is_file():
            raise ValidationError(f"{source} is not a readable file")
        data = source.read_bytes()
        return self.import_bytes(
            data, source.name, actor=actor, date_order=date_order, use_model=use_model
        )

    def import_bytes(
        self,
        data: bytes,
        filename: str,
        *,
        actor: str = "local-user",
        date_order: parsers.DateOrder = "dmy",
        use_model: bool = True,
    ) -> ImportOutcome:
        inspection = file_inspect.inspect_bytes(data, self.settings)
        safe_name = file_inspect.safe_filename(filename)
        import_id = f"imp-{uuid.uuid4().hex[:12]}"

        existing = self._find_by_hash(inspection.sha256)
        if existing is not None:
            self._record_import(
                import_id, inspection.sha256, safe_name, existing.id, "duplicate", None
            )
            detail = self.get_document(existing.id)
            return ImportOutcome(
                document=existing,
                fields=detail.fields,
                reminders=detail.reminders,
                warnings=["identical content was already imported; showing the existing record"],
                duplicate=True,
                pages=detail.pages,
            )

        try:
            extracted = extract_pages(data, inspection.media_type, self.settings, self._ocr)
            if not extracted.pages:
                raise ValidationError("no pages could be extracted from this file")
            self.store.put(data, inspection.sha256)
        except HomeFileError:
            self._record_import(
                import_id, inspection.sha256, safe_name, None, "failed", "validation"
            )
            raise
        except Exception as exc:
            self._record_import(
                import_id, inspection.sha256, safe_name, None, "failed", type(exc).__name__
            )
            raise

        combined = "\n".join(page.text for page in extracted.pages)
        classification = classify_text(combined)
        title = _title_from(extracted.pages, safe_name)
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        document = Document(
            id=doc_id,
            sha256=inspection.sha256,
            filename=safe_name,
            media_type=inspection.media_type,
            size_bytes=inspection.size_bytes,
            page_count=len(extracted.pages),
            doc_type=classification.doc_type,
            doc_type_confidence=classification.confidence,
            imported_at=_now(),
            title=title,
        )

        candidates = parsers.extract_candidates(extracted.pages, date_order)
        warnings = list(extracted.warnings)
        processed_by = ""
        if use_model:
            candidates, model_warnings, processed_by = self._model_candidates(
                extracted.pages, candidates, date_order
            )
            warnings.extend(model_warnings)
        if self._provider_error:
            warnings.append(f"model provider unavailable: {self._provider_error}")
        document.processed_by = processed_by

        fields: list[ExtractedField] = []
        reminders: list[Reminder] = []
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "INSERT INTO documents(id, sha256, filename, media_type, size_bytes, page_count,"
                " doc_type, doc_type_confidence, imported_at, title, processed_by, warnings)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document.id,
                    document.sha256,
                    document.filename,
                    document.media_type,
                    document.size_bytes,
                    document.page_count,
                    str(document.doc_type),
                    document.doc_type_confidence,
                    _iso(document.imported_at),
                    document.title,
                    document.processed_by,
                    json.dumps(warnings),
                ),
            )
            for page in extracted.pages:
                conn.execute(
                    "INSERT INTO pages(doc_id, page_no, text, text_source, width, height)"
                    " VALUES(?,?,?,?,?,?)",
                    (doc_id, page.number, page.text, str(page.source), page.width, page.height),
                )
            now = _now()
            for candidate in candidates:
                if not _citation_valid(candidate.citation, extracted.pages):
                    warnings.append(
                        f"rejected {candidate.name}: citation does not point into the page text"
                    )
                    continue
                field_id = f"fld-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    "INSERT INTO fields(id, doc_id, name, value, normalized, page_no, char_start,"
                    " char_end, x0, y0, x1, y1, confidence, source, status, original_value,"
                    " version, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        field_id,
                        doc_id,
                        str(candidate.name),
                        candidate.value,
                        candidate.normalized,
                        candidate.citation.page,
                        candidate.citation.char_start,
                        candidate.citation.char_end,
                        candidate.citation.x0,
                        candidate.citation.y0,
                        candidate.citation.x1,
                        candidate.citation.y1,
                        candidate.confidence,
                        candidate.source,
                        str(FieldStatus.EXTRACTED),
                        candidate.value,
                        1,
                        _iso(now),
                        _iso(now),
                    ),
                )
                conn.execute(
                    "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (
                        field_id,
                        "extracted",
                        None,
                        candidate.value,
                        candidate.source,
                        "extractor",
                        _iso(now),
                    ),
                )
                fields.append(
                    ExtractedField(
                        id=field_id,
                        doc_id=doc_id,
                        name=candidate.name,
                        value=candidate.value,
                        normalized=candidate.normalized,
                        citation=candidate.citation,
                        confidence=candidate.confidence,
                        source=candidate.source,
                        status=FieldStatus.EXTRACTED,
                        original_value=candidate.value,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            for field_value in fields:
                kind = parsers.reminder_kind_for(field_value.name)
                if kind is None or field_value.normalized is None:
                    continue
                try:
                    deadline = date.fromisoformat(field_value.normalized)
                except ValueError:
                    continue
                reminder = Reminder(
                    id=f"rem-{uuid.uuid4().hex[:12]}",
                    doc_id=doc_id,
                    field_id=field_value.id,
                    kind=kind,
                    due_date=parsers.reminder_due(kind, deadline),
                    status=ReminderStatus.SUGGESTED,
                    confidence=field_value.confidence,
                    citation=field_value.citation,
                    note=f"{kind.replace('_', ' ')} deadline {deadline.isoformat()}",
                    created_at=now,
                )
                conn.execute(
                    "INSERT INTO reminders(id, doc_id, field_id, kind, due_date, status, confidence,"
                    " page_no, note, created_at, confirmed_at, confirmed_by)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                    (
                        reminder.id,
                        doc_id,
                        reminder.field_id,
                        kind,
                        reminder.due_date.isoformat(),
                        str(reminder.status),
                        reminder.confidence,
                        field_value.citation.page,
                        reminder.note,
                        _iso(now),
                    ),
                )
                reminders.append(reminder)
            document.warnings = list(warnings)
            conn.execute(
                "UPDATE documents SET warnings = ? WHERE id = ?",
                (json.dumps(document.warnings), doc_id),
            )
            self._record_import(
                import_id, inspection.sha256, safe_name, doc_id, "imported", None, conn=conn
            )

        return ImportOutcome(
            document=document,
            fields=fields,
            reminders=reminders,
            warnings=warnings,
            pages=extracted.pages,
        )

    def _record_import(
        self,
        import_id: str,
        sha256: str,
        filename: str,
        doc_id: str | None,
        status: str,
        error: str | None,
        conn: Any | None = None,
    ) -> None:
        row = (import_id, sha256, filename, _iso(_now()), doc_id, status, error)
        sql = (
            "INSERT INTO imports(id, sha256, filename, imported_at, doc_id, status, error)"
            " VALUES(?,?,?,?,?,?,?)"
        )
        if conn is not None:
            conn.execute(sql, row)
            return
        with db.session(self.settings.db_path) as own:
            own.execute(sql, row)

    def _model_candidates(
        self,
        pages: list[Page],
        existing: list[parsers.Candidate],
        date_order: parsers.DateOrder,
    ) -> tuple[list[parsers.Candidate], list[str], str]:
        """Add model suggestions only where deterministic parsing found nothing.

        A suggestion is accepted only when its quote appears verbatim in the
        cited page, so the citation validator - not the model - decides truth.
        The third element names the provider that actually saw the text, or
        ``""`` when no request was made or it failed.
        """
        provider = self.provider()
        if provider is None:
            return existing, [], ""
        text = "\n".join(page.text for page in pages)[:MODEL_TEXT_LIMIT]
        if not text.strip():
            return existing, [], ""
        guard = ProviderGuard(self.settings, provider, workflow="extract")
        request = CompletionRequest(
            prompt=f"{MODEL_PROMPT}\n---DOCUMENT---\n{text}",
            system=MODEL_PROMPT,
            max_output_tokens=600,
        )
        try:
            response = guard.complete(request)
            payload = validate_extraction_payload(response.text)
        except ProviderError as exc:
            return existing, [f"model extraction skipped: {exc}"], ""

        known = {candidate.name for candidate in existing}
        added: list[parsers.Candidate] = []
        warnings: list[str] = []
        dropped = int(payload.get("dropped", 0))
        if dropped:
            warnings.append(
                f"model returned {dropped} unusable field(s); they were discarded, not coerced"
            )
        for item in payload["fields"]:
            try:
                name = FieldName(item["name"])
            except ValueError:
                warnings.append(f"model field {item['name']!r} is not a supported field; ignored")
                continue
            if name in known:
                continue
            located = _locate_quote(pages, item["quote"])
            if located is None:
                warnings.append(f"model field {name} rejected: quote was not found in the document")
                continue
            page, start, end = located
            value = item["value"]
            normalized = _normalize_value(name, value, date_order)
            added.append(
                parsers.Candidate(
                    name=name,
                    value=value,
                    normalized=normalized,
                    citation=Citation(page=page, char_start=start, char_end=end),
                    confidence=min(MODEL_CONFIDENCE_CEILING, float(item["confidence"])),
                    source=f"model:{response.provider}",
                )
            )
            known.add(name)
        return existing + added, warnings, response.provider if provider.is_remote else ""

    # --------------------------------------------------------------- read side
    def _find_by_hash(self, sha256: str) -> Document | None:
        with db.session(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(self) -> list[Document]:
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY imported_at DESC").fetchall()
        return [_row_to_document(row) for row in rows]

    def recent_imports(self, limit: int = 8) -> list[ImportRecord]:
        """Return the newest import attempts, newest first.

        Failed and duplicate attempts are included: the home page shows what
        happened to each chosen file instead of only a count.
        """
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM imports ORDER BY imported_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 50)),),
            ).fetchall()
        return [
            ImportRecord(
                id=row["id"],
                filename=row["filename"],
                status=row["status"],
                error=row["error"],
                imported_at=datetime.fromisoformat(row["imported_at"]),
                doc_id=row["doc_id"],
            )
            for row in rows
        ]

    def import_samples(self) -> list[ImportOutcome]:
        """Import the three synthetic fixtures for a safe first run.

        The bytes are generated in memory and go through the normal import
        path, so samples exercise the same validation, encryption, and
        citation checks as a user file.
        """
        outcomes: list[ImportOutcome] = []
        for name, payload in (
            ("sample-receipt.pdf", fixtures.receipt_pdf()),
            ("sample-warranty.pdf", fixtures.warranty_pdf()),
            ("sample-subscription.pdf", fixtures.subscription_pdf()),
        ):
            outcomes.append(self.import_bytes(payload, name, actor="local-user"))
        return outcomes

    def get_document(self, doc_id: str) -> DocumentDetail:
        with db.session(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if row is None:
                raise NotFound(f"document {doc_id} does not exist")
            page_rows = conn.execute(
                "SELECT page_no, text, text_source, width, height FROM pages"
                " WHERE doc_id = ? ORDER BY page_no",
                (doc_id,),
            ).fetchall()
            field_rows = conn.execute(
                "SELECT * FROM fields WHERE doc_id = ? ORDER BY name, confidence DESC", (doc_id,)
            ).fetchall()
            reminder_rows = conn.execute(
                f"{_REMINDER_SELECT} WHERE r.doc_id = ? ORDER BY r.due_date", (doc_id,)
            ).fetchall()
        return DocumentDetail(
            document=_row_to_document(row),
            pages=[
                Page(
                    number=page["page_no"],
                    text=page["text"],
                    source=TextSource(page["text_source"]),
                    width=page["width"],
                    height=page["height"],
                )
                for page in page_rows
            ],
            fields=[_row_to_field(item) for item in field_rows],
            reminders=[_row_to_reminder(item) for item in reminder_rows],
        )

    def get_field(self, field_id: str) -> ExtractedField:
        with db.session(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM fields WHERE id = ?", (field_id,)).fetchone()
        if row is None:
            raise NotFound(f"field {field_id} does not exist")
        return _row_to_field(row)

    def history(self, field_id: str) -> list[HistoryEntry]:
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM field_history WHERE field_id = ? ORDER BY id", (field_id,)
            ).fetchall()
        return [
            HistoryEntry(
                id=row["id"],
                field_id=row["field_id"],
                action=row["action"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                reason=row["reason"],
                actor=row["actor"],
                at=datetime.fromisoformat(row["at"]),
            )
            for row in rows
        ]

    def search(
        self,
        query: str | None = None,
        *,
        vendor: str | None = None,
        serial: str | None = None,
        doc_type: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
        deadline_before: str | None = None,
        deadline_after: str | None = None,
        limit: int = 50,
    ) -> list[SearchHit]:
        """Search text and structured fields; every hit names a source page.

        Filters combine with AND, and a text query is intersected with them:
        passing both means "pages matching the text in documents matching the
        filters". Without a text query, each matching field is its own hit.
        """
        hits: list[SearchHit] = []
        # One hit per document page: a text match and a structured match on the
        # same page describe the same source, so the first one wins.
        seen: set[tuple[str, int]] = set()
        with db.session(self.settings.db_path) as conn:
            # Filters combine with AND at the document level: a document must
            # have a field satisfying every supplied constraint, but those
            # fields may be different rows. Values stay bound parameters.
            groups: list[tuple[str, list[Any]]] = []
            if vendor:
                groups.append(("f.name = 'vendor' AND f.value LIKE ?", [f"%{vendor}%"]))
            if serial:
                groups.append(
                    ("f.name = 'serial' AND f.normalized LIKE ?", [f"%{serial.upper()}%"])
                )
            if min_amount:
                groups.append(
                    ("f.name = 'amount' AND CAST(f.normalized AS REAL) >= ?", [float(min_amount)])
                )
            if max_amount:
                groups.append(
                    ("f.name = 'amount' AND CAST(f.normalized AS REAL) <= ?", [float(max_amount)])
                )
            if deadline_before:
                groups.append(
                    (f"f.name IN ({DEADLINE_FIELDS}) AND f.normalized <= ?", [deadline_before])
                )
            if deadline_after:
                groups.append(
                    (f"f.name IN ({DEADLINE_FIELDS}) AND f.normalized >= ?", [deadline_after])
                )
            # Each group becomes its own correlated subquery over ``fields``;
            # the text is assembled only from these literals.
            doc_filter = " AND ".join(
                f"d.id IN (SELECT doc_id FROM fields f WHERE {condition})"  # noqa: S608
                for condition, _ in groups
            )
            group_params = [value for _, values in groups for value in values]
            has_query = bool(query and query.strip())
            if has_query:
                match = _fts_query(query or "")
                if match:
                    # A text query combined with filters means both: the page
                    # must match the text and its document must match every
                    # field constraint.
                    sql = (
                        "SELECT p.doc_id, p.page_no, d.filename, d.doc_type,"
                        " snippet(pages_fts, 0, '[', ']', ' … ', 12) AS snip"
                        " FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid"
                        " JOIN documents d ON d.id = p.doc_id"
                        " WHERE pages_fts MATCH ?"
                    )
                    text_params: list[Any] = [match]
                    if doc_filter:
                        sql += f" AND {doc_filter}"
                        text_params.extend(group_params)
                    if doc_type:
                        sql += " AND d.doc_type = ?"
                        text_params.append(doc_type)
                    sql += " ORDER BY rank LIMIT ?"
                    text_params.append(limit)
                    try:
                        rows = conn.execute(sql, text_params).fetchall()
                    except Exception as exc:
                        raise ValidationError(f"search query could not be parsed: {exc}") from exc
                    for row in rows:
                        key = (row["doc_id"], row["page_no"])
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append(
                            SearchHit(
                                doc_id=row["doc_id"],
                                filename=row["filename"],
                                doc_type=row["doc_type"],
                                page=row["page_no"],
                                snippet=row["snip"],
                            )
                        )
            if not has_query and groups:
                # No text query: one hit per matching document, citing the field
                # from the first supplied filter so the link lands on a citation.
                primary, primary_params = groups[0]
                sql = (
                    "SELECT d.id AS doc_id, d.filename, d.doc_type,"  # noqa: S608
                    " (SELECT f.page_no FROM fields f"
                    f"  WHERE f.doc_id = d.id AND {primary} LIMIT 1) AS page_no,"
                    " (SELECT f.name FROM fields f"
                    f"  WHERE f.doc_id = d.id AND {primary} LIMIT 1) AS name,"
                    " (SELECT f.value FROM fields f"
                    f"  WHERE f.doc_id = d.id AND {primary} LIMIT 1) AS value,"
                    " (SELECT f.id FROM fields f"
                    f"  WHERE f.doc_id = d.id AND {primary} LIMIT 1) AS field_id"
                    " FROM documents d"
                )
                field_params: list[Any] = [
                    *primary_params,
                    *primary_params,
                    *primary_params,
                    *primary_params,
                ]
                if doc_filter:
                    sql += f" WHERE {doc_filter}"
                    field_params.extend(group_params)
                if doc_type:
                    sql += " AND d.doc_type = ?"
                    field_params.append(doc_type)
                sql += " ORDER BY d.imported_at DESC LIMIT ?"
                field_params.append(limit)
                rows = conn.execute(sql, field_params).fetchall()
                for row in rows:
                    key = (row["doc_id"], row["page_no"])
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append(
                        SearchHit(
                            doc_id=row["doc_id"],
                            filename=row["filename"],
                            doc_type=row["doc_type"],
                            page=row["page_no"],
                            snippet=f"{row['name']}: {row['value']}",
                            matched_field=row["name"],
                            field_id=row["field_id"],
                        )
                    )
            if not seen and not has_query and not groups:
                # Browsing with no text query and no field constraint lists
                # documents by their first page, optionally by document type.
                sql = (
                    "SELECT d.id AS doc_id, d.filename, d.doc_type,"
                    " COALESCE((SELECT p.page_no FROM pages p WHERE p.doc_id = d.id"
                    "  ORDER BY p.page_no LIMIT 1), 1) AS page_no,"
                    " COALESCE((SELECT p.text FROM pages p WHERE p.doc_id = d.id"
                    "  ORDER BY p.page_no LIMIT 1), '') AS text"
                    " FROM documents d"
                )
                browse_params: list[Any] = []
                if doc_type:
                    sql += " WHERE d.doc_type = ?"
                    browse_params.append(doc_type)
                sql += " ORDER BY d.imported_at DESC LIMIT ?"
                browse_params.append(limit)
                rows = conn.execute(sql, browse_params).fetchall()
                for row in rows:
                    text = " ".join(str(row["text"]).split())
                    seen.add((row["doc_id"], row["page_no"]))
                    hits.append(
                        SearchHit(
                            doc_id=row["doc_id"],
                            filename=row["filename"],
                            doc_type=row["doc_type"],
                            page=row["page_no"],
                            snippet=text[:160],
                        )
                    )
        return hits[:limit]

    # ---------------------------------------------------------------- mutation
    def correct_field(
        self,
        field_id: str,
        value: str,
        *,
        reason: str,
        actor: str = "local-user",
        date_order: parsers.DateOrder = "dmy",
    ) -> ExtractedField:
        if not reason.strip():
            raise ValidationError("a correction requires a reason")
        current = self.get_field(field_id)
        normalized = _normalize_value(current.name, value, date_order)
        if (
            current.name
            in {
                FieldName.PURCHASE_DATE,
                FieldName.WARRANTY_END,
                FieldName.RENEWAL_DATE,
                FieldName.CANCELLATION_DEADLINE,
                FieldName.CONTRACT_END,
            }
            and normalized is None
        ):
            raise ValidationError(f"{current.name} must be a date; could not parse {value!r}")
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE fields SET value = ?, normalized = ?, status = ?, version = version + 1,"
                " updated_at = ? WHERE id = ?",
                (value.strip(), normalized, str(FieldStatus.CONFIRMED), _iso(now), field_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    field_id,
                    "corrected",
                    current.value,
                    value.strip(),
                    reason.strip(),
                    actor,
                    _iso(now),
                ),
            )
            if normalized is not None:
                kind = parsers.reminder_kind_for(current.name)
                if kind is not None:
                    try:
                        deadline = date.fromisoformat(normalized)
                    except ValueError:
                        deadline = None
                    if deadline is not None:
                        due = parsers.reminder_due(kind, deadline)
                        conn.execute(
                            "UPDATE reminders SET due_date = ?, confidence = ?,"
                            " note = ? WHERE field_id = ? AND status IN ('suggested','confirmed')",
                            (
                                due.isoformat(),
                                max(current.confidence, 0.99),
                                f"{kind.replace('_', ' ')} deadline {deadline.isoformat()}"
                                " (from corrected field)",
                                field_id,
                            ),
                        )
        return self.get_field(field_id)

    def confirm_field(self, field_id: str, *, actor: str = "local-user") -> ExtractedField:
        current = self.get_field(field_id)
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE fields SET status = ?, updated_at = ? WHERE id = ?",
                (str(FieldStatus.CONFIRMED), _iso(now), field_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    field_id,
                    "confirmed",
                    current.value,
                    current.value,
                    "confirmed as extracted",
                    actor,
                    _iso(now),
                ),
            )
        return self.get_field(field_id)

    def reject_field(
        self, field_id: str, *, reason: str, actor: str = "local-user"
    ) -> ExtractedField:
        if not reason.strip():
            raise ValidationError("a rejection requires a reason")
        current = self.get_field(field_id)
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE fields SET status = ?, updated_at = ? WHERE id = ?",
                (str(FieldStatus.REJECTED), _iso(now), field_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (field_id, "rejected", current.value, None, reason.strip(), actor, _iso(now)),
            )
            conn.execute(
                "UPDATE reminders SET status = ? WHERE field_id = ? AND status = 'suggested'",
                (str(ReminderStatus.DISMISSED), field_id),
            )
        return self.get_field(field_id)

    # --------------------------------------------------------------- reminders
    def list_reminders(self, status: str | None = None) -> list[Reminder]:
        sql = _REMINDER_SELECT
        args: list[Any] = []
        if status:
            sql += " WHERE r.status = ?"
            args.append(status)
        sql += " ORDER BY r.due_date"
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def _get_reminder_row(self, reminder_id: str) -> Any:
        with db.session(self.settings.db_path) as conn:
            row = conn.execute(f"{_REMINDER_SELECT} WHERE r.id = ?", (reminder_id,)).fetchone()
        if row is None:
            raise NotFound(f"reminder {reminder_id} does not exist")
        return row

    def confirm_reminder(self, reminder_id: str, *, actor: str = "local-user") -> Reminder:
        row = self._get_reminder_row(reminder_id)
        if row["status"] == str(ReminderStatus.DISMISSED):
            raise ValidationError("a dismissed reminder cannot be confirmed")
        field_row = self.get_field(row["field_id"])
        if field_row.status is FieldStatus.REJECTED:
            raise ValidationError("the underlying field was rejected; correct it before confirming")
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET status = ?, confirmed_at = ?, confirmed_by = ? WHERE id = ?",
                (str(ReminderStatus.CONFIRMED), _iso(now), actor, reminder_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    row["field_id"],
                    "reminder_confirmed",
                    None,
                    row["due_date"],
                    f"{row['kind']} reminder {reminder_id}",
                    actor,
                    _iso(now),
                ),
            )
        return _row_to_reminder(self._get_reminder_row(reminder_id))

    def dismiss_reminder(
        self, reminder_id: str, *, reason: str, actor: str = "local-user"
    ) -> Reminder:
        row = self._get_reminder_row(reminder_id)
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?",
                (str(ReminderStatus.DISMISSED), reminder_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    row["field_id"],
                    "reminder_dismissed",
                    row["due_date"],
                    None,
                    reason,
                    actor,
                    _iso(now),
                ),
            )
        return _row_to_reminder(self._get_reminder_row(reminder_id))

    def complete_reminder(self, reminder_id: str, *, actor: str = "local-user") -> Reminder:
        row = self._get_reminder_row(reminder_id)
        if row["status"] != str(ReminderStatus.CONFIRMED):
            raise ValidationError("only a confirmed reminder can be marked done")
        now = _now()
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?",
                (str(ReminderStatus.DONE), reminder_id),
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    row["field_id"],
                    "reminder_done",
                    row["due_date"],
                    None,
                    "marked done",
                    actor,
                    _iso(now),
                ),
            )
        return _row_to_reminder(self._get_reminder_row(reminder_id))

    def snooze_reminder(
        self, reminder_id: str, days: int, *, actor: str = "local-user"
    ) -> Reminder:
        if days < 1 or days > 365:
            raise ValidationError("snooze days must be between 1 and 365")
        row = self._get_reminder_row(reminder_id)
        if row["status"] != str(ReminderStatus.CONFIRMED):
            raise ValidationError("only a confirmed reminder can be snoozed")
        due = date.fromisoformat(row["due_date"]) + timedelta(days=days)
        with db.transaction(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE reminders SET due_date = ? WHERE id = ?", (due.isoformat(), reminder_id)
            )
            conn.execute(
                "INSERT INTO field_history(field_id, action, old_value, new_value, reason, actor, at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    row["field_id"],
                    "reminder_snoozed",
                    row["due_date"],
                    due.isoformat(),
                    f"snoozed {days} day(s)",
                    actor,
                    _iso(_now()),
                ),
            )
        return _row_to_reminder(self._get_reminder_row(reminder_id))

    def source_bytes(self, doc_id: str) -> bytes:
        """Return the original bytes exactly as imported."""
        detail = self.get_document(doc_id)
        return self.store.get(detail.document.sha256)

    def due_reminders(self, on: date | None = None) -> list[Reminder]:
        today = (on or _now().date()).isoformat()
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute(
                f"{_REMINDER_SELECT} WHERE r.status = 'confirmed' AND r.due_date <= ?"
                " ORDER BY r.due_date",
                (today,),
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    # ------------------------------------------------------------------ export
    def export_document(self, doc_id: str, passphrase: str | None = None) -> Path:
        detail = self.get_document(doc_id)
        original = self.store.get(detail.document.sha256)
        payload = {
            "format": "open-home-file/export/1",
            "exported_at": _iso(_now()),
            "document": detail.document.to_json(),
            "fields": [item.to_json() for item in detail.fields],
            "reminders": [item.to_json() for item in detail.reminders],
            "pages": [
                {"page": page.number, "source": str(page.source), "text": page.text}
                for page in detail.pages
            ],
            "history": {
                item.id: [
                    {
                        "action": entry.action,
                        "old_value": entry.old_value,
                        "new_value": entry.new_value,
                        "reason": entry.reason,
                        "actor": entry.actor,
                        "at": _iso(entry.at),
                    }
                    for entry in self.history(item.id)
                ]
                for item in detail.fields
            },
            "original": {
                "filename": detail.document.filename,
                "sha256": detail.document.sha256,
                "media_type": detail.document.media_type,
            },
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata.json", json.dumps(payload, indent=2, sort_keys=True))
            archive.writestr(f"original/{detail.document.filename}", original)
        bundle = buffer.getvalue()
        self.settings.export_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        if passphrase:
            target = self.settings.export_dir / f"{doc_id}-{stamp}.hfe"
            target.write_bytes(crypto.seal_with_passphrase(passphrase, bundle))
        else:
            target = self.settings.export_dir / f"{doc_id}-{stamp}.zip"
            target.write_bytes(bundle)
        return target

    def export_library(self, passphrase: str | None = None) -> Path:
        """Export every document, its metadata, reminders, and original bytes.

        The archive contains ``metadata.json`` (documents, fields, reminders,
        page text) and one decrypted original per distinct content hash. It is
        a portable backup, not an encrypted-at-rest copy, unless a passphrase
        is supplied.
        """
        documents = self.list_documents()
        payload_documents: list[dict[str, Any]] = []
        originals: dict[str, tuple[str, bytes]] = {}
        for document in documents:
            detail = self.get_document(document.id)
            payload_documents.append(
                {
                    "document": document.to_json(),
                    "fields": [item.to_json() for item in detail.fields],
                    "reminders": [item.to_json() for item in detail.reminders],
                    "pages": [
                        {"page": page.number, "source": str(page.source), "text": page.text}
                        for page in detail.pages
                    ],
                }
            )
            if document.sha256 not in originals:
                originals[document.sha256] = (
                    document.filename,
                    self.store.get(document.sha256),
                )
        payload = {
            "format": "open-home-file/library-export/1",
            "exported_at": _iso(_now()),
            "counts": {
                "documents": len(payload_documents),
                "originals": len(originals),
            },
            "documents": payload_documents,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata.json", json.dumps(payload, indent=2, sort_keys=True))
            for sha256, (filename, data) in originals.items():
                archive.writestr(f"originals/{sha256[:16]}-{filename}", data)
        bundle = buffer.getvalue()
        self.settings.export_dir.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        if passphrase:
            target = self.settings.export_dir / f"library-{stamp}.hfe"
            target.write_bytes(crypto.seal_with_passphrase(passphrase, bundle))
        else:
            target = self.settings.export_dir / f"library-{stamp}.zip"
            target.write_bytes(bundle)
        return target

    @staticmethod
    def read_export(path: Path, passphrase: str | None = None) -> dict[str, Any]:
        blob = Path(path).read_bytes()
        if blob.startswith(crypto.EXPORT_MAGIC):
            if not passphrase:
                raise ValidationError("this export is encrypted; provide the passphrase")
            bundle = crypto.open_with_passphrase(passphrase, blob)
        else:
            bundle = blob
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            names = archive.namelist()
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            originals = {
                name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in names
                if name.startswith(("original/", "originals/"))
            }
        return {"files": names, "metadata": metadata, "original_hashes": originals}

    # ------------------------------------------------------------------ delete
    def delete_document(self, doc_id: str, *, actor: str = "local-user") -> DeletionReport:
        detail = self.get_document(doc_id)
        sha256 = detail.document.sha256
        removed: list[str] = []
        with db.transaction(self.settings.db_path) as conn:
            field_ids = [
                row["field_id"]
                for row in conn.execute(
                    "SELECT id AS field_id FROM fields WHERE doc_id = ?", (doc_id,)
                ).fetchall()
            ]
            page_ids = [
                row["page_id"]
                for row in conn.execute(
                    "SELECT id AS page_id FROM pages WHERE doc_id = ?", (doc_id,)
                ).fetchall()
            ]
            for field_id in field_ids:
                conn.execute("DELETE FROM field_history WHERE field_id = ?", (field_id,))
            conn.execute("DELETE FROM reminders WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM fields WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.execute("DELETE FROM imports WHERE doc_id = ?", (doc_id,))
            removed.extend(
                [
                    "documents",
                    "pages",
                    "pages_fts",
                    "fields",
                    "field_history",
                    "reminders",
                    "imports",
                ]
            )
        if self.store.delete(sha256):
            removed.append("original blob")
        for export in self.settings.export_dir.glob(f"{doc_id}-*"):
            if export.is_file():
                export.unlink()
                removed.append(f"export {export.name}")

        remaining: list[str] = []
        with db.session(self.settings.db_path) as conn:
            checks = {
                "documents": conn.execute(
                    "SELECT COUNT(*) AS n FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()["n"],
                "pages": conn.execute(
                    "SELECT COUNT(*) AS n FROM pages WHERE doc_id = ?", (doc_id,)
                ).fetchone()["n"],
                "fields": conn.execute(
                    "SELECT COUNT(*) AS n FROM fields WHERE doc_id = ?", (doc_id,)
                ).fetchone()["n"],
                "reminders": conn.execute(
                    "SELECT COUNT(*) AS n FROM reminders WHERE doc_id = ?", (doc_id,)
                ).fetchone()["n"],
                "field_history": conn.execute(
                    "SELECT COUNT(*) AS n FROM field_history WHERE field_id IN"
                    " (SELECT id FROM fields WHERE doc_id = ?)",
                    (doc_id,),
                ).fetchone()["n"],
            }
            fts_hits = 0
            if page_ids:
                # Check the deleted pages' own index rows. Matching a word
                # globally would flag unrelated documents that share vocabulary.
                placeholders = ",".join("?" * len(page_ids))
                fts_hits = conn.execute(
                    f"SELECT COUNT(*) AS n FROM pages_fts WHERE rowid IN ({placeholders})",  # noqa: S608
                    page_ids,
                ).fetchone()["n"]
        remaining.extend(name for name, count in checks.items() if count)
        if fts_hits:
            remaining.append("pages_fts")
        if self.store.exists(sha256):
            remaining.append("original blob")
        if any(self.settings.export_dir.glob(f"{doc_id}-*")):
            remaining.append("export files")

        verified = not remaining
        with db.session(self.settings.db_path) as conn:
            conn.execute(
                "INSERT INTO deletion_log(doc_id, sha256, deleted_at, removed, verified,"
                " remaining, actor) VALUES(?,?,?,?,?,?,?)",
                (
                    doc_id,
                    sha256,
                    _iso(_now()),
                    json.dumps(removed),
                    1 if verified else 0,
                    json.dumps(remaining),
                    actor,
                ),
            )
        if not verified:
            raise DeletionError(
                f"deletion of {doc_id} is incomplete; still present: {', '.join(remaining)}"
            )
        return DeletionReport(
            doc_id=doc_id, sha256=sha256, removed=removed, verified=True, remaining=[]
        )

    def delete_all(self, *, actor: str = "local-user") -> list[DeletionReport]:
        """Delete every document and its derived data, verifying each deletion."""
        reports = [
            self.delete_document(document.id, actor=actor) for document in self.list_documents()
        ]
        for leftover in self.settings.export_dir.glob("*"):
            if leftover.is_file():
                leftover.unlink()
        return reports

    def deletion_log(self) -> list[dict[str, Any]]:
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM deletion_log ORDER BY id").fetchall()
        return [
            {
                "doc_id": row["doc_id"],
                "sha256": row["sha256"],
                "deleted_at": row["deleted_at"],
                "removed": json.loads(row["removed"]),
                "verified": bool(row["verified"]),
                "remaining": json.loads(row["remaining"]),
                "actor": row["actor"],
            }
            for row in rows
        ]

    # --------------------------------------------------------------- integrity
    def verify_integrity(self) -> IntegrityReport:
        problems: list[str] = []
        documents = self.list_documents()
        blobs = self.store.leftover_files()
        known = set()
        for document in documents:
            known.add(f"{document.sha256}.hbf")
            try:
                data = self.store.get(document.sha256)
            except (IntegrityError, HomeFileError) as exc:
                problems.append(f"{document.id}: {exc}")
                continue
            if len(data) != document.size_bytes:
                problems.append(
                    f"{document.id}: stored size {len(data)} differs from recorded {document.size_bytes}"
                )
        for name in blobs:
            if name.endswith(".hbf") and name not in known:
                problems.append(f"orphan blob {name} has no document record")
        return IntegrityReport(
            documents=len(documents), blobs=len(blobs), problems=problems, verified=not problems
        )

    def ledger(self) -> list[dict[str, Any]]:
        with db.session(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM ledger ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with db.session(self.settings.db_path) as conn:
            # Table names come from a fixed literal tuple, never from input.
            counts = {
                table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608
                for table in ("documents", "pages", "fields", "reminders", "ledger", "deletion_log")
            }
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM reminders WHERE status = 'suggested'"
            ).fetchone()["n"]
            spend = conn.execute(
                "SELECT COALESCE(SUM(CAST(estimated_cost AS REAL)), 0) AS total FROM ledger"
            ).fetchone()["total"]
        counts["suggested_reminders"] = pending
        counts["estimated_spend_usd"] = str(Decimal(str(spend)).quantize(Decimal("0.000001")))
        return counts


def _title_from(pages: list[Page], fallback: str) -> str:
    for page in pages:
        for line in page.text.split("\n"):
            cleaned = line.strip()
            if 3 <= len(cleaned) <= 90 and re.search(r"[A-Za-z]", cleaned):
                return cleaned
    return Path(fallback).stem.replace("_", " ").replace("-", " ").strip() or "Untitled document"


def _citation_valid(citation: Citation, pages: list[Page]) -> bool:
    for page in pages:
        if page.number != citation.page:
            continue
        return 0 <= citation.char_start < citation.char_end <= len(page.text)
    return False


def _locate_quote(pages: list[Page], quote: str) -> tuple[int, int, int] | None:
    needle = quote.strip()
    if not needle:
        return None
    for page in pages:
        index = page.text.find(needle)
        if index >= 0:
            return page.number, index, index + len(needle)
        collapsed = re.sub(r"\s+", " ", needle)
        haystack = re.sub(r"\s+", " ", page.text)
        index = haystack.find(collapsed)
        if index >= 0:
            return page.number, 0, min(len(page.text), len(collapsed))
    return None


def _normalize_value(name: FieldName, value: str, date_order: parsers.DateOrder) -> str | None:
    text = value.strip()
    if name in {
        FieldName.PURCHASE_DATE,
        FieldName.WARRANTY_END,
        FieldName.RENEWAL_DATE,
        FieldName.CANCELLATION_DEADLINE,
        FieldName.CONTRACT_END,
    }:
        parsed = parsers.parse_date_at(text, 0, date_order)
        return parsed.value.isoformat() if parsed else None
    if name is FieldName.AMOUNT:
        parsed_amount = parsers.parse_amount(text)
        return f"{parsed_amount[0]:.2f}" if parsed_amount else None
    if name is FieldName.SERIAL:
        return text.upper()
    if name is FieldName.CURRENCY:
        return text.upper() if text.upper() in parsers.CURRENCY_CODES else None
    return text


# Field names whose normalized value is a comparable ISO date.
DEADLINE_FIELDS = "'warranty_end','renewal_date','cancellation_deadline','contract_end'"


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z\u00c0-\u024f]+", query)
    if not tokens:
        return ""
    return " AND ".join(f"{token}*" for token in tokens[:8])


def _fts_probe(pages: list[Page]) -> str:
    words: list[str] = re.findall(r"[A-Za-z]{5,}", " ".join(page.text for page in pages))
    if not words:
        return ""
    words.sort(key=len, reverse=True)
    return words[0].lower()
