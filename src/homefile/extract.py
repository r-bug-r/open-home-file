"""Page-preserving text extraction.

PDF: the embedded text layer is preferred because it preserves character
offsets exactly. When a page has no usable text layer, embedded raster images
are passed to the OCR adapter. Image imports are always OCR.

OCR is an injected interface so tests and offline installs never require
Tesseract. When no OCR backend is available the page is recorded with
``TextSource.NONE`` and empty text, and the import reports a warning instead
of inventing content.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings
from .models import Page, TextSource


class OcrEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def ocr_image(self, data: bytes) -> str: ...


class TesseractOcr:
    """Local Tesseract adapter. No network access."""

    name = "tesseract"

    def __init__(self) -> None:
        self._checked: bool | None = None

    def is_available(self) -> bool:
        if self._checked is None:
            try:
                import pytesseract

                pytesseract.get_tesseract_version()
                self._checked = True
            except Exception:
                self._checked = False
        return self._checked

    def ocr_image(self, data: bytes) -> str:
        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            grayscale = image.convert("L")
            return str(pytesseract.image_to_string(grayscale))


class NullOcr:
    name = "none"

    def is_available(self) -> bool:
        return False

    def ocr_image(self, data: bytes) -> str:
        raise RuntimeError("no OCR engine is configured")


@dataclass(slots=True)
class ExtractionResult:
    pages: list[Page] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ocr_used: bool = False

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)


def default_ocr() -> OcrEngine:
    return TesseractOcr()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n")


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def extract_pdf(data: bytes, settings: Settings, ocr: OcrEngine) -> ExtractionResult:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    result = ExtractionResult()
    for index, pdf_page in enumerate(reader.pages, start=1):
        raw = ""
        try:
            raw = pdf_page.extract_text() or ""
        except Exception as exc:
            result.warnings.append(f"page {index}: text layer could not be read ({exc})")
        text = _clean(raw)
        source = TextSource.TEXT_LAYER
        if len(text.strip()) < 20:
            ocr_text = _ocr_page_images(pdf_page, index, ocr, result)
            if ocr_text:
                text = _clean(ocr_text)
                source = TextSource.OCR
                result.ocr_used = True
            elif not text.strip():
                source = TextSource.NONE
                result.warnings.append(
                    f"page {index}: no text layer and OCR unavailable; page is stored without text"
                )
        text, truncated = _truncate(text, settings.max_page_chars)
        if truncated:
            result.warnings.append(
                f"page {index}: text truncated at {settings.max_page_chars} characters"
            )
        width = height = None
        with contextlib.suppress(Exception):
            # Page geometry is cosmetic; a malformed box must not fail the import.
            box = pdf_page.mediabox
            width, height = float(box.width), float(box.height)
        result.pages.append(
            Page(number=index, text=text, source=source, width=width, height=height)
        )
    return result


def _ocr_page_images(pdf_page: object, index: int, ocr: OcrEngine, result: ExtractionResult) -> str:
    if not ocr.is_available():
        return ""
    try:
        images = list(getattr(pdf_page, "images", []) or [])
    except Exception:
        return ""
    if not images:
        return ""
    chunks: list[str] = []
    for image in images:
        try:
            chunks.append(ocr.ocr_image(image.data))
        except Exception as exc:
            result.warnings.append(f"page {index}: embedded image OCR failed ({exc})")
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def extract_image(data: bytes, settings: Settings, ocr: OcrEngine) -> ExtractionResult:
    result = ExtractionResult()
    if not ocr.is_available():
        result.pages.append(Page(number=1, text="", source=TextSource.NONE))
        result.warnings.append(
            "OCR engine unavailable (install pytesseract and Tesseract); image stored without text"
        )
        return result
    try:
        text = ocr.ocr_image(data)
    except Exception as exc:
        result.pages.append(Page(number=1, text="", source=TextSource.NONE))
        result.warnings.append(f"OCR failed: {exc}")
        return result
    text, truncated = _truncate(_clean(text), settings.max_page_chars)
    if truncated:
        result.warnings.append(f"page 1: text truncated at {settings.max_page_chars} characters")
    result.ocr_used = True
    result.pages.append(Page(number=1, text=text, source=TextSource.OCR))
    return result


def extract_pages(
    data: bytes, media_type: str, settings: Settings, ocr: OcrEngine | None = None
) -> ExtractionResult:
    engine = ocr if ocr is not None else default_ocr()
    if media_type == "application/pdf":
        return extract_pdf(data, settings, engine)
    if media_type in {"image/png", "image/jpeg"}:
        return extract_image(data, settings, engine)
    raise ValueError(f"unsupported media type {media_type}")
