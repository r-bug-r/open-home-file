"""Server-rendered pages for the local web UI.

Each function returns a complete HTML document. Nothing here decides business
rules: pages call :class:`homefile.service.Library` and render what it returns.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from ..models import Reminder, ReminderStatus, TextSource
from ..service import DocumentDetail, Library
from .render import (
    badge,
    confidence_meter,
    empty_state,
    esc,
    field_label,
    fmt_bytes,
    fmt_date,
    highlight,
    layout,
    page_header,
    status_badge,
    table,
)

DOC_TYPES = ("receipt", "warranty", "bill", "contract", "subscription", "unknown")

FLASH = {
    "imported": "Document imported. Review each extracted value against its citation.",
    "import-failed": "That file could not be imported.",
    "corrected": "Correction saved. The original value is kept in history.",
    "field-confirmed": "Field confirmed.",
    "field-rejected": "Field rejected and removed from reminders.",
    "reminder-confirmed": "Reminder confirmed.",
    "reminder-dismissed": "Reminder dismissed.",
    "reminder-done": "Reminder marked done.",
    "reminder-snoozed": "Reminder snoozed.",
    "deleted": "Document deleted and removal verified.",
    "delete-all": "Every document and derived record was deleted.",
    "exported": "Export written to your library's exports folder.",
}

DELETE_CONFIRM_PHRASE = "DELETE"


def _flash(code: str | None) -> str | None:
    if not code:
        return None
    if code.startswith("imported-"):
        # ``imported-<new>-<duplicates>-<failures>`` from the import handler.
        parts = code.split("-")
        if len(parts) == 4 and all(part.isdigit() for part in parts[1:]):
            imported, duplicates, failed = (int(part) for part in parts[1:])
            sentences: list[str] = []
            if imported:
                noun = "document" if imported == 1 else "documents"
                sentences.append(f"Imported {imported} {noun}.")
            if duplicates:
                noun = "file was" if duplicates == 1 else "files were"
                sentences.append(f"{duplicates} {noun} already in the library.")
            if failed:
                noun = "file" if failed == 1 else "files"
                sentences.append(f"{failed} {noun} could not be imported.")
            sentences.append("Review each extracted value against its citation.")
            return " ".join(sentences)
    return FLASH.get(code)


def _mode(settings: Any) -> bool:
    return not settings.allow_network and settings.provider == "fake"


def _shell(
    library: Library,
    *,
    title: str,
    body: str,
    active: str,
    flash: str | None = None,
    error: str | None = None,
) -> str:
    settings = library.settings
    return layout(
        title=title,
        body=body,
        active=active,
        notice=_flash(flash),
        error=error,
        local_only=_mode(settings),
        footer_note=str(settings.data_dir),
    )


def _csrf_input(token: str) -> str:
    return f'<input type="hidden" name="csrf" value="{esc(token)}">'


def _field_query(field_id: str | None) -> str:
    return f"?field={quote(field_id)}" if field_id else ""

def _usd(value: Any) -> str:
    """Format a ledger amount with two decimals and no float noise."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return f"${esc(value)}"
    return f"${amount:.2f}"

def _doc_label(document: Any) -> str:
    return str(document.title or document.filename)


# --------------------------------------------------------------------- home


