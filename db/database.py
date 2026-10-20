"""
Mini ARK database layer.

Governing rule: this module never decides what is TRUE. It only stores
what was observed, proposed, or accepted, with provenance attached.
"""

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the Mini ARK ledger."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_readonly_connection(db_path: str) -> sqlite3.Connection:
    """Open an existing Mini ARK ledger for observation-only commands."""
    path = Path(db_path).resolve()
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql. Safe to run repeatedly (all statements are IF NOT EXISTS)."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    migrate_schema(conn)


# CREATE TABLE IF NOT EXISTS only ever creates a table the FIRST time it
# doesn't exist -- it is a permanent no-op on any table that already
# exists, even if schema.sql has since grown new columns on it. A ledger
# bootstrapped under an older version of this file will silently keep
# missing those columns forever unless something retrofits them. This is
# that something. Only columns ADDED to already-existing tables need an
# entry here -- brand new tables are already handled correctly by
# CREATE TABLE IF NOT EXISTS and don't need to appear below.
_RETROFIT_COLUMNS = {
    "scans": [
        ("last_committed_path", "TEXT"),
        ("interrupted_at", "TEXT"),
    ],
    "proposals": [
        ("batch_key", "TEXT"),
    ],
    "protected_paths": [
        ("category", "TEXT NOT NULL DEFAULT 'user_reserved'"),
    ],
    "stewardship_findings": [
        ("shadow_run_id", "INTEGER REFERENCES shadow_runs(id)"),
        ("resolution_strategy", "TEXT"),
        ("evidence_source", "TEXT"),
        ("lifecycle_posture", "TEXT"),
        ("attention_posture", "TEXT"),
        ("confidence_dimensions_json", "TEXT"),
    ],
    "stewardship_proposals": [
        ("shadow_run_id", "INTEGER REFERENCES shadow_runs(id)"),
        ("resolution_strategy", "TEXT"),
    ],
}


def migrate_schema(conn: sqlite3.Connection) -> list:
    """
    Adds any columns schema.sql expects but CREATE TABLE IF NOT EXISTS
    couldn't retrofit onto an already-existing table. Safe to run every
    time: skips columns that already exist, never rewrites or touches
    existing rows, never drops anything. Returns the list of columns it
    actually added, so callers can report what changed.
    """
    added = []
    for table, columns in _RETROFIT_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}
        if not existing:
            continue  # table doesn't exist yet -- CREATE TABLE IF NOT EXISTS will handle it
        for col_name, col_ddl in columns:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl};")
                added.append(f"{table}.{col_name}")
    if added:
        conn.commit()
    return added


def get_schema_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT MAX(version) as v FROM schema_version;")
    row = cur.fetchone()
    return row["v"] if row and row["v"] is not None else 0


def record_source(conn: sqlite3.Connection, kind: str, label: str = None, platform: str = None) -> int:
    """Every ingestion should call this first, then attach the returned id
    to whatever it records. This is what makes 'why do you think this?'
    an answerable question later."""
    cur = conn.execute(
        "INSERT INTO sources (kind, label, platform) VALUES (?, ?, ?);",
        (kind, label, platform),
    )
    conn.commit()
    return cur.lastrowid


def get_or_create_project(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("SELECT id FROM projects WHERE name = ?;", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]

    entity_cur = conn.execute(
        "INSERT OR IGNORE INTO entities (entity_type, name) VALUES ('project', ?);",
        (name,),
    )
    ent_row = conn.execute(
        "SELECT id FROM entities WHERE entity_type='project' AND name=?;", (name,)
    ).fetchone()
    entity_id = ent_row["id"]

    cur = conn.execute(
        "INSERT INTO projects (entity_id, name) VALUES (?, ?);",
        (entity_id, name),
    )
    conn.commit()
    return cur.lastrowid
