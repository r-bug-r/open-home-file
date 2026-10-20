"""Synthetic fixture generation.

Builds deterministic, obviously fake household documents as real PDF bytes so
tests and demos never depend on personal data or network access. The text
layer is emitted directly, which keeps citations exact and OCR unnecessary.
"""

from __future__ import annotations

import io
import zlib
from pathlib import Path

RECEIPT_LINES = [
    "NORTHWIND HARDWARE LTD",
    "42 Example Street, Testville",
    "VAT No. GB000000000",
    "",
    "SALES RECEIPT",
    "Receipt No: R-10042",
    "Purchase date: 14 March 2026",
    "",
    "Item                     Qty      Amount",
    "Cordless drill kit         1      129.99",
    "Drill bit set              1       24.50",
    "Extension cable 5m         2       18.00",
    "",
    "Subtotal:                       172.49",
    "VAT (20%):                       34.50",
    "Grand total:                    206.99 GBP",
    "",
    "Paid by card ending 0000",
    "Thank you for your purchase.",
]

WARRANTY_LINES = [
    "NORTHWIND HARDWARE LTD",
    "LIMITED WARRANTY CERTIFICATE",
    "",
    "Product: Cordless drill kit",
    "Model number: NW-CD18",
    "Serial number: NWCD-4417-XZ",
    "Purchase date: 14 March 2026",
    "",
    "Coverage period: 2 years from the purchase date.",
    "Warranty end date: 2028-03-14",
    "",
    "This guarantee covers manufacturing defects only.",
    "Proof of purchase is required for any claim.",
    "Claims must be reported before the warranty end date.",
]

SUBSCRIPTION_LINES = [
    "STREAMBOX MEDIA",
    "SUBSCRIPTION NOTICE",
    "",
    "Account: AC-900123",
    "Plan: Annual HD",
    "Billing period: 1 April 2026 to 31 March 2027",
    "Amount: 89.00 GBP per year",
    "",
    "Your subscription renews on 2027-04-01.",
    "Cancellation deadline: 2027-03-18.",
    "Cancel anytime before the renewal date to avoid charges.",
]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str], font_size: int = 11) -> bytes:
    parts = ["BT", f"/F1 {font_size} Tf", "14 TL", "56 780 Td"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Assemble a minimal, valid PDF with one text layer per page."""
    if not pages:
        raise ValueError("at least one page is required")
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    pages_id_placeholder = 2
    objects.append(b"")  # page tree placeholder
    page_ids: list[int] = []
    for lines in pages:
        stream = _content_stream(lines)
        compressed = zlib.compress(stream, 9)
        content_id = add(
            b"<</Length "
            + str(len(compressed)).encode()
            + b"/Filter/FlateDecode>>\nstream\n"
            + compressed
            + b"\nendstream"
        )
        page_id = add(
            b"<</Type/Page/Parent " + str(pages_id_placeholder).encode() + b" 0 R"
            b"/MediaBox[0 0 595 842]"
            b"/Resources<</Font<</F1 " + str(font_id).encode() + b" 0 R>>>>"
            b"/Contents " + str(content_id).encode() + b" 0 R>>"
        )
        page_ids.append(page_id)

    objects[pages_id_placeholder - 1] = (
        b"<</Type/Pages/Count "
        + str(len(page_ids)).encode()
        + b"/Kids["
        + b" ".join(str(pid).encode() + b" 0 R" for pid in page_ids)
        + b"]>>"
    )
    catalog_id = add(b"<</Type/Catalog/Pages " + str(pages_id_placeholder).encode() + b" 0 R>>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n")
    xref_offset = out.tell()
    out.write(b"xref\n0 " + str(len(objects) + 1).encode() + b"\n")
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        b"trailer\n<</Size "
        + str(len(objects) + 1).encode()
        + b"/Root "
        + str(catalog_id).encode()
        + b" 0 R>>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return out.getvalue()


def receipt_pdf() -> bytes:
    return build_pdf([RECEIPT_LINES])


def warranty_pdf() -> bytes:
    return build_pdf([WARRANTY_LINES])


def subscription_pdf() -> bytes:
    return build_pdf([SUBSCRIPTION_LINES])


def multi_page_pdf() -> bytes:
    """Two pages, so page-scoped citations can be proven distinct."""
    return build_pdf([RECEIPT_LINES, WARRANTY_LINES])


def blank_pdf() -> bytes:
    return build_pdf([[""]])


def png_bytes(width: int = 64, height: int = 64) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([4, 4, width - 4, height - 4], outline="black", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_samples(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "receipt.pdf": receipt_pdf(),
        "warranty.pdf": warranty_pdf(),
        "subscription.pdf": subscription_pdf(),
    }
    written: dict[str, Path] = {}
    for name, data in files.items():
        path = directory / name
        path.write_bytes(data)
        written[name] = path
    return written


if __name__ == "__main__":  # pragma: no cover - developer helper
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/generated")
    for name, path in write_samples(target).items():
        print(f"{name}: {path} ({path.stat().st_size} bytes)")
