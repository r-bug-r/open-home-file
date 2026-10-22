"""Shared HTML rendering helpers.

Everything is rendered on the server with the standard library only: no
template engine, no build step, no external asset. Every value that comes from
a document or the database passes through :func:`esc`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from html import escape
from typing import Any

APP_NAME = "Open Home File"


def esc(value: Any) -> str:
    """Escape any value for HTML text or attribute context."""
    return escape("" if value is None else str(value), quote=True)


def fmt_date(value: date | datetime | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return str(value)


def fmt_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def nav(active: str) -> str:
    items = [
        ("home", "/", "Home"),
        ("documents", "/documents", "Documents"),
        ("reminders", "/reminders", "Reminders"),
        ("settings", "/settings", "Settings"),
    ]

    def link(key: str, href: str, label: str) -> str:
        current = key == active
        classes = "nav-link is-active" if current else "nav-link"
        marker = "" if not current else ' aria-current="page"'
        return f'<li><a class="{classes}"{marker} href="{href}">{esc(label)}</a></li>'

    links = "".join(link(key, href, label) for key, href, label in items)
    return f'<ul class="nav-list">{links}</ul>'


def layout(
    *,
    title: str,
    body: str,
    active: str,
    notice: str | None = None,
    error: str | None = None,
    local_only: bool = True,
    footer_note: str = "",
) -> str:
    banner = ""
    if notice:
        banner += f'<p class="flash flash-ok" role="status">{esc(notice)}</p>'
    if error:
        banner += f'<p class="flash flash-error" role="alert">{esc(error)}</p>'
    mode = (
        '<span class="mode mode-local"><span aria-hidden="true">●</span> Local only</span>'
        if local_only
        else '<span class="mode mode-cloud"><span aria-hidden="true">◆</span> Cloud provider enabled</span>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(APP_NAME)}</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="app-header">
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true">▤</span> {esc(APP_NAME)}</a>
  <nav aria-label="Primary">{nav(active)}</nav>
  <div class="header-status">{mode}</div>
  <div class="status-region">{banner}</div>
</header>
<main id="main" class="app-main">
{body}
</main>
<footer class="app-footer">
  <p>Documents stay in {esc(footer_note or "your local library")}. No telemetry, no uploads.</p>
</footer>
<script src="/static/app.js" defer></script>
</body>
</html>
"""


def page_header(title: str, subtitle: str = "", actions: str = "") -> str:
    sub = f'<p class="page-subtitle">{esc(subtitle)}</p>' if subtitle else ""
    action_block = f'<div class="page-actions">{actions}</div>' if actions else ""
    return f"""<div class="page-header">
  <div>
    <h1>{esc(title)}</h1>
    {sub}
  </div>
  {action_block}
</div>"""


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="badge badge-{esc(tone)}">{esc(text)}</span>'


def status_badge(status: str) -> str:
    tones = {
        "extracted": "warn",
        "confirmed": "ok",
        "rejected": "danger",
        "suggested": "warn",
        "dismissed": "muted",
        "done": "ok",
    }
    return badge(status.replace("_", " "), tones.get(status, "neutral"))


def empty_state(title: str, detail: str, action: str = "") -> str:
    action_block = f'<div class="empty-action">{action}</div>' if action else ""
    return f"""<div class="empty-state">
  <p class="empty-title">{esc(title)}</p>
  <p class="empty-detail">{esc(detail)}</p>
  {action_block}
</div>"""


def table(headers: Iterable[str], rows: Iterable[Sequence[str]], caption: str) -> str:
    """Render a data table.

    ``rows`` holds one sequence of already-escaped cell fragments per row. Each
    cell carries its column name in ``data-label``, which the narrow-screen
    stylesheet uses to stack a row into labelled lines instead of clipping
    columns. Explicit roles keep the table semantics when that CSS changes the
    display type.
    """
    heads = list(headers)
    head = "".join(f'<th scope="col" role="columnheader">{esc(item)}</th>' for item in heads)
    body = "".join(
        '<tr role="row">'
        + "".join(
            f'<td role="cell" data-label="{esc(name)}">{cell}'
            for name, cell in zip(heads, row, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    # The wrapper scrolls horizontally on narrow screens. A scroll container
    # with no focusable descendant is unreachable by keyboard, so it is itself
    # a labelled, focusable region.
    return f"""<div class="table-wrap" role="region" aria-label="{esc(caption)}" tabindex="0">
<table role="table">
  <caption class="visually-hidden">{esc(caption)}</caption>
  <thead role="rowgroup"><tr role="row">{head}</tr></thead>
  <tbody role="rowgroup">{body}</tbody>
</table>
</div>"""


def field_label(name: str) -> str:
    return name.replace("_", " ")


def confidence_meter(confidence: float, threshold: float) -> str:
    percent = max(0, min(100, round(confidence * 100)))
    tone = "ok" if confidence >= threshold else "warn"
    hint = "needs review" if confidence < threshold else "above confirmation threshold"
    # The bar is an SVG so the fill width is a presentation attribute. An
    # inline style attribute would be blocked by the page's style-src CSP.
    return (
        f'<span class="confidence confidence-{tone}">'
        f'<svg class="confidence-track" viewBox="0 0 100 6" preserveAspectRatio="none" '
        f'aria-hidden="true" focusable="false">'
        f'<rect class="confidence-rail" x="0" y="0" width="100" height="6" rx="3"></rect>'
        f'<rect class="confidence-fill" x="0" y="0" width="{percent}" height="6" rx="3"></rect>'
        f"</svg>"
        f'<span class="confidence-text">{percent}% · {esc(hint)}</span></span>'
    )


def highlight(text: str, start: int, end: int) -> str:
    """Escape ``text`` and wrap the cited span in a ``<mark>`` element."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    before = esc(text[:start])
    marked = esc(text[start:end])
    after = esc(text[end:])
    if not marked:
        return before + after
    return f'{before}<mark id="citation-target" class="citation-mark">{marked}</mark>{after}'
