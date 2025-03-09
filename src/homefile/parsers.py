"""Deterministic parsers for dates, amounts, identifiers, and field candidates.

Everything here is pure and offline: same input, same output, no model. Each
candidate carries a citation into the page text so the UI can show the exact
source and so a reminder can never exist without a source.

Date ambiguity is handled explicitly. ``01/02/2027`` is day-first by default
(``date_order="dmy"``); when the order is ambiguous the candidate's confidence
drops below the confirmation threshold, so a reminder is only a suggestion
until a human confirms it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from .models import Citation, FieldName, Page

DateOrder = Literal["dmy", "mdy"]

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY", "₹": "INR"}
CURRENCY_CODES = {
    "GBP",
    "USD",
    "EUR",
    "JPY",
    "INR",
    "CAD",
    "AUD",
    "NZD",
    "SEK",
    "NOK",
    "DKK",
    "CHF",
}

_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_NUMERIC = re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?![\d/.-])")
_DATE_TEXTUAL = re.compile(
    r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
_DATE_TEXTUAL_US = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)

_AMOUNT = re.compile(
    r"(?:(?P<sym>[£$€¥₹])\s?)?"
    r"(?P<num>\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
    r"(?:\s?(?P<code>GBP|USD|EUR|JPY|INR|CAD|AUD|NZD|SEK|NOK|DKK|CHF))?"
)

_SERIAL = re.compile(
    r"(?:serial(?:\s*(?:no|number|#))?|s/n|sn|imei|asset\s*(?:no|id))"
    r"\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9-]{3,23})\b",
    re.IGNORECASE,
)
_MODEL = re.compile(
    r"model\s*(?:no|number|#)?\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9-]{3,23})\b",
    re.IGNORECASE,
)

_VENDOR_LABEL = re.compile(
    r"^(?:sold\s+by|vendor|merchant|supplier|billed\s+by|retailer|seller|provider)\s*:\s*(?P<value>.+)$",
    re.IGNORECASE,
)
_TOTAL_LABEL = re.compile(
    r"\b(?:grand\s+total|total\s+(?:due|amount|paid|inc(?:luding)?\s+(?:vat|tax))|"
    r"amount|total)\b",
    re.IGNORECASE,
)
_NON_AMOUNT_PREFIX = re.compile(r"[A-Za-z0-9][-./]\s*$")

_DEADLINE_KINDS: tuple[tuple[str, FieldName, tuple[str, ...]], ...] = (
    ("warranty", FieldName.WARRANTY_END, ("warranty", "guarantee")),
    ("renewal", FieldName.RENEWAL_DATE, ("renew", "renews", "renewal")),
    (
        "cancellation",
        FieldName.CANCELLATION_DEADLINE,
        ("cancel", "cancellation", "notice period", "opt out", "opt-out"),
    ),
    ("contract_end", FieldName.CONTRACT_END, ("contract end", "term ends", "expires", "expiry")),
)

_PURCHASE_HINTS = (
    "purchase date",
    "date of purchase",
    "purchased",
    "invoice date",
    "receipt date",
    "date",
)

_METADATA_LABELS = re.compile(
    r"^(?:vat|tax|receipt|invoice|order|account|plan|billing|payment|date|due|"
    r"serial|model|reference|ref|tel|phone|email|e-mail|web|www|iban|sort\s*code|"
    r"page|total|subtotal|amount|qty|quantity)\b",
    re.IGNORECASE,
)

_GENERIC_TITLES = {
    "receipt",
    "invoice",
    "tax invoice",
    "order confirmation",
    "payment receipt",
    "statement",
    "bill",
    "quote",
    "sales receipt",
}


@dataclass(frozen=True, slots=True)
class ParsedDate:
    value: date
    ambiguous: bool


@dataclass(frozen=True, slots=True)
class Candidate:
    name: FieldName
    value: str
    normalized: str | None
    citation: Citation
    confidence: float
    source: str


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _expand_year(raw: str) -> int:
    year = int(raw)
    if len(raw) == 2:
        return 2000 + year if year <= 79 else 1900 + year
    return year


def parse_date_at(text: str, start: int = 0, date_order: DateOrder = "dmy") -> ParsedDate | None:
    """Parse the first date at or after ``start``, returning ambiguity."""
    best: tuple[int, ParsedDate] | None = None

    def consider(pos: int, parsed: ParsedDate) -> None:
        nonlocal best
        if best is None or pos < best[0]:
            best = (pos, parsed)

    for match in _DATE_ISO.finditer(text, start):
        parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            consider(match.start(), ParsedDate(parsed, False))

    for match in _DATE_TEXTUAL.finditer(text, start):
        month = MONTHS[match.group(2).lower().rstrip(".")]
        parsed = _safe_date(int(match.group(3)), month, int(match.group(1)))
        if parsed:
            consider(match.start(), ParsedDate(parsed, False))

    for match in _DATE_TEXTUAL_US.finditer(text, start):
        month = MONTHS[match.group(1).lower().rstrip(".")]
        parsed = _safe_date(int(match.group(3)), month, int(match.group(2)))
        if parsed:
            consider(match.start(), ParsedDate(parsed, False))

    for match in _DATE_NUMERIC.finditer(text, start):
        first, second, year_raw = int(match.group(1)), int(match.group(2)), match.group(3)
        year = _expand_year(year_raw)
        day_first = _safe_date(year, second, first) if first <= 31 and second <= 12 else None
        month_first = _safe_date(year, first, second) if first <= 12 and second <= 31 else None
        chosen: ParsedDate | None = None
        if day_first and month_first and day_first != month_first:
            ambiguous = True
            chosen = ParsedDate(day_first if date_order == "dmy" else month_first, ambiguous)
        elif (day_first and month_first) or day_first:
            chosen = ParsedDate(day_first, False)
        elif month_first:
            chosen = ParsedDate(month_first, False)
        if chosen:
            consider(match.start(), chosen)

    if best is None:
        return None
    return best[1]


def find_dates(text: str, date_order: DateOrder = "dmy") -> list[tuple[int, int, ParsedDate]]:
    found: list[tuple[int, int, ParsedDate]] = []
    position = 0
    while position < len(text):
        parsed = parse_date_at(text, position, date_order)
        if parsed is None:
            break
        match_start = _locate(text, position, parsed)
        if match_start is None:
            break
        end = match_start + _date_span(text, match_start)
        found.append((match_start, end, parsed))
        position = max(end, match_start + 1)
    return found


def _locate(text: str, start: int, parsed: ParsedDate) -> int | None:
    """Find the offset of the date that ``parse_date_at`` selected."""
    for match in _DATE_ISO.finditer(text, start):
        if (
            _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            == parsed.value
        ):
            return match.start()
    for match in _DATE_TEXTUAL.finditer(text, start):
        month = MONTHS[match.group(2).lower().rstrip(".")]
        if _safe_date(int(match.group(3)), month, int(match.group(1))) == parsed.value:
            return match.start()
    for match in _DATE_TEXTUAL_US.finditer(text, start):
        month = MONTHS[match.group(1).lower().rstrip(".")]
        if _safe_date(int(match.group(3)), month, int(match.group(2))) == parsed.value:
            return match.start()
    for match in _DATE_NUMERIC.finditer(text, start):
        first, second = int(match.group(1)), int(match.group(2))
        year = _expand_year(match.group(3))
        if (
            _safe_date(year, second, first) == parsed.value
            or _safe_date(year, first, second) == parsed.value
        ):
            return match.start()
    return None


def _date_span(text: str, start: int) -> int:
    for pattern in (_DATE_ISO, _DATE_TEXTUAL, _DATE_TEXTUAL_US, _DATE_NUMERIC):
        match = pattern.match(text, start)
        if match:
            return match.end() - match.start()
    return 10


def parse_amount(raw: str) -> tuple[Decimal, str | None] | None:
    """Parse a monetary string into (value, ISO currency when known)."""
    match = _AMOUNT.search(raw)
    if match is None:
        return None
    digits = match.group("num")
    if digits is None:
        return None
    if not re.search(r"\d", digits):
        return None
    cleaned = digits.replace(" ", "")
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        head, _, tail = cleaned.rpartition(",")
        cleaned = f"{head.replace(',', '')}.{tail}" if len(tail) == 2 else cleaned.replace(",", "")
    elif has_dot and cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    symbol = match.group("sym")
    code = match.group("code")
    currency = CURRENCY_SYMBOLS.get(symbol or "") or (code.upper() if code else None)
    if currency not in CURRENCY_CODES:
        currency = None
    return value, currency


def iter_lines(text: str) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []
    offset = 0
    for raw in text.split("\n"):
        lines.append((raw, offset))
        offset += len(raw) + 1
    return lines


def _cite(page: Page, start: int, end: int) -> Citation:
    return Citation(page=page.number, char_start=start, char_end=end)


def _line_citation(
    page: Page, line: str, line_start: int, match_start: int, match_end: int
) -> Citation:
    del line
    return _cite(page, line_start + match_start, line_start + match_end)


def find_vendor(page: Page) -> Candidate | None:
    lines = [(line.strip(), start) for line, start in iter_lines(page.text) if line.strip()]
    for line, start in lines:
        match = _VENDOR_LABEL.match(line)
        if match:
            value = match.group("value").strip(" .;:-")
            if value:
                return Candidate(
                    FieldName.VENDOR,
                    value,
                    value,
                    _cite(page, start + match.start("value"), start + match.end("value")),
                    0.92,
                    "label",
                )
    for line, start in lines:
        cleaned = line.strip(" .;:-")
        if not cleaned or cleaned.lower() in _GENERIC_TITLES:
            continue
        if len(cleaned) < 3 or len(cleaned) > 80:
            continue
        if not re.search(r"[A-Za-z]", cleaned):
            continue
        if re.fullmatch(r"[\d\s.,:/#-]+", cleaned):
            continue
        if _METADATA_LABELS.match(cleaned):
            continue
        return Candidate(
            FieldName.VENDOR,
            cleaned,
            cleaned,
            _cite(page, start, start + len(line)),
            0.55,
            "heuristic",
        )
    return None


def find_amount(page: Page) -> list[Candidate]:
    candidates: list[Candidate] = []
    for line, start in iter_lines(page.text):
        stripped = line.strip()
        if not stripped:
            continue
        is_total = bool(_TOTAL_LABEL.search(stripped))
        for match in _AMOUNT.finditer(line):
            parsed = parse_amount(match.group(0))
            if parsed is None:
                continue
            value, currency = parsed
            if value <= 0:
                continue
            if not is_total and currency is None:
                continue
            if _NON_AMOUNT_PREFIX.search(line[: match.start()]):
                continue
            candidates.append(
                Candidate(
                    FieldName.AMOUNT,
                    match.group(0).strip(),
                    f"{value:.2f}",
                    _line_citation(page, line, start, match.start(), match.end()),
                    0.9 if is_total else 0.6,
                    "total-label" if is_total else "number",
                )
            )
            if currency:
                code_span = match.span("code")
                token_span = code_span if code_span[0] >= 0 else match.span("sym")
                candidates.append(
                    Candidate(
                        FieldName.CURRENCY,
                        currency,
                        currency,
                        _line_citation(page, line, start, token_span[0], token_span[1]),
                        0.9,
                        "symbol",
                    )
                )
    return candidates


def find_serial(page: Page) -> Candidate | None:
    """Prefer an explicit serial label; fall back to a model number."""
    for pattern, confidence, method in (
        (_SERIAL, 0.9, "label"),
        (_MODEL, 0.7, "model-label"),
    ):
        match = pattern.search(page.text)
        if match is None:
            continue
        value = match.group("value").strip("-")
        if len(value) < 4 or (value.isdigit() and len(value) < 5):
            continue
        return Candidate(
            FieldName.SERIAL,
            value,
            value.upper(),
            _cite(page, match.start("value"), match.end("value")),
            confidence,
            method,
        )
    return None


def find_purchase_date(page: Page, date_order: DateOrder) -> Candidate | None:
    lines = iter_lines(page.text)
    for hint in _PURCHASE_HINTS:
        for line, start in lines:
            if hint in line.lower():
                parsed = parse_date_at(line, 0, date_order)
                if parsed is None:
                    continue
                offset = _locate(line, 0, parsed)
                if offset is None:
                    continue
                span = _date_span(line, offset)
                confidence = 0.9 if hint != "date" else 0.75
                if parsed.ambiguous:
                    confidence = min(confidence, 0.6)
                return Candidate(
                    FieldName.PURCHASE_DATE,
                    line[offset : offset + span],
                    parsed.value.isoformat(),
                    _line_citation(page, line, start, offset, offset + span),
                    confidence,
                    "label",
                )
    return None


def find_deadlines(page: Page, date_order: DateOrder) -> list[Candidate]:
    """Find dated obligations, one candidate per line and deadline kind."""
    results: list[Candidate] = []
    for line, start in iter_lines(page.text):
        lowered = line.lower()
        for kind, name, keywords in _DEADLINE_KINDS:
            if not any(keyword in lowered for keyword in keywords):
                continue
            parsed = parse_date_at(line, 0, date_order)
            if parsed is None:
                continue
            offset = _locate(line, 0, parsed)
            if offset is None:
                continue
            span = _date_span(line, offset)
            confidence = 0.9 if not parsed.ambiguous else 0.6
            if kind == "contract_end" and name is FieldName.CONTRACT_END and "expir" in lowered:
                confidence = min(confidence, 0.85)
            results.append(
                Candidate(
                    name,
                    line[offset : offset + span],
                    parsed.value.isoformat(),
                    _line_citation(page, line, start, offset, offset + span),
                    confidence,
                    f"deadline:{kind}",
                )
            )
            break
    return results


def derive_warranty_from_term(
    page: Page, purchase: date, date_order: DateOrder
) -> Candidate | None:
    """Compute an end date from an explicit "N year(s) warranty" phrase.

    The citation points at the warranty phrase (not at a date), and the value
    is marked as derived so the UI can label it and require confirmation.
    """
    match = re.search(
        r"(?P<years>\d{1,2})[-\s]?(?:year|yr)s?\s+(?:limited\s+)?(?:warranty|guarantee)",
        page.text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    del date_order
    years = int(match.group("years"))
    if not 1 <= years <= 30:
        return None
    end = (
        date(purchase.year + years, purchase.month, purchase.day)
        if not (purchase.month == 2 and purchase.day == 29)
        else date(purchase.year + years, 2, 28)
    )
    return Candidate(
        FieldName.WARRANTY_END,
        match.group(0),
        end.isoformat(),
        _cite(page, match.start(), match.end()),
        0.5,
        "derived:term",
    )


def extract_candidates(pages: list[Page], date_order: DateOrder = "dmy") -> list[Candidate]:
    """Run every deterministic parser and keep the strongest candidate per field."""
    chosen: dict[FieldName, Candidate] = {}

    def offer(candidate: Candidate) -> None:
        current = chosen.get(candidate.name)
        if current is None or candidate.confidence > current.confidence:
            chosen[candidate.name] = candidate

    for page in pages:
        if not page.text.strip():
            continue
        vendor = find_vendor(page)
        if vendor:
            offer(vendor)
        for amount in find_amount(page):
            offer(amount)
        serial = find_serial(page)
        if serial:
            offer(serial)
        purchase = find_purchase_date(page, date_order)
        if purchase:
            offer(purchase)
        for deadline in find_deadlines(page, date_order):
            offer(deadline)

    purchase = chosen.get(FieldName.PURCHASE_DATE)
    if purchase and purchase.normalized and FieldName.WARRANTY_END not in chosen:
        for page in pages:
            derived = derive_warranty_from_term(
                page, date.fromisoformat(purchase.normalized), date_order
            )
            if derived:
                offer(derived)
                break
    return list(chosen.values())


def reminder_kind_for(name: FieldName) -> str | None:
    return {
        FieldName.WARRANTY_END: "warranty",
        FieldName.RENEWAL_DATE: "renewal",
        FieldName.CANCELLATION_DEADLINE: "cancellation",
        FieldName.CONTRACT_END: "contract_end",
    }.get(name)


def reminder_lead_days(kind: str) -> int:
    return {
        "warranty": 14,
        "renewal": 7,
        "cancellation": 14,
        "contract_end": 30,
    }.get(kind, 7)


def reminder_due(kind: str, deadline: date) -> date:
    """Reminder fires ahead of the deadline, never after it."""
    lead = timedelta(days=reminder_lead_days(kind))
    candidate = deadline - lead
    return candidate if candidate > date.min else deadline
