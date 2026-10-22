"""Command-line interface.

Every command is a thin wrapper over :class:`homefile.service.Library`.
Output is JSON by default so it can be scripted and diffed; ``--human`` prints
a compact readable form.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import HomeFileError
from .models import ReminderStatus
from .service import Library


def _emit(payload: Any, human: str | None = None) -> None:
    if human:
        print(human)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _library(args: argparse.Namespace) -> Library:
    settings = Settings.from_env(Path(args.data_dir) if args.data_dir else None)
    return Library(settings)


def _format_field(field: dict[str, Any]) -> str:
    citation = field["citation"]
    return (
        f"  {field['name']:<22} {field['value']!r:<32} "
        f"conf={field['confidence']:.2f} p{citation['page']} "
        f"chars {citation['char_start']}-{citation['char_end']} [{field['status']}]"
    )


def cmd_import(args: argparse.Namespace) -> int:
    library = _library(args)
    outcome = library.import_file(
        Path(args.path), actor=args.actor, date_order=args.date_order, use_model=not args.no_model
    )
    if args.human:
        lines = [
            f"{'Duplicate of' if outcome.duplicate else 'Imported'} {outcome.document.id} "
            f"{outcome.document.filename!r} ({outcome.document.doc_type}, "
            f"conf={outcome.document.doc_type_confidence:.2f}, {outcome.document.page_count} page(s))",
        ]
        lines += [_format_field(field.to_json()) for field in outcome.fields]
        for reminder in outcome.reminders:
            lines.append(
                f"  reminder {reminder.kind:<14} due {reminder.due_date} "
                f"conf={reminder.confidence:.2f} [{reminder.status}]"
            )
        for warning in outcome.warnings:
            lines.append(f"  warning: {warning}")
        _emit(outcome.to_json(), "\n".join(lines))
    else:
        _emit(outcome.to_json())
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    library = _library(args)
    documents = [document.to_json() for document in library.list_documents()]
    if args.human:
        if not documents:
            _emit(documents, "No documents imported.")
            return 0
        lines = [f"{'id':<18} {'type':<13} {'pages':>5}  filename"]
        lines += [
            f"{doc['id']:<18} {doc['doc_type']:<13} {doc['page_count']:>5}  {doc['filename']}"
            for doc in documents
        ]
        _emit(documents, "\n".join(lines))
    else:
        _emit(documents)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    library = _library(args)
    detail = library.get_document(args.doc_id)
    payload = detail.to_json()
    if args.human:
        lines = [
            f"{detail.document.filename} ({detail.document.id})",
            f"  type: {detail.document.doc_type} conf={detail.document.doc_type_confidence:.2f}",
            f"  sha256: {detail.document.sha256}",
            f"  imported: {detail.document.imported_at.isoformat()}",
        ]
        for field in payload["fields"]:
            lines.append(_format_field(field))
        for reminder in payload["reminders"]:
            lines.append(
                f"  reminder {reminder['kind']:<14} due {reminder['due_date']} "
                f"conf={reminder['confidence']:.2f} [{reminder['status']}]"
            )
        _emit(payload, "\n".join(lines))
    else:
        _emit(payload)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    library = _library(args)
    hits = library.search(
        args.query,
        vendor=args.vendor,
        serial=args.serial,
        doc_type=args.type,
        min_amount=args.min_amount,
        max_amount=args.max_amount,
        deadline_before=args.deadline_before,
        deadline_after=args.deadline_after,
        limit=args.limit,
    )
    payload = [hit.to_json() for hit in hits]
    if args.human:
        if not hits:
            _emit(payload, "No matches.")
            return 0
        lines = [
            f"{hit.filename} p{hit.page} ({hit.doc_id})"
            + (f" [{hit.matched_field}]" if hit.matched_field else "")
            + f": {hit.snippet}"
            for hit in hits
        ]
        _emit(payload, "\n".join(lines))
    else:
        _emit(payload)
    return 0


def cmd_correct(args: argparse.Namespace) -> int:
    library = _library(args)
    field = library.correct_field(
        args.field_id, args.value, reason=args.reason, actor=args.actor, date_order=args.date_order
    )
    payload = field.to_json()
    if args.human:
        _emit(payload, _format_field(payload))
    else:
        _emit(payload)
    return 0


def cmd_confirm_field(args: argparse.Namespace) -> int:
    library = _library(args)
    field = library.confirm_field(args.field_id, actor=args.actor)
    payload = field.to_json()
    if args.human:
        _emit(payload, _format_field(payload))
    else:
        _emit(payload)
    return 0


def cmd_reject_field(args: argparse.Namespace) -> int:
    library = _library(args)
    field = library.reject_field(args.field_id, reason=args.reason, actor=args.actor)
    payload = field.to_json()
    if args.human:
        _emit(payload, _format_field(payload))
    else:
        _emit(payload)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    library = _library(args)
    entries = [
        {
            "action": entry.action,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
            "reason": entry.reason,
            "actor": entry.actor,
            "at": entry.at.isoformat(),
        }
        for entry in library.history(args.field_id)
    ]
    if args.human:
        lines = [
            f"{item['at']} {item['action']:<20} {item['old_value']!r} -> {item['new_value']!r}"
            f"  ({item['actor']}: {item['reason']})"
            for item in entries
        ]
        _emit(entries, "\n".join(lines) if lines else "No history.")
    else:
        _emit(entries)
    return 0


def cmd_reminders(args: argparse.Namespace) -> int:
    library = _library(args)
    reminders = [reminder.to_json() for reminder in library.list_reminders(args.status)]
    if args.human:
        if not reminders:
            _emit(reminders, "No reminders.")
            return 0
        lines = [
            f"{item['due_date']} {item['kind']:<14} [{item['status']}] "
            f"conf={item['confidence']:.2f} doc={item['doc_id']} {item['note']}"
            for item in reminders
        ]
        _emit(reminders, "\n".join(lines))
    else:
        _emit(reminders)
    return 0


def cmd_confirm_reminder(args: argparse.Namespace) -> int:
    library = _library(args)
    reminder = library.confirm_reminder(args.reminder_id, actor=args.actor).to_json()
    if args.human:
        _emit(reminder, f"Confirmed {reminder['kind']} reminder due {reminder['due_date']}")
    else:
        _emit(reminder)
    return 0


def cmd_dismiss_reminder(args: argparse.Namespace) -> int:
    library = _library(args)
    reminder = library.dismiss_reminder(
        args.reminder_id, reason=args.reason, actor=args.actor
    ).to_json()
    if args.human:
        _emit(reminder, f"Dismissed {reminder['kind']} reminder ({args.reason})")
    else:
        _emit(reminder)
    return 0


def cmd_due(args: argparse.Namespace) -> int:
    library = _library(args)
    reminders = [reminder.to_json() for reminder in library.due_reminders()]
    if args.human:
        if not reminders:
            _emit(reminders, "Nothing due.")
            return 0
        lines = [
            f"{item['due_date']} {item['kind']:<14} doc={item['doc_id']} {item['note']}"
            for item in reminders
        ]
        _emit(reminders, "\n".join(lines))
    else:
        _emit(reminders)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    library = _library(args)
    target = library.export_document(args.doc_id, passphrase=args.passphrase)
    payload = {"path": str(target), "encrypted": target.suffix == ".hfe"}
    if args.human:
        _emit(
            payload,
            f"Exported to {target} ({'encrypted' if payload['encrypted'] else 'plain zip'})",
        )
    else:
        _emit(payload)
    return 0


def cmd_export_all(args: argparse.Namespace) -> int:
    library = _library(args)
    target = library.export_library(passphrase=args.passphrase)
    payload = {"path": str(target), "encrypted": target.suffix == ".hfe"}
    if args.human:
        _emit(
            payload,
            f"Exported library to {target} ({'encrypted' if payload['encrypted'] else 'plain zip'})",
        )
    else:
        _emit(payload)
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    library = _library(args)
    report = library.delete_document(args.doc_id, actor=args.actor)
    payload = report.to_json()
    if args.human:
        _emit(payload, f"Deleted {report.doc_id}; verified removal of: {', '.join(report.removed)}")
    else:
        _emit(payload)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    library = _library(args)
    report = library.verify_integrity()
    payload = report.to_json()
    if args.human:
        text = f"{report.documents} document(s), {report.blobs} blob(s); " + (
            "integrity verified" if report.verified else "PROBLEMS: " + "; ".join(report.problems)
        )
        _emit(payload, text)
    else:
        _emit(payload)
    return 0 if report.verified else 1


def cmd_stats(args: argparse.Namespace) -> int:
    library = _library(args)
    payload = library.stats()
    if args.human:
        _emit(payload, "\n".join(f"{key}: {value}" for key, value in payload.items()))
    else:
        _emit(payload)
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    library = _library(args)
    entries = library.ledger()
    if args.human:
        if not entries:
            _emit(entries, "No provider calls recorded.")
            return 0
        lines = [
            f"{item['started_at']} {item['provider']}/{item['model']} "
            f"in={item['input_tokens']} out={item['output_tokens']} "
            f"cost={item['estimated_cost']} ok={bool(item['success'])}"
            for item in entries
        ]
        _emit(entries, "\n".join(lines))
    else:
        _emit(entries)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web.server import serve

    serve(_library(args), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homefile",
        description="Local-first household document index with citations and reminders.",
    )
    parser.add_argument("--data-dir", help="library directory (default: per-user data dir)")
    parser.add_argument("--human", action="store_true", help="print a compact readable summary")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="import a PDF, PNG, or JPEG")
    import_parser.add_argument("path")
    import_parser.add_argument("--actor", default="local-user")
    import_parser.add_argument("--date-order", choices=("dmy", "mdy"), default="dmy")
    import_parser.add_argument(
        "--no-model", action="store_true", help="deterministic extraction only"
    )
    import_parser.set_defaults(func=cmd_import)

    list_parser = subparsers.add_parser("list", help="list documents")
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show", help="show a document with fields and citations")
    show_parser.add_argument("doc_id")
    show_parser.set_defaults(func=cmd_show)

    search_parser = subparsers.add_parser("search", help="search text and structured fields")
    search_parser.add_argument("query", nargs="?", default=None)
    search_parser.add_argument("--vendor")
    search_parser.add_argument("--serial")
    search_parser.add_argument("--type", dest="type")
    search_parser.add_argument("--min-amount")
    search_parser.add_argument("--max-amount")
    search_parser.add_argument("--deadline-before")
    search_parser.add_argument("--deadline-after")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.set_defaults(func=cmd_search)

    correct_parser = subparsers.add_parser("correct", help="correct an extracted field")
    correct_parser.add_argument("field_id")
    correct_parser.add_argument("value")
    correct_parser.add_argument("--reason", required=True)
    correct_parser.add_argument("--actor", default="local-user")
    correct_parser.add_argument("--date-order", choices=("dmy", "mdy"), default="dmy")
    correct_parser.set_defaults(func=cmd_correct)

    confirm_field_parser = subparsers.add_parser(
        "confirm-field", help="accept a field as extracted"
    )
    confirm_field_parser.add_argument("field_id")
    confirm_field_parser.add_argument("--actor", default="local-user")
    confirm_field_parser.set_defaults(func=cmd_confirm_field)

    reject_field_parser = subparsers.add_parser("reject-field", help="reject an extracted field")
    reject_field_parser.add_argument("field_id")
    reject_field_parser.add_argument("--reason", required=True)
    reject_field_parser.add_argument("--actor", default="local-user")
    reject_field_parser.set_defaults(func=cmd_reject_field)

    history_parser = subparsers.add_parser("history", help="show a field's provenance history")
    history_parser.add_argument("field_id")
    history_parser.set_defaults(func=cmd_history)

    reminders_parser = subparsers.add_parser("reminders", help="list reminders")
    reminders_parser.add_argument("--status", choices=[status.value for status in ReminderStatus])
    reminders_parser.set_defaults(func=cmd_reminders)

    confirm_reminder_parser = subparsers.add_parser(
        "confirm-reminder", help="confirm a suggested reminder"
    )
    confirm_reminder_parser.add_argument("reminder_id")
    confirm_reminder_parser.add_argument("--actor", default="local-user")
    confirm_reminder_parser.set_defaults(func=cmd_confirm_reminder)

    dismiss_reminder_parser = subparsers.add_parser("dismiss-reminder", help="dismiss a reminder")
    dismiss_reminder_parser.add_argument("reminder_id")
    dismiss_reminder_parser.add_argument("--reason", required=True)
    dismiss_reminder_parser.add_argument("--actor", default="local-user")
    dismiss_reminder_parser.set_defaults(func=cmd_dismiss_reminder)

    due_parser = subparsers.add_parser("due", help="list confirmed reminders that are due")
    due_parser.set_defaults(func=cmd_due)

    export_parser = subparsers.add_parser("export", help="export a document bundle")
    export_parser.add_argument("doc_id")
    export_parser.add_argument("--passphrase", help="encrypt the export with this passphrase")
    export_parser.set_defaults(func=cmd_export)

    export_all_parser = subparsers.add_parser(
        "export-all", help="export every document, field, and reminder as one archive"
    )
    export_all_parser.add_argument("--passphrase", help="encrypt the export with this passphrase")
    export_all_parser.set_defaults(func=cmd_export_all)

    delete_parser = subparsers.add_parser("delete", help="delete a document and verify removal")
    delete_parser.add_argument("doc_id")
    delete_parser.add_argument("--actor", default="local-user")
    delete_parser.set_defaults(func=cmd_delete)

    verify_parser = subparsers.add_parser("verify", help="verify stored blobs against their hashes")
    verify_parser.set_defaults(func=cmd_verify)

    stats_parser = subparsers.add_parser("stats", help="show library counts and spend")
    stats_parser.set_defaults(func=cmd_stats)

    ledger_parser = subparsers.add_parser("ledger", help="show the provider cost ledger")
    ledger_parser.set_defaults(func=cmd_ledger)

    serve_parser = subparsers.add_parser("serve", help="start the local web UI on loopback")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(func=cmd_serve)

    smoke_parser = subparsers.add_parser("smoke", help="run the end-to-end smoke scenario")
    smoke_parser.add_argument("--work-dir", help="directory for generated fixtures and data")
    smoke_parser.set_defaults(func=cmd_smoke)

    samples_parser = subparsers.add_parser(
        "samples", help="write synthetic sample documents for a safe first run"
    )
    samples_parser.add_argument(
        "directory", nargs="?", default="samples", help="target directory (default: ./samples)"
    )
    samples_parser.set_defaults(func=cmd_samples)

    return parser


def cmd_samples(args: argparse.Namespace) -> int:
    from .fixtures import write_samples

    written = write_samples(Path(args.directory))
    payload = {
        name: {"path": str(path), "bytes": path.stat().st_size} for name, path in written.items()
    }
    if args.human:
        _emit(
            payload,
            "\n".join(
                f"{name}: {entry['path']} ({entry['bytes']} bytes)"
                for name, entry in payload.items()
            ),
        )
    else:
        _emit(payload)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    from .smoke import run_smoke

    report = run_smoke(Path(args.work_dir) if args.work_dir else None)
    _emit(report)
    return 0 if report.get("ok") else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HomeFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
