"""Local HTTP server.

Binds to loopback only. Uses the standard library: ``ThreadingHTTPServer`` with
one handler per request, a per-process CSRF token in a strict cookie and in
every form, and no external assets.

The server is a thin adapter: every route calls :class:`homefile.service.Library`
and renders HTML. There is no JSON API in the first release, so there is no
second surface to keep in sync.
"""

from __future__ import annotations

import mimetypes
import secrets
import traceback
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from ..config import Settings
from ..errors import HomeFileError, NotFound, ValidationError
from ..service import Library
from . import pages

STATIC_DIR = Path(__file__).with_name("static")
COOKIE_NAME = "homefile_csrf"
MAX_FILES_PER_IMPORT = 20
# Multipart framing, headers, and non-file fields on top of the file payloads.
MAX_FORM_OVERHEAD = 1024 * 1024
ALLOWED_STATIC = {"tokens.css", "app.css", "app.js"}


class Upload:
    __slots__ = ("data", "filename")

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.data = data


class MultipartError(ValueError):
    pass


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[Upload]]:
    """Parse a multipart/form-data body into text fields and file uploads."""
    if "boundary=" not in content_type:
        raise MultipartError("missing multipart boundary")
    raw = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1") + body
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not message.is_multipart():
        raise MultipartError("body is not multipart")
    fields: dict[str, str] = {}
    uploads: list[Upload] = []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            payload = b""
        if filename:
            uploads.append(Upload(Path(filename).name, payload))
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
    return fields, uploads


class HomeFileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], library: Library) -> None:
        super().__init__(address, Handler)
        self.library = library
        self.csrf = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenHomeFile/0.1"
    protocol_version = "HTTP/1.1"
    server: HomeFileServer

    # ------------------------------------------------------------- plumbing
    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def _library(self) -> Library:
        return self.server.library

    def _csrf_token(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(COOKIE_NAME)
        if morsel is not None and secrets.compare_digest(morsel.value, self.server.csrf):
            return morsel.value
        return self.server.csrf

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "text/html; charset=utf-8",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # ``no-referrer`` would make Chromium send ``Origin: null`` on form
        # submissions, which breaks same-origin checks; ``same-origin`` still
        # sends nothing to other origins.
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}={self.server.csrf}; Path=/; HttpOnly; SameSite=Strict",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status: int, html: str, *, headers: dict[str, str] | None = None) -> None:
        self._send(status, html.encode("utf-8"), headers=headers)

    def _redirect(self, location: str, *, flash: str | None = None) -> None:
        if flash:
            separator = "&" if "?" in location else "?"
            location = f"{location}{separator}flash={quote(flash)}"
        self._send(
            HTTPStatus.SEE_OTHER,
            b"",
            headers={"Location": location},
        )

    def _error(self, status: int, title: str, message: str) -> None:
        self._html(
            status, pages.error_page(self._library(), title=title, message=message, status=status)
        )

    def _read_form(self) -> tuple[dict[str, str], list[Upload]]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > self._max_body_bytes():
            self.close_connection = True
            raise ValidationError("request body is too large")
        body = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return parse_multipart(body, content_type)
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}, []
        return {}, []

    def _max_body_bytes(self) -> int:
        """Bound request bodies by the configured per-file limit."""
        settings = Settings.from_env()
        return MAX_FILES_PER_IMPORT * settings.max_file_bytes + MAX_FORM_OVERHEAD

    def _check_csrf(self, fields: dict[str, str]) -> None:
        supplied = fields.get("csrf", "")
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(COOKIE_NAME)
        cookie_value = morsel.value if morsel is not None else ""
        if not (
            secrets.compare_digest(supplied, self.server.csrf)
            and secrets.compare_digest(cookie_value, self.server.csrf)
        ):
            raise ValidationError(
                "this form expired or came from another origin; reload the page and try again"
            )

    def _same_origin(self) -> None:
        """Refuse cross-site submissions.

        The CSRF token is the primary control; this is defence in depth. A
        browser may send ``Origin: null`` for a same-origin form (for example
        when a referrer policy suppresses the origin), so an opaque origin is
        allowed to fall through to the token check instead of being rejected.
        """
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in {"same-origin", "none"}:
            raise ValidationError("cross-site form submissions are refused")
        origin = self.headers.get("Origin")
        if origin is None or origin == "null":
            return
        host = self.headers.get("Host", "")
        if origin not in {f"http://{host}", f"https://{host}"}:
            raise ValidationError("cross-origin form submissions are refused")

    # --------------------------------------------------------------- routing
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            self._route_get()
        except NotFound as exc:
            self._error(HTTPStatus.NOT_FOUND, "Not found", str(exc))
        except HomeFileError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "That request could not be completed", str(exc))
        except Exception:
            traceback.print_exc()
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
                "The request failed unexpectedly. The server log has the details; no data was changed.",
            )

    def do_POST(self) -> None:
        try:
            self._route_post()
        except NotFound as exc:
            self._error(HTTPStatus.NOT_FOUND, "Not found", str(exc))
        except HomeFileError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "That change was refused", str(exc))
        except MultipartError as exc:
            self._error(HTTPStatus.BAD_REQUEST, "Upload could not be read", str(exc))
        except Exception:
            traceback.print_exc()
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
                "The request failed unexpectedly. The server log has the details; no data was changed.",
            )

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query, keep_blank_values=True)
        library = self._library()
        csrf = self._csrf_token()

        def param(name: str, default: str = "") -> str:
            values = query.get(name)
            return values[-1] if values else default

        if path == "/":
            self._html(
                HTTPStatus.OK,
                pages.home_page(library, csrf=csrf, flash=param("flash"), error=param("error")),
            )
            return
        if path == "/documents":
            self._html(
                HTTPStatus.OK,
                pages.documents_page(
                    library,
                    csrf=csrf,
                    query=param("q"),
                    vendor=param("vendor"),
                    serial=param("serial"),
                    doc_type=param("type"),
                    min_amount=param("min_amount"),
                    max_amount=param("max_amount"),
                    deadline_before=param("deadline_before"),
                    flash=param("flash"),
                    error=param("error"),
                ),
            )
            return
        if path == "/reminders":
            self._html(
                HTTPStatus.OK,
                pages.reminders_page(
                    library,
                    csrf=csrf,
                    status=param("status"),
                    flash=param("flash"),
                    error=param("error"),
                ),
            )
            return
        if path == "/settings":
            self._html(
                HTTPStatus.OK,
                pages.settings_page(library, csrf=csrf, flash=param("flash"), error=param("error")),
            )
            return
        if path == "/healthz":
            self._send(HTTPStatus.OK, b'{"ok":true}', "application/json")
            return
        if path.startswith("/static/"):
            self._static(path.removeprefix("/static/"))
            return
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "documents":
            doc_id = segments[1]
            if len(segments) == 2:
                self._html(
                    HTTPStatus.OK,
                    pages.document_page(
                        library,
                        doc_id,
                        csrf=csrf,
                        field_id=param("field") or None,
                        flash=param("flash"),
                        error=param("error"),
                    ),
                )
                return
            if len(segments) == 3 and segments[2] == "delete":
                self._html(
                    HTTPStatus.OK,
                    pages.delete_page(
                        library, doc_id, csrf=csrf, flash=param("flash"), error=param("error")
                    ),
                )
                return
            if len(segments) == 3 and segments[2] == "original":
                data = library.source_bytes(doc_id)
                detail = library.get_document(doc_id)
                self._send(
                    HTTPStatus.OK,
                    data,
                    detail.document.media_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="{quote(detail.document.filename)}"',
                    },
                )
                return
        self._error(HTTPStatus.NOT_FOUND, "Not found", f"No page at {path}")

    def _route_post(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        fields, uploads = self._read_form()
        self._same_origin()
        self._check_csrf(fields)
        library = self._library()
        segments = [segment for segment in path.split("/") if segment]

        if path == "/import":
            self._handle_import(uploads)
            return
        if path == "/samples":
            outcomes = library.import_samples()
            imported = sum(1 for outcome in outcomes if not outcome.duplicate)
            duplicates = len(outcomes) - imported
            self._redirect("/", flash=f"samples-{imported}-{duplicates}")
            return
        if path == "/settings/export":
            library.export_library(passphrase=fields.get("passphrase") or None)
            self._redirect("/settings", flash="library-exported")
            return
        if path == "/settings/delete-all":
            if fields.get("confirm", "") != pages.DELETE_CONFIRM_PHRASE:
                raise ValidationError("confirmation phrase did not match")
            library.delete_all()
            self._redirect("/", flash="delete-all")
            return
        if len(segments) >= 3 and segments[0] == "documents":
            doc_id = segments[1]
            action = segments[2]
            if action == "correct":
                field_id = fields.get("field_id", "")
                library.correct_field(
                    field_id,
                    fields.get("value", ""),
                    reason=fields.get("reason", ""),
                )
                self._redirect(f"/documents/{doc_id}?field={quote(field_id)}", flash="corrected")
                return
            if action == "confirm":
                field_id = fields.get("field_id", "")
                library.confirm_field(field_id)
                self._redirect(
                    f"/documents/{doc_id}?field={quote(field_id)}", flash="field-confirmed"
                )
                return
            if action == "reject":
                field_id = fields.get("field_id", "")
                library.reject_field(
                    field_id, reason=fields.get("reason", "") or "rejected by user"
                )
                self._redirect(f"/documents/{doc_id}", flash="field-rejected")
                return
            if action == "export":
                library.export_document(doc_id, passphrase=fields.get("passphrase") or None)
                self._redirect(f"/documents/{doc_id}", flash="exported")
                return
            if action == "delete":
                if fields.get("confirm", "") != pages.DELETE_CONFIRM_PHRASE:
                    raise ValidationError("confirmation phrase did not match")
                library.delete_document(doc_id)
                self._redirect("/documents", flash="deleted")
                return
            if action == "reminders" and len(segments) == 5:
                reminder_id = segments[3]
                verb = segments[4]
                # The reminder panel only renders for its own field, so the
                # action keeps that field selected on the way back.
                field_id = fields.get("field", "")
                back = f"/documents/{doc_id}" + (f"?field={quote(field_id)}" if field_id else "")
                if verb == "confirm":
                    library.confirm_reminder(reminder_id)
                    self._redirect(back, flash="reminder-confirmed")
                    return
                if verb == "dismiss":
                    library.dismiss_reminder(
                        reminder_id, reason=fields.get("reason", "") or "dismissed by user"
                    )
                    self._redirect(back, flash="reminder-dismissed")
                    return
                if verb == "done":
                    library.complete_reminder(reminder_id)
                    self._redirect(back, flash="reminder-done")
                    return
                if verb == "snooze":
                    try:
                        days = int(fields.get("days", "7"))
                    except ValueError as exc:
                        raise ValidationError("snooze days must be a number") from exc
                    library.snooze_reminder(reminder_id, days)
                    self._redirect(back, flash="reminder-snoozed")
                    return
        self._error(HTTPStatus.NOT_FOUND, "Not found", f"No action at {path}")

    # ---------------------------------------------------------------- upload
    def _handle_import(self, uploads: list[Upload]) -> None:
        if not uploads:
            raise ValidationError("choose at least one PDF, PNG, or JPEG file")
        if len(uploads) > MAX_FILES_PER_IMPORT:
            raise ValidationError(f"import at most {MAX_FILES_PER_IMPORT} files at a time")
        library = self._library()
        imported = 0
        duplicate = 0
        failures: list[str] = []
        for upload in uploads:
            try:
                outcome = library.import_bytes(upload.data, upload.filename, actor="local-user")
            except HomeFileError as exc:
                failures.append(f"{upload.filename}: {exc}")
                continue
            if outcome.duplicate:
                duplicate += 1
            else:
                imported += 1
        if failures and not imported and not duplicate:
            raise ValidationError("; ".join(failures[:4]))
        code = f"imported-{imported}-{duplicate}-{len(failures)}"
        if imported == 0 and duplicate:
            self._redirect("/documents", flash=code)
            return
        self._redirect("/", flash=code)

    # ---------------------------------------------------------------- static
    def _static(self, name: str) -> None:
        if name not in ALLOWED_STATIC:
            self._error(HTTPStatus.NOT_FOUND, "Not found", "No such asset")
            return
        target = STATIC_DIR / name
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Not found", "No such asset")
            return
        media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(
            HTTPStatus.OK,
            target.read_bytes(),
            f"{media_type}; charset=utf-8"
            if media_type.startswith(("text/", "application/javascript"))
            else media_type,
            headers={"Cache-Control": "no-cache"},
        )


def serve(library: Library, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the local UI until interrupted."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValidationError(
            "the local UI only binds to loopback; use a reverse proxy if you need remote access"
        )
    server = HomeFileServer((host, port), library)
    actual_host, actual_port = server.server_address[:2]
    print(f"Open Home File listening on http://{actual_host!s}:{int(actual_port)}")
    print(f"Library: {library.settings.data_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
