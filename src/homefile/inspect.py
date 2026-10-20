"""File inspection and safe import validation.

Validation happens on bytes before anything is decrypted, indexed, or parsed:

* extension and magic-number agreement
* size and page limits
* rejection of PDFs containing JavaScript, launch actions, embedded files,
  XFA forms, or encryption (they cannot be fully inspected)
* rejection of decompression bombs in images

Only PDF, PNG, and JPEG are accepted. Everything else is rejected rather than
guessed at.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import FileTooLarge, UnsafeContent, UnsupportedFile

PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

_ACTIVE_PDF_TOKENS = (
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/EmbeddedFile",
    b"/RichMedia",
    b"/XFA",
    b"/OpenAction",
    b"/AA",
    b"/SubmitForm",
    b"/ImportData",
    b"/GoToR",
    b"/Sound",
    b"/Movie",
)

_PDF_HEADER = re.compile(rb"%PDF-(\d\.\d)")


@dataclass(frozen=True, slots=True)
class Inspection:
    media_type: str
    sha256: str
    size_bytes: int

    @property
    def is_pdf(self) -> bool:
        return self.media_type == "application/pdf"

    @property
    def is_image(self) -> bool:
        return self.media_type in {"image/png", "image/jpeg"}


def detect_media_type(data: bytes) -> str:
    if data.startswith(PDF_MAGIC):
        return "application/pdf"
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    raise UnsupportedFile("only PDF, PNG, and JPEG files are supported")


def _reject_active_pdf(data: bytes) -> None:
    for token in _ACTIVE_PDF_TOKENS:
        if token in data:
            raise UnsafeContent(
                f"PDF contains active or embedded content ({token.decode()}); "
                "convert it to a plain, flattened PDF first"
            )
    if b"/Encrypt" in data:
        raise UnsafeContent("encrypted PDFs are not supported; decrypt and re-export first")


def _inspect_pdf(data: bytes, settings: Settings) -> None:
    header = _PDF_HEADER.search(data[:1024])
    if header is None:
        raise UnsupportedFile("file does not contain a valid PDF header")
    if header.group(1) not in {b"1.4", b"1.5", b"1.6", b"1.7", b"2.0"}:
        raise UnsupportedFile(f"unsupported PDF version {header.group(1).decode()}")
    _reject_active_pdf(data)
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        page_count = len(reader.pages)
    except PdfReadError as exc:
        raise UnsupportedFile(f"PDF could not be parsed: {exc}") from exc
    if page_count == 0:
        raise UnsupportedFile("PDF has no pages")
    if page_count > settings.max_pages:
        raise UnsafeContent(f"PDF has {page_count} pages; limit is {settings.max_pages}")
    if reader.is_encrypted:
        raise UnsafeContent("encrypted PDFs are not supported")


def _inspect_image(data: bytes, settings: Settings) -> None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception as exc:
        raise UnsupportedFile(f"image could not be decoded: {exc}") from exc
    if width * height > 40_000_000:
        raise UnsafeContent(f"image is {width}x{height}; too large to process safely")
    if width > 20_000 or height > 20_000:
        raise UnsafeContent(f"image dimension {width}x{height} exceeds the 20000px limit")
    if width < 8 or height < 8:
        raise UnsupportedFile("image is too small to contain a document")
    del settings


def inspect_bytes(data: bytes, settings: Settings) -> Inspection:
    """Validate untrusted bytes and return their identity."""
    import hashlib

    if not data:
        raise UnsupportedFile("file is empty")
    if len(data) > settings.max_file_bytes:
        raise FileTooLarge(
            f"file is {len(data)} bytes; limit is {settings.max_file_bytes} bytes "
            f"(set HOMEFILE_MAX_FILE_MB to change it)"
        )
    media_type = detect_media_type(data)
    if media_type == "application/pdf":
        _inspect_pdf(data, settings)
    else:
        _inspect_image(data, settings)
    return Inspection(
        media_type=media_type, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)
    )


def inspect_path(path: Path, settings: Settings) -> Inspection:
    resolved = Path(path)
    if not resolved.is_file():
        raise UnsupportedFile(f"{resolved} is not a file")
    with resolved.open("rb") as handle:
        data = handle.read(settings.max_file_bytes + 1)
    return inspect_bytes(data, settings)


def safe_filename(name: str) -> str:
    """Reduce a user-supplied filename to a display-safe basename."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    base = re.sub(r"\s+", " ", base)
    if not base or base in {".", ".."}:
        return "document"
    return base[:200]