def home_page(library: Library, *, csrf: str, flash: str | None = None, error: str | None = None) -> str:
    settings = library.settings
    documents = library.list_documents()
    stats = library.stats()
    reminders = library.list_reminders()
    today = date.today()
    upcoming = sorted(
        (
            reminder
            for reminder in reminders
            if reminder.status is ReminderStatus.CONFIRMED and reminder.due_date >= today
        ),
        key=lambda item: item.due_date,
    )[:6]
    due_now = [item for item in upcoming if item.due_date <= today + timedelta(days=14)]
    recent = documents[:6]

    metrics = f"""<div class="metric-grid">
  <div class="metric">
    <p class="metric-label">Documents</p>
    <p class="metric-value">{len(documents)}</p>
    <p class="metric-detail">{stats["pages"]} indexed pages</p>
  </div>
  <div class="metric">
    <p class="metric-label">Deadlines due in 14 days</p>
    <p class="metric-value">{len(due_now)}</p>
    <p class="metric-detail">{len(upcoming)} upcoming confirmed</p>
  </div>
  <div class="metric">
    <p class="metric-label">Awaiting your review</p>
    <p class="metric-value">{stats["suggested_reminders"]}</p>
    <p class="metric-detail">suggested reminders</p>
  </div>
  <div class="metric">
    <p class="metric-label">Provider spend</p>
    <p class="metric-value">{_usd(stats["estimated_spend_usd"])}</p>
    <p class="metric-detail">cap {_usd(settings.run_cost_cap_usd)}/run</p>
  </div>
</div>"""

    dropzone = f"""<form class="dropzone" method="post" action="/import" enctype="multipart/form-data"
      data-dropzone data-confirm="Import these files into your local library?">
  {_csrf_input(csrf)}
  <p class="dropzone-title">Drop documents here, or choose files</p>
  <p class="hint">PDF, PNG, or JPEG. Nothing leaves this computer: text extraction and
  classification run locally, and the model adapter is the offline fake provider.</p>
  <label class="field">
    <span class="field-label">Files</span>
    <input type="file" name="files" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" multiple required>
  </label>
  <p class="hint" data-dropzone-status role="status"></p>
  <ul class="dropzone-rules">
    <li>Max {fmt_bytes(settings.max_file_bytes)} per file</li>
    <li>Up to {settings.max_pages} pages</li>
    <li>Date order: day first</li>
  </ul>
  <div class="inline-actions">
    <button class="button button-primary" type="submit">Import locally</button>
    <a class="button button-quiet" href="/settings">Storage and privacy</a>
  </div>
</form>"""

    if upcoming:
        rows = [
            f"""<tr>
  <td><time datetime="{esc(item.due_date.isoformat())}">{fmt_date(item.due_date)}</time></td>
  <td>{esc(field_label(item.kind))}</td>
  <td><a href="/documents/{esc(item.doc_id)}?field={esc(item.field_id)}">{esc(item.note)}</a></td>
  <td>{status_badge(str(item.status))}</td>
</tr>"""
            for item in upcoming
        ]
        reminder_block = table(("Due", "Kind", "Reminder", "Status"), rows, "Upcoming reminders")
    else:
        reminder_block = empty_state(
            "No confirmed reminders yet",
            "Open a document, check a date field against its citation, then confirm the reminder. "
            "Suggested reminders appear in the Reminders list and never fire on their own.",
            '<a class="button" href="/reminders">Review suggested reminders</a>',
        )

    if recent:
        doc_rows = [
            f"""<tr>
  <td><a href="/documents/{esc(document.id)}">{esc(_doc_label(document))}</a>
      <div class="hint">{esc(document.filename)}</div></td>
  <td>{badge(document.doc_type, "neutral")}</td>
  <td class="num">{document.page_count}</td>
  <td class="num">{fmt_bytes(document.size_bytes)}</td>
  <td><time datetime="{esc(document.imported_at.isoformat())}">{fmt_date(document.imported_at)}</time></td>
</tr>"""
            for document in recent
        ]
        doc_block = table(("Document", "Type", "Pages", "Size", "Imported"), doc_rows, "Recent documents")
    else:
        doc_block = empty_state(
            "Your library is empty",
            "Import a receipt or warranty PDF to see extracted fields with page citations. "
            "Synthetic samples are generated by `homefile samples` if you want a safe first run.",
        )

    body = f"""{page_header(
        "Household paperwork, kept locally",
        "Every extracted value links back to the page it came from. Deadlines stay suggestions until you confirm them.",
        '<a class="button" href="/documents">Search documents</a>',
    )}
<div class="notice-strip">
  <strong>Local only.</strong>
  <span>Storage: <span class="mono">{esc(settings.data_dir)}</span></span>
  <span>Provider: <span class="mono">{esc(settings.provider)}</span> (no network)</span>
</div>
{metrics}
<section class="panel" aria-labelledby="import-heading" style="margin-top: var(--space-6)">
  <div class="panel-head">
    <h2 id="import-heading">Import</h2>
    <p class="panel-note">Files are hashed, encrypted at rest, and indexed by page.</p>
  </div>
  {dropzone}
</section>
<div class="split" style="margin-top: var(--space-6)">
  <section class="panel" aria-labelledby="upcoming-heading">
    <div class="panel-head">
      <h2 id="upcoming-heading">Upcoming deadlines</h2>
      <a href="/reminders">All reminders</a>
    </div>
    {reminder_block}
  </section>
  <section class="panel" aria-labelledby="recent-heading">
    <div class="panel-head">
      <h2 id="recent-heading">Recent documents</h2>
      <a href="/documents">All documents</a>
    </div>
    {doc_block}
  </section>
</div>"""
    return _shell(library, title="Home", body=body, active="home", flash=flash, error=error)


