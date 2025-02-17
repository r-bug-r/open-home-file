"""SQLite persistence.

One database file per install. Documents, page text, extracted fields, field
history, reminders, provider ledger, and the deletion log all live here. The
FTS5 index is an external-content index over ``pages`` so deletion of a page
row always removes its index entry.

Connections use ``PRAGMA foreign_keys=ON`` and WAL, and are created per
operation; SQLite is safe for the single-process CLI and local server.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    doc_type_confidence REAL NOT NULL,
    imported_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_source TEXT NOT NULL,
    width REAL,
    height REAL,
    UNIQUE (doc_id, page_no)
) STRICT;

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text,
    content='pages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO pages_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS fields (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    normalized TEXT,
    page_no INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    original_value TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS fields_doc_idx ON fields(doc_id);
CREATE INDEX IF NOT EXISTS fields_name_idx ON fields(name);

CREATE TABLE IF NOT EXISTS field_history (
    id INTEGER PRIMARY KEY,
    field_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    page_no INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    confirmed_by TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders(due_date, status);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    project TEXT NOT NULL,
    workflow TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    estimated_cost TEXT NOT NULL,
    cache_hit INTEGER NOT NULL,
    success INTEGER NOT NULL,
    error_class TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS deletion_log (
    id INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    removed TEXT NOT NULL,
    verified INTEGER NOT NULL,
    remaining TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'local-user'
) STRICT;

CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    doc_id TEXT,
    status TEXT NOT NULL,
    error TEXT
) STRICT;
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA trusted_schema = OFF")
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
        version = int(row["value"]) if row is not None else SCHEMA_VERSION
        if version < 2:
            columns = {info["name"] for info in conn.execute("PRAGMA table_info(reminders)")}
            if "confirmed_by" not in columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN confirmed_by TEXT")
        if version < 3:
            columns = {info["name"] for info in conn.execute("PRAGMA table_info(deletion_log)")}
            if "actor" not in columns:
                conn.execute(
                    "ALTER TABLE deletion_log ADD COLUMN actor TEXT NOT NULL DEFAULT 'local-user'"
                )
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
    finally:
        conn.close()


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
