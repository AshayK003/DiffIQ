"""SQLite helper functions. All queries are parameterized."""

import sqlite3
from typing import Any


def upsert_stock(conn: sqlite3.Connection, bse_code: str, name: str) -> int:
    """Insert a stock if it doesn't exist, or return its id."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO stocks (bse_code, name) VALUES (?, ?)",
        (bse_code, name),
    )
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM stocks WHERE bse_code = ?", (bse_code,)
    ).fetchone()
    return row["id"] if row else 0


def insert_filing(
    conn: sqlite3.Connection,
    stock_id: int,
    filing_uuid: str,
    filing_date: str,
    subject: str | None,
    pdf_url: str,
) -> int:
    """Insert a new filing. Returns filing id."""
    cur = conn.execute(
        """INSERT INTO filings (stock_id, filing_uuid, filing_date, subject, pdf_url)
           VALUES (?, ?, ?, ?, ?)""",
        (stock_id, filing_uuid, filing_date, subject, pdf_url),
    )
    return cur.lastrowid


def update_filing_status(
    conn: sqlite3.Connection, filing_id: int, status: str, error: str | None = None
) -> None:
    """Update filing status and optionally set error message."""
    conn.execute(
        "UPDATE filings SET status = ?, error = ?, updated_at = datetime('now') WHERE id = ?",
        (status, error, filing_id),
    )


def update_filing_type(
    conn: sqlite3.Connection, filing_id: int, filing_type: str
) -> None:
    """Set the filing type classification."""
    conn.execute(
        "UPDATE filings SET filing_type = ?, updated_at = datetime('now') WHERE id = ?",
        (filing_type, filing_id),
    )


def update_filing_raw_text(
    conn: sqlite3.Connection, filing_id: int, raw_text: str
) -> None:
    """Store extracted PDF text."""
    conn.execute(
        "UPDATE filings SET raw_text = ?, updated_at = datetime('now') WHERE id = ?",
        (raw_text, filing_id),
    )


def get_filings_for_stock(
    conn: sqlite3.Connection, stock_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Return recent filings for a stock, newest first."""
    rows = conn.execute(
        """SELECT * FROM filings
           WHERE stock_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (stock_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_filing_by_uuid(
    conn: sqlite3.Connection, filing_uuid: str
) -> dict[str, Any] | None:
    """Look up a filing by its BSE UUID."""
    row = conn.execute(
        "SELECT * FROM filings WHERE filing_uuid = ?", (filing_uuid,)
    ).fetchone()
    return dict(row) if row else None


def get_pending_filings(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Return all filings with QUEUED status."""
    rows = conn.execute(
        "SELECT * FROM filings WHERE status = 'QUEUED' ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_last_filing_of_type(
    conn: sqlite3.Connection, stock_id: int, filing_type: str
) -> dict[str, Any] | None:
    """Most recent filing of a given type for a stock (excludes current)."""
    row = conn.execute(
        """SELECT * FROM filings
           WHERE stock_id = ? AND filing_type = ? AND status NOT IN ('QUEUED', 'ERROR_%')
           ORDER BY filing_date DESC, created_at DESC
           LIMIT 1""",
        (stock_id, filing_type),
    ).fetchone()
    return dict(row) if row else None


def insert_sections(
    conn: sqlite3.Connection, filing_id: int, sections_list: list[dict]
) -> None:
    """Insert multiple sections for a filing."""
    for sec in sections_list:
        conn.execute(
            """INSERT INTO sections (filing_id, header, text, chunk_hash, page_num, section_idx)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                filing_id,
                sec["header"],
                sec["text"],
                sec.get("chunk_hash"),
                sec.get("page_num"),
                sec["section_idx"],
            ),
        )


def get_sections(
    conn: sqlite3.Connection, filing_id: int
) -> list[dict[str, Any]]:
    """Return sections for a filing, ordered by index."""
    rows = conn.execute(
        "SELECT * FROM sections WHERE filing_id = ? ORDER BY section_idx ASC",
        (filing_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_diff(conn: sqlite3.Connection, diff_data: dict) -> int:
    """Insert a diff record. Returns diff id."""
    cur = conn.execute(
        """INSERT INTO diffs (stock_id, filing_id_new, section_id_new, section_header, diff_text, changed)
           VALUES (:stock_id, :filing_id_new, :section_id_new, :section_header, :diff_text, :changed)""",
        diff_data,
    )
    return cur.lastrowid


def get_diffs_for_stock(
    conn: sqlite3.Connection, stock_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    """Return recent diffs for a stock, newest first."""
    rows = conn.execute(
        """SELECT * FROM diffs
           WHERE stock_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (stock_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_diffs_for_filing(
    conn: sqlite3.Connection, filing_id: int, stock_id: int
) -> list[dict[str, Any]]:
    """Return diffs for a specific filing and stock, newest first."""
    rows = conn.execute(
        """SELECT * FROM diffs
           WHERE stock_id = ? AND filing_id_new = ?
           ORDER BY created_at DESC""",
        (stock_id, filing_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio_summary(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Aggregate per-stock filing stats for the portfolio overview.

    Returns one row per stock with:
        id, bse_code, name, total_filings, ready_count, error_count,
        latest_filing_date, latest_subject.
    """
    rows = conn.execute(
        """SELECT
               s.id,
               s.bse_code,
               s.name,
               COUNT(f.id)                                            AS total_filings,
               SUM(CASE WHEN f.status = 'READY'        THEN 1 ELSE 0 END) AS ready_count,
               SUM(CASE WHEN f.status LIKE 'ERROR_%'   THEN 1 ELSE 0 END) AS error_count,
               MAX(f.filing_date)                                      AS latest_filing_date,
               (SELECT f2.subject
                FROM filings f2
                WHERE f2.stock_id = s.id AND f2.status = 'READY'
                ORDER BY f2.filing_date DESC, f2.created_at DESC
                LIMIT 1)                                               AS latest_subject
           FROM stocks s
           LEFT JOIN filings f ON f.stock_id = s.id
           WHERE s.bse_code != ''
           GROUP BY s.id
           ORDER BY s.name"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_stock_by_bse_code(
    conn: sqlite3.Connection, bse_code: str
) -> dict[str, Any] | None:
    """Look up a stock by BSE code."""
    row = conn.execute(
        "SELECT * FROM stocks WHERE bse_code = ?", (bse_code,)
    ).fetchone()
    return dict(row) if row else None
