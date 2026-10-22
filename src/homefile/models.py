"""Domain models.

Every extracted value carries a citation (page number plus character span or
bounding box) and a confidence score. Values are drafts until a human confirms
or corrects them; the original value is never overwritten in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class DocType(StrEnum):
    RECEIPT = "receipt"
    WARRANTY = "warranty"
    BILL = "bill"
    CONTRACT = "contract"
    SUBSCRIPTION = "subscription"
    UNKNOWN = "unknown"


class FieldName(StrEnum):
    VENDOR = "vendor"
    AMOUNT = "amount"
    CURRENCY = "currency"
    PURCHASE_DATE = "purchase_date"
    SERIAL = "serial"
    WARRANTY_END = "warranty_end"
    RENEWAL_DATE = "renewal_date"
    CANCELLATION_DEADLINE = "cancellation_deadline"
    CONTRACT_END = "contract_end"
    ACCOUNT = "account"


class FieldStatus(StrEnum):
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReminderStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    DONE = "done"


class TextSource(StrEnum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Citation:
    """Location of a value inside the source document."""

    page: int
    char_start: int
    char_end: int
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "bbox": None
            if self.x0 is None
            else {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Citation:
        bbox = data.get("bbox") or {}
        return cls(
            page=int(data["page"]),
            char_start=int(data.get("char_start", 0)),
            char_end=int(data.get("char_end", 0)),
            x0=bbox.get("x0"),
            y0=bbox.get("y0"),
            x1=bbox.get("x1"),
            y1=bbox.get("y1"),
        )


@dataclass(slots=True)
class Page:
    number: int
    text: str
    source: TextSource
    width: float | None = None
    height: float | None = None

    def excerpt(self, citation: Citation, radius: int = 80) -> str:
        start = max(0, citation.char_start - radius)
        end = min(len(self.text), citation.char_end + radius)
        return self.text[start:end].replace("\n", " ").strip()


@dataclass(slots=True)
class ExtractedField:
    id: str
    doc_id: str
    name: FieldName
    value: str
    normalized: str | None
    citation: Citation
    confidence: float
    source: str
    status: FieldStatus = FieldStatus.EXTRACTED
    original_value: str = ""
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "name": str(self.name),
            "value": self.value,
            "normalized": self.normalized,
            "citation": self.citation.to_json(),
            "confidence": self.confidence,
            "source": self.source,
            "status": str(self.status),
            "original_value": self.original_value,
            "version": self.version,
        }


@dataclass(slots=True)
class Document:
    id: str
    sha256: str
    filename: str
    media_type: str
    size_bytes: int
    page_count: int
    doc_type: DocType
    doc_type_confidence: float
    imported_at: datetime
    title: str = ""
    deleted_at: datetime | None = None
    processed_by: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def stayed_local(self) -> bool:
        """True when no model provider saw this document's text."""
        return not self.processed_by

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "doc_type": str(self.doc_type),
            "doc_type_confidence": self.doc_type_confidence,
            "imported_at": self.imported_at.isoformat(),
            "title": self.title,
            "processed_by": self.processed_by,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class Reminder:
    id: str
    doc_id: str
    field_id: str
    kind: str
    due_date: date
    status: ReminderStatus
    confidence: float
    citation: Citation
    note: str = ""
    created_at: datetime | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    doc_label: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "field_id": self.field_id,
            "kind": self.kind,
            "due_date": self.due_date.isoformat(),
            "status": str(self.status),
            "confidence": self.confidence,
            "doc_label": self.doc_label,
            "citation": self.citation.to_json(),
            "note": self.note,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "confirmed_by": self.confirmed_by,
        }


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    field_id: str
    action: str
    old_value: str | None
    new_value: str | None
    reason: str
    actor: str
    at: datetime


@dataclass(frozen=True, slots=True)
class DeletionReport:
    doc_id: str
    sha256: str
    removed: list[str] = field(default_factory=list)
    verified: bool = False
    remaining: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "sha256": self.sha256,
            "removed": self.removed,
            "verified": self.verified,
            "remaining": self.remaining,
        }