# ---------------------------------------------------------------- documents


def documents_page(
    library: Library,
    *,
    csrf: str,
    query: str = "",
    vendor: str = "",
    serial: str = "",
    doc_type: str = "",
    min_amount: str = "",
    max_amount: str = "",
    deadline_before: str = "",
    flash: str | None = None,
    error: str | None = None,
) -> str:
    has_filters = any([query.strip(), vendor, serial, doc_type, min_amount, max_amount, deadline_before])
    hits = library.search(
        query or None,
        vendor=vendor or None,
        serial=serial or None,
        doc_type=doc_type or None,
        min_amount=min_amount or None,
        max_amount=max_amount or None,
        deadline_before=deadline_before or None,
    )
    type_options = "".join(
        f'<option value="{esc(name)}"{" selected" if name == doc_type else ""}>{esc(name)}</option>'
        for name in DOC_TYPES
    )
    form = f"""<form class="filter-bar" method="get" action="/documents" role="search">
  <label class="field">
    <span class="field-label">Text</span>
    <input type="search" name="q" value="{esc(query)}" placeholder="vendor, model, account…" autocomplete="off">
  </label>
  <label class="field">
    <span class="field-label">Vendor</span>
    <input type="text" name="vendor" value="{esc(vendor)}" autocomplete="off">
  </label>
  <label class="field">
    <span class="field-label">Serial</span>
    <input type="text" name="serial" value="{esc(serial)}" autocomplete="off">
  </label>
  <label class="field">
    <span class="field-label">Type</span>
    <select name="type"><option value="">Any</option>{type_options}</select>
  </label>
  <label class="field">
    <span class="field-label">Min amount</span>
    <input type="number" name="min_amount" step="0.01" min="0" value="{esc(min_amount)}">
  </label>
  <label class="field">
    <span class="field-label">Max amount</span>
    <input type="number" name="max_amount" step="0.01" min="0" value="{esc(max_amount)}">
  </label>
  <label class="field">
    <span class="field-label">Deadline before</span>
    <input type="date" name="deadline_before" value="{esc(deadline_before)}">
  </label>
  <div class="inline-actions">
    <button class="button button-primary" type="submit">Search</button>
    <a class="button button-quiet" href="/documents">Reset</a>
  </div>
</form>"""

    if hits:
        rows = [
            f"""<tr>
  <td><a href="/documents/{esc(hit.doc_id)}{_field_query(hit.field_id)}">{esc(hit.filename)}</a>
      <div class="hint mono">page {hit.page}</div></td>
  <td>{esc(hit.doc_type)}</td>
  <td>{badge(hit.matched_field, "muted") if hit.matched_field else badge("text", "neutral")}</td>
  <td>{esc(hit.snippet)}</td>
</tr>"""
            for hit in hits
        ]
        results = table(("Document", "Type", "Matched", "Snippet"), rows, "Search results")
    elif has_filters:
        results = empty_state(
            "No document matches those filters",
            "Try a shorter text query, remove the amount range, or clear the type filter. "
            "Search covers indexed page text and extracted fields.",
            '<a class="button" href="/documents">Clear filters</a>',
        )
    else:
        results = empty_state(
            "Nothing imported yet",
            "Import a PDF, PNG, or JPEG from the home screen. Text and fields are indexed per page, "
            "so search results always point at a source page.",
            '<a class="button button-primary" href="/">Import a document</a>',
        )

    body = f"""{page_header(
        "Documents",
        f"{len(hits)} result(s). Search reads local page text and extracted fields only.",
        '<a class="button" href="/">Import</a>',
    )}
<section class="panel" aria-labelledby="search-heading">
  <div class="panel-head"><h2 id="search-heading">Search</h2>
  <p class="panel-note">Press <kbd>/</kbd> to focus the text field.</p></div>
  {form}
</section>
<section class="panel" aria-labelledby="results-heading" aria-live="polite">
  <h2 id="results-heading" class="visually-hidden">Results</h2>
  {results}
</section>"""
    return _shell(library, title="Documents", body=body, active="documents", flash=flash, error=error)


