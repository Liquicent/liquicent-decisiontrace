"""Schema migrations, applied in order and tracked with ``PRAGMA user_version``."""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = [
    # 1: append-only records, derived links, opt-in bodies, store metadata.
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE records (
        seq           INTEGER PRIMARY KEY AUTOINCREMENT,
        id            TEXT NOT NULL UNIQUE,
        record_type   TEXT NOT NULL CHECK (record_type IN ('decision', 'outcome', 'correction')),
        namespace     TEXT NOT NULL,
        trace_id      TEXT,
        decision_kind TEXT,
        intent        TEXT,
        actor_id      TEXT,
        occurred_at   TEXT NOT NULL,
        body          TEXT NOT NULL,
        prev_hash     TEXT NOT NULL,
        hash          TEXT NOT NULL UNIQUE,
        redactions    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX records_trace ON records (trace_id);
    CREATE INDEX records_kind ON records (decision_kind, occurred_at);
    CREATE INDEX records_time ON records (occurred_at);

    CREATE TRIGGER records_no_update BEFORE UPDATE ON records
    BEGIN SELECT RAISE(ABORT, 'decisiontrace: records are append-only'); END;
    CREATE TRIGGER records_no_delete BEFORE DELETE ON records
    BEGIN SELECT RAISE(ABORT, 'decisiontrace: records are append-only'); END;

    CREATE TABLE links (
        src_id    TEXT NOT NULL,
        type      TEXT NOT NULL,
        target_id TEXT NOT NULL,
        PRIMARY KEY (src_id, type, target_id)
    );
    CREATE INDEX links_target ON links (target_id, type);
    CREATE TRIGGER links_no_update BEFORE UPDATE ON links
    BEGIN SELECT RAISE(ABORT, 'decisiontrace: links are append-only'); END;
    CREATE TRIGGER links_no_delete BEFORE DELETE ON links
    BEGIN SELECT RAISE(ABORT, 'decisiontrace: links are append-only'); END;

    -- Opt-in bodies live outside the hash chain so they can be erased on request
    -- without breaking verification. Records only ever hold their hash.
    CREATE TABLE bodies (
        record_id TEXT NOT NULL,
        name      TEXT NOT NULL,
        content   TEXT NOT NULL,
        PRIMARY KEY (record_id, name)
    );
    """,
]


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database up to the latest version; return that version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
    return len(MIGRATIONS)
