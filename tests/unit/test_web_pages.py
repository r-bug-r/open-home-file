"""Rendered-page tests for the local web UI.

These assert properties the browser cannot forgive: the page's own
``style-src 'self'`` policy silently drops inline ``style`` attributes, so a
regression there produces a visually broken page with no error. Everything else
here is a contract the plan states explicitly - citations on every field,
confirmation before a reminder exists, and named data classes before deletion.
"""

from __future__ import annotations

import re

import pytest

from homefile import db, fixtures
from homefile.config import Settings
from homefile.service import Library
from homefile.web import pages
from homefile.web.render import confidence_meter

CSRF = "test-csrf-token"


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> Library:
    """One imported library for the whole module: importing fixtures dominates runtime."""
    library = Library(Settings(data_dir=tmp_path_factory.mktemp("web") / "library"))
    library.import_samples()
    return library


def _doc_id(library: Library, name: str) -> str:
    document = next(item for item in library.list_documents() if item.filename == name)
    return document.id


def _all_pages(library: Library) -> dict[str, str]:
    doc_id = _doc_id(library, "sample-warranty.pdf")
    detail = library.get_document(doc_id)
    return {
        "home": pages.home_page(library, csrf=CSRF),
        "documents": pages.documents_page(library, csrf=CSRF),
        "detail": pages.document_page(library, doc_id, csrf=CSRF),
        "detail-field": pages.document_page(
            library, doc_id, csrf=CSRF, field_id=detail.fields[0].id
        ),
        "delete": pages.delete_page(library, doc_id, csrf=CSRF),
        "reminders": pages.reminders_page(library, csrf=CSRF),
        "settings": pages.settings_page(library, csrf=CSRF),
        "error": pages.error_page(library, title="Not found", message="No such page", status=404),
    }


def test_no_page_uses_inline_style_attributes(loaded: Library) -> None:
    # The CSP sets `style-src 'self'`, so an inline style attribute is dropped
    # by the browser without any visible error.
    offenders = {
        name: re.findall(r'style="[^"]*"', html)
        for name, html in _all_pages(loaded).items()
        if 'style="' in html
    }
    assert offenders == {}


def test_table_rows_carry_their_column_names(loaded: Library) -> None:
    """Narrow screens stack rows, so each cell must name its column.

    Below 48rem `app.css` sets every table cell to `display: block` and shows
    the column name from `data-label`. A cell without that attribute loses its
    heading there and reads as an unlabelled value. `display: block` also drops
    the implicit table roles, so the explicit roles are part of the contract.
    """
    for name, html in _all_pages(loaded).items():
        for cell in re.findall(r"<td\b[^>]*>", html):
            assert "data-label=" in cell, f"{name}: cell without a column name: {cell}"
        if "<table" in html:
            assert '<table role="table">' in html, f"{name}: table lost its role"
            assert 'role="columnheader"' in html, f"{name}: headers lost their role"


def test_flash_messages_are_announced_and_escaped(loaded: Library) -> None:
    html = pages.home_page(loaded, csrf=CSRF, flash="imported")
    assert 'role="status"' in html
    assert "Document imported." in html

    error = pages.home_page(loaded, csrf=CSRF, error="<script>alert(1)</script>")
    assert 'role="alert"' in error
    assert "<script>alert(1)</script>" not in error
    assert "&lt;script&gt;" in error


def test_confidence_meter_encodes_the_value_without_inline_style() -> None:
    html = confidence_meter(0.905, threshold=0.8)
    assert 'width="90"' in html or 'width="91"' in html
    assert "90%" in html
    assert "above confirmation threshold" in html

    low = confidence_meter(0.42, threshold=0.8)
    assert "42%" in low
    assert "needs review" in low
    assert "confidence-warn" in low


def test_every_field_row_links_to_a_citation(loaded: Library) -> None:
    doc_id = _doc_id(loaded, "sample-warranty.pdf")
    detail = loaded.get_document(doc_id)
    html = pages.document_page(loaded, doc_id, csrf=CSRF)
    for field in detail.fields:
        assert f'data-field-id="{field.id}"' in html
        assert f"page {field.citation.page}" in html
        assert field.citation.char_start < field.citation.char_end


def test_reminder_controls_only_offer_actions_the_state_allows(loaded: Library) -> None:
    doc_id = _doc_id(loaded, "sample-warranty.pdf")
    detail = loaded.get_document(doc_id)
    suggested = [item for item in detail.reminders if str(item.status) == "suggested"]
    assert suggested, "the warranty fixture should suggest a reminder"
    html = pages.document_page(loaded, doc_id, csrf=CSRF)
    assert "Confirm reminder" in html
    assert "Mark done" not in html

    loaded.confirm_reminder(suggested[0].id)
    html = pages.document_page(loaded, doc_id, csrf=CSRF)
    assert "Mark done" in html
    assert "Confirm reminder" not in html


def test_delete_page_names_every_data_class_it_removes(loaded: Library) -> None:
    doc_id = _doc_id(loaded, "sample-warranty.pdf")
    detail = loaded.get_document(doc_id)
    html = pages.delete_page(loaded, doc_id, csrf=CSRF)
    assert "encrypted original blob" in html
    assert "full-text search index" in html
    assert f"{len(detail.fields)} extracted field(s)" in html
    assert f"{len(detail.reminders)} reminder(s)" in html
    assert 'pattern="DELETE"' in html


def test_settings_page_reports_storage_provider_and_retention(loaded: Library) -> None:
    html = pages.settings_page(loaded, csrf=CSRF)
    assert str(loaded.settings.data_dir) in html
    assert "Local only" in html
    assert "No telemetry" in html
    assert "Export everything" in html


def test_document_page_states_where_text_was_processed(loaded: Library) -> None:
    doc_id = _doc_id(loaded, "sample-warranty.pdf")
    html = pages.document_page(loaded, doc_id, csrf=CSRF)
    assert "no document text was sent to a provider" in html


def test_provider_documents_disclose_the_destination(library: Library) -> None:
    library.import_bytes(fixtures.receipt_pdf(), "receipt.pdf")
    document = library.list_documents()[0]
    # A remote provider is the only path that sets this column, and the test
    # environment blocks sockets, so the recorded value is written directly.
    with db.transaction(library.settings.db_path) as conn:
        conn.execute("UPDATE documents SET processed_by = ? WHERE id = ?", ("ollama", document.id))
    html = pages.document_page(library, document.id, csrf=CSRF)
    assert "Sent to ollama" in html


def test_unreadable_document_explains_the_missing_fields(library: Library) -> None:
    library.import_bytes(fixtures.png_bytes(), "scan.png")
    document = library.list_documents()[0]
    html = pages.document_page(library, document.id, csrf=CSRF)
    assert "no readable text" in html
    assert "nothing to match against" in html


def test_every_post_form_carries_the_csrf_token(loaded: Library) -> None:
    for name, html in _all_pages(loaded).items():
        # GET forms (search, filters) carry no token by design.
        posts = re.findall(r'<form[^>]*method="post"[^>]*>', html)
        tokens = html.count(f'value="{CSRF}"')
        assert tokens >= len(posts), f"{name}: {len(posts)} POST form(s), {tokens} token(s)"