# ------------------------------------------------------------------- detail


def _page_panels(detail: DocumentDetail, selected: Any) -> str:
    panels = []
    for page in detail.pages:
        text = page.text
        if selected is not None and selected.citation.page == page.number:
            inner = highlight(text, selected.citation.char_start, selected.citation.char_end)
        else:
            inner = esc(text)
        hidden = "" if (selected is None and page.number == 1) or (
            selected is not None and selected.citation.page == page.number
        ) else " hidden"
        if page.source is TextSource.NONE and not text:
            inner = (
                '<p class="hint">This page has no text layer and OCR is not installed, '
                "so there is nothing to quote. The original is still stored and "
                "downloadable.</p>"
            )
            panels.append(
                f'<div data-page-panel="{page.number}"{hidden}>{inner}</div>'
            )
            continue
        panels.append(
            f'<div data-page-panel="{page.number}"{hidden}>'
            f'<pre class="source-text" tabindex="0" aria-label="Page {page.number} text">{inner}</pre>'
            f"</div>"
        )
    return "".join(panels)


def _page_tabs(detail: DocumentDetail, selected: Any) -> str:
    tabs = []
    for page in detail.pages:
        active = (selected.citation.page if selected else 1) == page.number
        tabs.append(
            f'<button type="button" class="page-tab" role="tab" data-page-tab="{page.number}"'
            f' aria-selected="{"true" if active else "false"}">Page {page.number}'
            f' <span class="hint">{esc(page.source)}</span></button>'
        )
    return f'<div class="page-tabs" role="tablist" aria-label="Source pages">{"".join(tabs)}</div>'


def _field_rows(detail: DocumentDetail, selected_id: str | None, threshold: float) -> str:
    rows = []
    for field in detail.fields:
        current = field.id == selected_id
        rows.append(
            f"""<a class="field-row" href="?field={esc(field.id)}"
   data-field-id="{esc(field.id)}"
   data-page="{field.citation.page}"
   data-start="{field.citation.char_start}"
   data-end="{field.citation.char_end}"
   data-name="{esc(field.name)}"
   data-value="{esc(field.value)}"
   data-confidence="{field.confidence}"
   data-quote="{esc(field.value)}"
   aria-current="{"true" if current else "false"}">
  <span class="field-row-top">
    <span class="field-name">{esc(field_label(str(field.name)))}</span>
    {status_badge(str(field.status))}
  </span>
  <span class="field-value">{esc(field.value)}</span>
  <span class="field-quote">page {field.citation.page} · chars {field.citation.char_start}–{field.citation.char_end}</span>
  {confidence_meter(field.confidence, threshold)}
</a>"""
        )
    return "".join(rows)


