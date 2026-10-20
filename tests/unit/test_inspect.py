"""Input validation tests: media type, active content, limits, filenames."""

from __future__ import annotations

import pytest

from homefile import fixtures
from homefile.config import Settings
from homefile.errors import FileTooLarge, UnsafeContent, UnsupportedFile
from homefile.inspect import inspect_bytes, safe_filename


def test_pdf_is_accepted(settings: Settings) -> None:
    inspection = inspect_bytes(fixtures.receipt_pdf(), settings)
    assert inspection.media_type == "application/pdf"
    assert inspection.size_bytes > 0
    assert len(inspection.sha256) == 64


def test_png_is_accepted(settings: Settings) -> None:
    inspection = inspect_bytes(fixtures.png_bytes(), settings)
    assert inspection.media_type == "image/png"


def test_unknown_bytes_are_rejected(settings: Settings) -> None:
    with pytest.raises(UnsupportedFile):
        inspect_bytes(b"just some text", settings)


def test_empty_file_is_rejected(settings: Settings) -> None:
    with pytest.raises(UnsupportedFile):
        inspect_bytes(b"", settings)


def test_size_limit_is_enforced(settings: Settings) -> None:
    small = settings.__class__(data_dir=settings.data_dir, max_file_bytes=128)
    with pytest.raises(FileTooLarge):
        inspect_bytes(fixtures.receipt_pdf(), small)


def test_javascript_pdf_is_rejected(settings: Settings) -> None:
    malicious = fixtures.receipt_pdf().replace(b"%%EOF", b"/JavaScript (app.alert(1)) %%EOF")
    with pytest.raises(UnsafeContent):
        inspect_bytes(malicious, settings)


def test_embedded_file_pdf_is_rejected(settings: Settings) -> None:
    malicious = fixtures.receipt_pdf().replace(b"%%EOF", b"/EmbeddedFile %%EOF")
    with pytest.raises(UnsafeContent):
        inspect_bytes(malicious, settings)


def test_page_limit_is_enforced(settings: Settings) -> None:
    two_pages = fixtures.multi_page_pdf()
    limited = settings.__class__(data_dir=settings.data_dir, max_pages=1)
    with pytest.raises(UnsafeContent):
        inspect_bytes(two_pages, limited)


def test_encrypted_pdf_is_rejected(settings: Settings) -> None:
    encrypted = fixtures.receipt_pdf().replace(b"%%EOF", b"/Encrypt 9 0 R %%EOF")
    with pytest.raises(UnsafeContent):
        inspect_bytes(encrypted, settings)


def test_truncated_pdf_is_rejected(settings: Settings) -> None:
    with pytest.raises(UnsupportedFile):
        inspect_bytes(fixtures.receipt_pdf()[:200], settings)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\Rye\\invoice.pdf", "invoice.pdf"),
        ("my receipt (1).pdf", "my receipt (1).pdf"),
        ("..", "document"),
        ("", "document"),
        ("invoice\nname.pdf", "invoicename.pdf"),
        ("a" * 300 + ".pdf", "a" * 200),
    ],
)
def test_safe_filename_strips_paths_and_control_characters(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected
