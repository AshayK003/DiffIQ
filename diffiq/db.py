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
    """Insert a new filing. Returns filing id.

    Uses INSERT OR IGNORE so a concurrent pipeline instance inserting the same
    filing_uuid does not crash — instead returns the existing filing's id.
    """
    conn.execute(
        """INSERT OR IGNORE INTO filings (stock_id, filing_uuid, filing_date, subject, pdf_url)
           VALUES (?, ?, ?, ?, ?)""",
        (stock_id, filing_uuid, filing_date, subject, pdf_url),
    )
    row = conn.execute(
        "SELECT id FROM filings WHERE filing_uuid = ?", (filing_uuid,)
    ).fetchone()
    return row["id"] if row else 0


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
    conn: sqlite3.Connection, stock_id: int, filing_type: str,
    exclude_id: int | None = None,
) -> dict[str, Any] | None:
    """Most recent filing of a given type for a stock.

    Args:
        conn: SQLite connection.
        stock_id: Stock ID.
        filing_type: Filing type string.
        exclude_id: Optional filing ID to exclude (for finding prior filings).

    Returns:
        Filing dict or None if none found.
    """
    if exclude_id is not None:
        row = conn.execute(
            """SELECT * FROM filings
               WHERE stock_id = ? AND filing_type = ?
                 AND id != ?
                 AND status NOT IN ('QUEUED')
                 AND status NOT LIKE 'ERROR_%'
               ORDER BY filing_date DESC, created_at DESC
               LIMIT 1""",
            (stock_id, filing_type, exclude_id),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM filings
               WHERE stock_id = ? AND filing_type = ?
                 AND status NOT IN ('QUEUED')
                 AND status NOT LIKE 'ERROR_%'
               ORDER BY filing_date DESC, created_at DESC
               LIMIT 1""",
            (stock_id, filing_type),
        ).fetchone()
    return dict(row) if row else None


def insert_sections(
    conn: sqlite3.Connection, filing_id: int, sections_list: list[dict]
) -> None:
    """Insert multiple sections for a filing (batch executemany)."""
    conn.executemany(
        """INSERT INTO sections (filing_id, header, text, chunk_hash, page_num, section_idx)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                filing_id,
                sec["header"],
                sec["text"],
                sec.get("chunk_hash"),
                sec.get("page_num"),
                sec["section_idx"],
            )
            for sec in sections_list
        ],
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


def get_sections_for_filings(
    conn: sqlite3.Connection, filing_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """Fetch all sections for multiple filings in one query.

    Args:
        conn: SQLite connection.
        filing_ids: List of filing IDs to fetch sections for (max 500).

    Returns:
        Dict mapping each filing_id to its list of section dicts.
        Filings with no sections are absent from the dict.

    Raises:
        ValueError: If filing_ids exceeds 500 entries.
    """
    if not filing_ids:
        return {}
    if len(filing_ids) > 500:
        raise ValueError(
            f"filing_ids too large: {len(filing_ids)} (max 500)"
        )
    placeholders = ",".join("?" * len(filing_ids))
    rows = conn.execute(
        f"SELECT * FROM sections WHERE filing_id IN ({placeholders}) ORDER BY filing_id, section_idx",
        filing_ids,
    ).fetchall()
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        d = dict(row)
        result.setdefault(d["filing_id"], []).append(d)
    return result


def insert_diff(conn: sqlite3.Connection, diff_data: dict) -> int:
    """Insert a diff record. Returns diff id."""
    cur = conn.execute(
        """INSERT INTO diffs (stock_id, filing_id_new, filing_id_old,
                              section_id_new, section_id_old,
                              section_header, diff_text, changed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            diff_data["stock_id"],
            diff_data["filing_id_new"],
            diff_data.get("filing_id_old"),
            diff_data["section_id_new"],
            diff_data.get("section_id_old"),
            diff_data["section_header"],
            diff_data["diff_text"],
            diff_data["changed"],
        ),
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


def get_diffs_for_filings(
    conn: sqlite3.Connection, filing_ids: list[int], stock_id: int
) -> dict[int, list[dict[str, Any]]]:
    """Fetch all diffs for multiple filings in one query.

    Args:
        conn: SQLite connection.
        filing_ids: List of filing IDs to fetch diffs for (max 500).
        stock_id: Stock ID to filter by.

    Returns:
        Dict mapping each filing_id_new to its list of diff dicts.
        Filings with no diffs are absent from the dict.

    Raises:
        ValueError: If filing_ids exceeds 500 entries.
    """
    if not filing_ids:
        return {}
    if len(filing_ids) > 500:
        raise ValueError(
            f"filing_ids too large: {len(filing_ids)} (max 500)"
        )
    placeholders = ",".join("?" * len(filing_ids))
    rows = conn.execute(
        f"""SELECT * FROM diffs
           WHERE stock_id = ? AND filing_id_new IN ({placeholders})
           ORDER BY filing_id_new, created_at DESC""",
        [stock_id, *filing_ids],
    ).fetchall()
    result: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        d = dict(row)
        result.setdefault(d["filing_id_new"], []).append(d)
    return result


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