def _citation_panel(
    detail: DocumentDetail, selected: Any, csrf: str, threshold: float
) -> str:
    document = detail.document
    if selected is None:
        return """<div class="citation-card" data-citation-pane tabindex="-1" aria-labelledby="citation-heading">
  <h2 id="citation-heading">Citation</h2>
  <p class="hint">Select a field to see the exact source text, its page, and the correction form.</p>
</div>"""

    page = next((p for p in detail.pages if p.number == selected.citation.page), None)
    excerpt = page.excerpt(selected.citation) if page else selected.value
    reminder_block = ""
    for reminder in detail.reminders:
        hidden = "" if reminder.field_id == selected.id else " hidden"
        reminder_block += f"""<div class="panel" data-reminder-for="{esc(reminder.field_id)}"{hidden}
     style="margin-top: var(--space-3)">
  <div class="panel-head">
    <strong>{esc(field_label(reminder.kind))} reminder</strong>
    {status_badge(str(reminder.status))}
  </div>
  <dl class="meta">
    <dt>Due</dt><dd>{fmt_date(reminder.due_date)}</dd>
    <dt>Confidence</dt><dd>{round(reminder.confidence * 100)}%</dd>
    <dt>Created</dt><dd>{fmt_date(reminder.created_at)}</dd>
  </dl>
  <div class="inline-actions" style="margin-top: var(--space-3)">
    {_reminder_actions(document.id, reminder, csrf)}
  </div>
</div>"""

    return f"""<div class="citation-card" data-citation-pane tabindex="-1" aria-labelledby="citation-heading">
  <h2 id="citation-heading">Citation</h2>
  <dl class="meta">
    <dt>Field</dt><dd data-citation-field>{esc(field_label(str(selected.name)))}</dd>
    <dt>Value</dt><dd class="mono" data-citation-value>{esc(selected.value)}</dd>
    <dt>Confidence</dt><dd data-citation-confidence>{round(selected.confidence * 100)}%</dd>
    <dt>Source</dt><dd class="mono">{esc(selected.source)}</dd>
    <dt>Page</dt><dd>{selected.citation.page}</dd>
    <dt>Offsets</dt><dd class="mono">{selected.citation.char_start}–{selected.citation.char_end}</dd>
  </dl>
  <p class="field-label">Source excerpt</p>
  <p class="citation-target" data-citation-quote>{esc(excerpt)}</p>
  <p class="hint">The highlighted span on the left is the exact text this value was read from.
  If it is wrong, correct it below; the original stays in history.</p>
  <form method="post" action="/documents/{esc(document.id)}/correct" class="stack"
        data-citation-form
        data-confirm="Save this correction and keep the original value in history?">
    {_csrf_input(csrf)}
    <input type="hidden" name="field_id" value="{esc(selected.id)}">
    <label class="field">
      <span class="field-label">Corrected value</span>
      <input type="text" name="value" value="{esc(selected.value)}" required maxlength="200">
    </label>
    <label class="field">
      <span class="field-label">Reason (required)</span>
      <input type="text" name="reason" required maxlength="200" placeholder="certificate states 30 April 2028">
    </label>
    <div class="inline-actions">
      <button class="button button-primary" type="submit">Save correction</button>
      <button class="button" type="submit" formaction="/documents/{esc(document.id)}/confirm">Confirm as is</button>
      <button class="button button-danger" type="submit" formaction="/documents/{esc(document.id)}/reject">Reject field</button>
    </div>
  </form>
  {reminder_block}
  <p id="citation-live" class="visually-hidden" role="status" aria-live="polite"></p>
</div>"""


def _reminder_actions(doc_id: str, reminder: Reminder, csrf: str) -> str:
    base = f"/documents/{esc(doc_id)}/reminders/{esc(reminder.id)}"
    # Keep the selected field after the redirect so the citation panel does not
    # collapse when a reminder action re-renders the page.
    context = _csrf_input(csrf) + f'<input type="hidden" name="field" value="{esc(reminder.field_id)}">'
    status = reminder.status
    parts: list[str] = []
    if status is ReminderStatus.SUGGESTED:
        parts.append(
            f'<form method="post" action="{base}/confirm">{context}'
            f'<button class="button button-primary button-small" type="submit">Confirm reminder</button></form>'
        )
        parts.append(
            f'<form method="post" action="{base}/dismiss">{context}'
            f'<input type="hidden" name="reason" value="not relevant">'
            f'<button class="button button-small" type="submit">Dismiss</button></form>'
        )
    elif status is ReminderStatus.CONFIRMED:
        parts.append(
            f'<form method="post" action="{base}/done">{context}'
            f'<button class="button button-primary button-small" type="submit">Mark done</button></form>'
        )
        parts.append(
            f'<form method="post" action="{base}/snooze">{context}'
            f'<input type="hidden" name="days" value="7">'
            f'<button class="button button-small" type="submit">Snooze 7 days</button></form>'
        )
        parts.append(
            f'<form method="post" action="{base}/dismiss">{context}'
            f'<input type="hidden" name="reason" value="dismissed by user">'
            f'<button class="button button-small" type="submit">Dismiss</button></form>'
        )
    return "".join(parts)


