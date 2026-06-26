"""SQLite schema initialization and connection management."""

import sqlite3
from pathlib import Path

SCHEMA_SQL: str = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA cache_size=-64000;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS stocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bse_code    TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS filings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id      INTEGER NOT NULL REFERENCES stocks(id),
    filing_uuid   TEXT    NOT NULL UNIQUE,
    filing_type   TEXT,
    filing_date   TEXT    NOT NULL,
    subject       TEXT,
    pdf_url       TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'QUEUED',
    error         TEXT,
    raw_text      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_filings_stock_type_date
    ON filings(stock_id, filing_type, filing_date DESC);

CREATE TABLE IF NOT EXISTS sections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id   INTEGER NOT NULL REFERENCES filings(id),
    header      TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    chunk_hash  TEXT,
    page_num    INTEGER,
    section_idx INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sections_filing_id
    ON sections(filing_id);

CREATE TABLE IF NOT EXISTS diffs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id        INTEGER NOT NULL REFERENCES stocks(id),
    filing_id_new   INTEGER NOT NULL REFERENCES filings(id),
    filing_id_old   INTEGER REFERENCES filings(id),
    section_id_new  INTEGER NOT NULL REFERENCES sections(id),
    section_id_old  INTEGER REFERENCES sections(id),
    section_header  TEXT    NOT NULL,
    significance    TEXT,
    diff_text       TEXT,
    changed         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create tables if not exist. Returns connection with Row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
