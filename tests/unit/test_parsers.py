"""Deterministic parser tests: dates, amounts, identifiers, deadlines, vendors."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from homefile.models import FieldName, Page, TextSource
from homefile.parsers import (
    find_amount,
    find_deadlines,
    find_purchase_date,
    find_serial,
    find_vendor,
    iter_lines,
    parse_amount,
    parse_date_at,
)


def page(text: str, number: int = 1) -> Page:
    return Page(number=number, text=text, source=TextSource.TEXT_LAYER)


def test_iso_date_parses_without_ambiguity() -> None:
    parsed = parse_date_at("Warranty end date: 2028-03-14", 0)
    assert parsed is not None
    assert parsed.value == date(2028, 3, 14)
    assert parsed.ambiguous is False


@pytest.mark.parametrize(
    ("text", "order", "expected"),
    [
        ("14 March 2026", "dmy", date(2026, 3, 14)),
        ("March 14, 2026", "mdy", date(2026, 3, 14)),
        ("25/03/2026", "dmy", date(2026, 3, 25)),
        ("03/25/2026", "mdy", date(2026, 3, 25)),
    ],
)
def test_date_formats_respect_declared_order(text: str, order: str, expected: date) -> None:
    parsed = parse_date_at(text, 0, order)  # type: ignore[arg-type]
    assert parsed is not None
    assert parsed.value == expected


def test_day_first_default_reads_unambiguous_day_twenty_five() -> None:
    parsed = parse_date_at("Date: 25/03/2026", 0, "dmy")
    assert parsed is not None
    assert parsed.value == date(2026, 3, 25)
    assert parsed.ambiguous is False


def test_ambiguous_numeric_date_is_flagged() -> None:
    parsed = parse_date_at("Date: 03/04/2026", 0, "dmy")
    assert parsed is not None
    assert parsed.value == date(2026, 4, 3)
    assert parsed.ambiguous is True


def test_invalid_calendar_date_is_not_returned() -> None:
    assert parse_date_at("Date: 31/02/2026", 0) is None


@pytest.mark.parametrize(
    ("raw", "value", "currency"),
    [
        ("206.99 GBP", Decimal("206.99"), "GBP"),
        ("£1,299.00", Decimal("1299.00"), "GBP"),
        ("1.299,00 EUR", Decimal("1299.00"), "EUR"),
        ("$42", Decimal("42"), "USD"),
        ("89.00", Decimal("89.00"), None),
    ],
)
def test_amount_formats(raw: str, value: Decimal, currency: str | None) -> None:
    parsed = parse_amount(raw)
    assert parsed is not None
    assert parsed[0] == value
    assert parsed[1] == currency


def test_amount_rejects_non_numeric_text() -> None:
    assert parse_amount("no numbers here") is None


def test_total_label_wins_over_item_lines() -> None:
    text = "\n".join(
        [
            "Item                Amount",
            "Cordless drill       129.99",
            "Drill bit set         24.50",
            "Grand total:         154.49 GBP",
        ]
    )
    candidates = [c for c in find_amount(page(text)) if c.name is FieldName.AMOUNT]
    assert candidates
    best = max(candidates, key=lambda candidate: candidate.confidence)
    assert best.value == "154.49 GBP"
    assert best.confidence >= 0.9


def test_amount_citation_points_at_the_number() -> None:
    text = "Subtotal: 10.00\nGrand total: 206.99 GBP\n"
    candidate = next(c for c in find_amount(page(text)) if c.value == "206.99 GBP")
    start, end = candidate.citation.char_start, candidate.citation.char_end
    assert text[start:end] == "206.99 GBP"


def test_currency_citation_points_at_the_currency_token() -> None:
    text = "Subtotal: 10.00\nGrand total: 206.99 GBP\n"
    candidate = next(c for c in find_amount(page(text)) if c.name is FieldName.CURRENCY)
    start, end = candidate.citation.char_start, candidate.citation.char_end
    assert text[start:end] == "GBP"
    assert candidate.value == "GBP"


def test_currency_symbol_citation_points_at_the_symbol() -> None:
    text = "Total: £12.50\n"
    candidate = next(c for c in find_amount(page(text)) if c.name is FieldName.CURRENCY)
    start, end = candidate.citation.char_start, candidate.citation.char_end
    assert text[start:end] == "£"
    assert candidate.value == "GBP"


def test_serial_label_beats_model_number() -> None:
    text = "Model number: NW-CD18\nSerial number: NWCD-4417-XZ\n"
    candidate = find_serial(page(text))
    assert candidate is not None
    assert candidate.value == "NWCD-4417-XZ"
    assert candidate.normalized == "NWCD-4417-XZ"
    assert candidate.confidence > 0.8


def test_model_number_used_only_without_serial() -> None:
    candidate = find_serial(page("Model number: NW-CD18\n"))
    assert candidate is not None
    assert candidate.value == "NW-CD18"
    assert candidate.confidence < 0.8


def test_serial_requires_a_label() -> None:
    assert find_serial(page("The quick brown fox NWCD-4417-XZ\n")) is None


def test_deadline_keywords_map_to_field_names() -> None:
    text = "\n".join(
        [
            "Warranty end date: 2028-03-14",
            "Your subscription renews on 2027-04-01.",
            "Cancellation deadline: 2027-03-18.",
        ]
    )
    found = {candidate.name: candidate for candidate in find_deadlines(page(text), "dmy")}
    assert set(found) == {
        FieldName.WARRANTY_END,
        FieldName.RENEWAL_DATE,
        FieldName.CANCELLATION_DEADLINE,
    }
    assert found[FieldName.WARRANTY_END].normalized == "2028-03-14"
    assert found[FieldName.RENEWAL_DATE].normalized == "2027-04-01"
    assert found[FieldName.CANCELLATION_DEADLINE].normalized == "2027-03-18"


def test_deadline_without_a_date_is_ignored() -> None:
    assert find_deadlines(page("Warranty covers manufacturing defects.\n"), "dmy") == []


def test_purchase_date_requires_a_hint() -> None:
    assert find_purchase_date(page("Some text 14 March 2026\n"), "dmy") is None
    candidate = find_purchase_date(page("Purchase date: 14 March 2026\n"), "dmy")
    assert candidate is not None
    assert candidate.normalized == "2026-03-14"


def test_vendor_skips_generic_titles() -> None:
    candidate = find_vendor(page("SALES RECEIPT\nNORTHWIND HARDWARE LTD\n42 Example Street\n"))
    assert candidate is not None
    assert candidate.value == "NORTHWIND HARDWARE LTD"


def test_vendor_skips_numeric_lines() -> None:
    assert find_vendor(page("VAT No. GB000000000\n12345 67890\n")) is None


def test_iter_lines_reports_absolute_offsets() -> None:
    text = "first\nsecond\nthird"
    lines = iter_lines(text)
    assert [line for line, _ in lines] == ["first", "second", "third"]
    for line, offset in lines:
        assert text[offset : offset + len(line)] == line