def document_page(
    library: Library,
    doc_id: str,
    *,
    csrf: str,
    field_id: str | None = None,
    flash: str | None = None,
    error: str | None = None,
) -> str:
    detail = library.get_document(doc_id)
    document = detail.document
    threshold = library.settings.confirm_below
    selected = next((item for item in detail.fields if item.id == field_id), None)
    if selected is None and detail.fields:
        selected = detail.fields[0]

    history_items = []
    for field in detail.fields:
        for entry in library.history(field.id):
            history_items.append((entry.at, field, entry))
    history_items.sort(key=lambda item: item[0], reverse=True)
    history_html = "".join(
        f"""<li>
  <time datetime="{esc(entry.at.isoformat())}">{fmt_date(entry.at)}</time>
  <div class="timeline-body">
    <strong>{esc(field_label(str(field.name)))}</strong>
    {badge(entry.action, "muted")}
    <div>{esc(entry.old_value or "—")} → {esc(entry.new_value or "—")}</div>
    <div class="hint">{esc(entry.actor)}: {esc(entry.reason)}</div>
  </div>
</li>"""
        for entry_at, field, entry in history_items[:40]
    ) or '<li><div class="timeline-body hint">No changes recorded yet.</div></li>'

    unreadable = any(page.source is TextSource.NONE for page in detail.pages)
    no_fields_hint = (
        "This document has no readable text, so there was nothing to match against."
        if unreadable
        else "The text was indexed, but no vendor, amount, date, serial, or deadline pattern matched."
    )
    warnings = ""
    if unreadable:
        warnings = (
            '<p class="flash flash-error" role="alert">No text layer and no OCR engine: '
            "this document has no readable text, so no fields could be extracted. "
            "Install the OCR extra or re-import a text PDF.</p>"
        )

    body = f"""<nav aria-label="Breadcrumb">
  <ol class="breadcrumbs">
    <li><a href="/documents">Documents</a></li>
    <li aria-current="page">{esc(document.filename)}</li>
  </ol>
</nav>
{page_header(
    _doc_label(document),
    f"{document.page_count} page(s) · {fmt_bytes(document.size_bytes)} · imported {fmt_date(document.imported_at)}",
    f'<a class="button" href="/documents/{esc(document.id)}/original">Download original</a>'
    f'<a class="button" href="/documents/{esc(document.id)}/delete">Delete…</a>',
)}
{warnings}
<div class="notice-strip">
  <span>{badge(document.doc_type, "neutral")} type confidence {round(document.doc_type_confidence * 100)}%</span>
  <span class="mono">{esc(document.sha256[:16])}…</span>
  <span>Stored locally; processing used {esc(library.settings.provider)} provider.</span>
</div>
<div class="workspace" data-workspace>
  <section class="source-pane panel" aria-labelledby="source-heading">
    <div class="panel-head">
      <h2 id="source-heading">Source</h2>
      <p class="panel-note">Original bytes are unchanged; text is extracted per page.</p>
    </div>
    {_page_tabs(detail, selected)}
    {_page_panels(detail, selected)}
  </section>
  <section class="fields-pane panel" aria-labelledby="fields-heading">
    <div class="panel-head">
      <h2 id="fields-heading">Extracted fields</h2>
      <p class="panel-note">{len(detail.fields)} value(s)</p>
    </div>
    {_field_rows(detail, selected.id if selected else None, threshold)}
    {"" if detail.fields else empty_state("No fields found", no_fields_hint)}
  </section>
  <section class="citation-pane" aria-label="Citation and correction">
    {_citation_panel(detail, selected, csrf, threshold)}
  </section>
</div>
<section class="panel" aria-labelledby="history-heading" style="margin-top: var(--space-6)">
  <div class="panel-head">
    <h2 id="history-heading">Correction history</h2>
    <p class="panel-note">Every extracted value keeps its original text.</p>
  </div>
  <ol class="timeline">{history_html}</ol>
</section>
<section class="panel" aria-labelledby="export-heading">
  <div class="panel-head"><h2 id="export-heading">Export</h2>
  <p class="panel-note">A zip of the original plus JSON metadata, optionally encrypted with a passphrase.</p></div>
  <form method="post" action="/documents/{esc(document.id)}/export" class="form-row">
    {_csrf_input(csrf)}
    <label class="field">
      <span class="field-label">Passphrase (optional)</span>
      <input type="password" name="passphrase" minlength="8" autocomplete="new-password">
    </label>
    <button class="button" type="submit">Export record</button>
  </form>
</section>"""
    return _shell(library, title=document.filename, body=body, active="documents", flash=flash, error=error)


def delete_page(
    library: Library, doc_id: str, *, csrf: str, flash: str | None = None, error: str | None = None
) -> str:
    detail = library.get_document(doc_id)
    document = detail.document
    body = f"""<nav aria-label="Breadcrumb">
  <ol class="breadcrumbs">
    <li><a href="/documents">Documents</a></li>
    <li><a href="/documents/{esc(document.id)}">{esc(document.filename)}</a></li>
    <li aria-current="page">Delete</li>
  </ol>
</nav>
<div class="danger-zone">
  <h2>Delete {esc(document.filename)}?</h2>
  <p>This cannot be undone. The following will be removed from this library and verified
  afterwards:</p>
  <ul class="delete-list">
    <li>The encrypted original blob ({esc(document.sha256[:16])}…)</li>
    <li>Extracted page text and the full-text search index entries</li>
    <li>{len(detail.fields)} extracted field(s) and their correction history</li>
    <li>{len(detail.reminders)} reminder(s)</li>
    <li>Import records and any export file created from this document</li>
  </ul>
  <p class="hint">There is no cloud copy: this is the only copy in the library.</p>
  <form method="post" action="/documents/{esc(document.id)}/delete" class="stack"
        data-confirm="Delete this document and every derived record?">
    {_csrf_input(csrf)}
    <label class="field">
      <span class="field-label">Type {esc(DELETE_CONFIRM_PHRASE)} to confirm</span>
      <input type="text" name="confirm" required autocomplete="off" pattern="DELETE">
    </label>
    <div class="inline-actions">
      <button class="button button-danger" type="submit">Delete permanently</button>
      <a class="button" href="/documents/{esc(document.id)}">Cancel</a>
    </div>
  </form>
</div>"""
    return _shell(library, title="Delete document", body=body, active="documents", flash=flash, error=error)


# ----------------------------------------------------------------- reminders


def reminders_page(
    library: Library,
    *,
    csrf: str,
    status: str = "",
    flash: str | None = None,
    error: str | None = None,
) -> str:
    allowed = {"", "suggested", "confirmed", "dismissed", "done"}
    chosen = status if status in allowed else ""
    reminders = library.list_reminders(chosen or None)
    titles = {
        "": "All reminders",
        "suggested": "Suggested — needs your confirmation",
        "confirmed": "Confirmed",
        "dismissed": "Dismissed",
        "done": "Completed",
    }
    tabs = "".join(
        f'<a class="page-tab" role="tab" aria-selected="{"true" if key == chosen else "false"}"'
        f' href="/reminders{"" if not key else "?status=" + key}">{esc(label)}</a>'
        for key, label in (
            ("", "All"),
            ("suggested", "Suggested"),
            ("confirmed", "Confirmed"),
            ("dismissed", "Dismissed"),
            ("done", "Done"),
        )
    )
    if reminders:
        rows = []
        for item in reminders:
            rows.append(
                f"""<tr>
  <td><time datetime="{esc(item.due_date.isoformat())}">{fmt_date(item.due_date)}</time></td>
  <td>{esc(field_label(item.kind))}</td>
  <td>{status_badge(str(item.status))}</td>
  <td>{round(item.confidence * 100)}%</td>
  <td><a href="/documents/{esc(item.doc_id)}?field={esc(item.field_id)}">Open citation</a>
      <div class="hint">{esc(item.note)}</div></td>
  <td><div class="inline-actions">{_reminder_actions(item.doc_id, item, csrf)}</div></td>
</tr>"""
            )
        listing = table(("Due", "Kind", "Status", "Confidence", "Source", "Actions"), rows, titles[chosen])
    else:
        listing = empty_state(
            "No reminders in this view",
            "Reminders are created from warranty, renewal, and cancellation dates. "
            "A suggestion only becomes active after you confirm it.",
            '<a class="button" href="/documents">Find a document</a>',
        )

    body = f"""{page_header(
        "Reminders",
        "Suggestions never fire on their own. Confirm one to make it active; every reminder keeps its source citation.",
    )}
<div class="page-tabs" role="tablist" aria-label="Reminder status">{tabs}</div>
<section class="panel" aria-labelledby="reminders-heading" aria-live="polite">
  <h2 id="reminders-heading" class="visually-hidden">{esc(titles[chosen])}</h2>
  {listing}
</section>"""
    return _shell(library, title="Reminders", body=body, active="reminders", flash=flash, error=error)


# ------------------------------------------------------------------ settings


def settings_page(
    library: Library, *, csrf: str, flash: str | None = None, error: str | None = None
) -> str:
    settings = library.settings
    report = library.verify_integrity()
    stats = library.stats()
    provider = library.provider()
    provider_name = provider.name if provider else "unavailable"
    mode_label = "Local only" if _mode(settings) else "Cloud provider enabled"
    integrity = (
        badge("verified", "ok")
        if report.verified
        else badge("problems found", "danger")
    )
    problems = ""
    if report.problems:
        problems = '<ul class="delete-list">' + "".join(
            f"<li>{esc(problem)}</li>" for problem in report.problems
        ) + "</ul>"

    body = f"""{page_header(
        "Settings",
        "What this install stores, where it stores it, and what leaves the machine.",
    )}
<section class="panel" aria-labelledby="storage-heading">
  <div class="panel-head"><h2 id="storage-heading">Storage</h2>{integrity}</div>
  <dl class="meta">
    <dt>Library</dt><dd class="mono">{esc(settings.data_dir)}</dd>
    <dt>Database</dt><dd class="mono">{esc(settings.db_path)}</dd>
    <dt>Encrypted blobs</dt><dd class="mono">{esc(settings.blob_dir)}</dd>
    <dt>Exports</dt><dd class="mono">{esc(settings.export_dir)}</dd>
    <dt>Documents</dt><dd>{stats["documents"]} · {stats["pages"]} pages · {stats["fields"]} fields</dd>
    <dt>Deletions verified</dt><dd>{stats["deletion_log"]}</dd>
  </dl>
  {problems}
</section>
<section class="panel" aria-labelledby="processing-heading">
  <div class="panel-head"><h2 id="processing-heading">Processing mode</h2>
  {badge(mode_label, "ok" if _mode(settings) else "danger")}</div>
  <dl class="meta">
    <dt>Provider</dt><dd class="mono">{esc(settings.provider)} → {esc(provider_name)}</dd>
    <dt>Network access</dt><dd>{'disabled' if not settings.allow_network else 'enabled'}</dd>
    <dt>Per-run request cap</dt><dd>{settings.run_request_cap}</dd>
    <dt>Per-run token cap</dt><dd>{settings.run_token_cap}</dd>
    <dt>Per-run cost cap</dt><dd class="mono">{_usd(settings.run_cost_cap_usd)}</dd>
    <dt>Daily cost cap</dt><dd class="mono">{_usd(settings.daily_cost_cap_usd)}</dd>
    <dt>Estimated spend</dt><dd class="mono">{_usd(stats["estimated_spend_usd"])}</dd>
  </dl>
  <p class="hint">Change these with HOMEFILE_* environment variables before starting the server.
  A zero cost cap refuses every paid call.</p>
</section>
<section class="panel" aria-labelledby="retention-heading">
  <div class="panel-head"><h2 id="retention-heading">Retained data</h2></div>
  <ul class="delete-list">
    <li>Encrypted original files (AES-256-GCM, key at <span class="mono">{esc(settings.key_path)}</span>)</li>
    <li>Extracted page text and a local full-text index (plaintext, local database only)</li>
    <li>Extracted fields, citations, confidence, correction history, reminders</li>
    <li>Provider ledger rows: provider, model, tokens, estimated cost, outcome</li>
    <li>Deletion log: document id, hash, timestamp, what was removed, actor</li>
  </ul>
  <p class="hint">No telemetry, no analytics, no upload. Deleting a document removes all of the
  above for that document and verifies removal.</p>
</section>
<div class="danger-zone">
  <h2>Delete everything</h2>
  <p>Deletes every document, page, field, reminder, export, and encrypted blob in this library.
  Provider ledger and deletion-log rows are kept as an audit trail of what happened.</p>
  <form method="post" action="/settings/delete-all" class="stack"
        data-confirm="Delete every document and derived record in this library?">
    {_csrf_input(csrf)}
    <label class="field">
      <span class="field-label">Type {esc(DELETE_CONFIRM_PHRASE)} to confirm</span>
      <input type="text" name="confirm" required autocomplete="off" pattern="DELETE">
    </label>
    <div class="inline-actions">
      <button class="button button-danger" type="submit">Delete all documents</button>
    </div>
  </form>
</div>"""
    return _shell(library, title="Settings", body=body, active="settings", flash=flash, error=error)


# -------------------------------------------------------------------- errors


def error_page(library: Library, *, title: str, message: str, status: int) -> str:
    body = f"""{page_header(title, message)}
<div class="inline-actions">
  <a class="button button-primary" href="/">Back to home</a>
  <a class="button" href="/documents">Documents</a>
</div>"""
    return _shell(library, title=title, body=body, active="home", error=None)


def quote_path(segment: str) -> str:
    return quote(segment, safe="")
