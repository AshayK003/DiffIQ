"""P1 pipeline — crawl BSE, download PDFs, extract text, classify, sectionize, diff."""

import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep

from diffiq.classifier import classify_filing
from diffiq.config import STOCKS, DB_PATH, CRAWL_DELAY_SECONDS
from diffiq.crawler import fetch_manifest
from diffiq.db import (
    get_filing_by_uuid,
    insert_filing,
    update_filing_raw_text,
    update_filing_status,
    update_filing_type,
    upsert_stock,
)
from diffiq.differ import run_diffs_for_filing
from diffiq.extractor import extract_and_store_sections, download_pdf_text
from diffiq.schema import init_db

logger = logging.getLogger(__name__)


def _acquire_pipeline_lock(conn: sqlite3.Connection) -> None:
    """Advisory lock to prevent concurrent pipeline runs.

    Uses a dedicated table with INSERT OR ABORT semantics — the second
    concurrent pipeline instance will block on the UNIQUE constraint
    until the first one commits/closes its transaction.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _pipeline_lock "
        "(id INTEGER PRIMARY KEY, locked_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute("DELETE FROM _pipeline_lock")
    conn.execute("INSERT INTO _pipeline_lock (id) VALUES (1)")
    conn.commit()


def _release_pipeline_lock(conn: sqlite3.Connection) -> None:
    """Release the advisory pipeline lock."""
    conn.execute("DELETE FROM _pipeline_lock")
    conn.commit()


def _process_pdf_result(
    conn: sqlite3.Connection,
    entry: dict,
    filing_id: int,
    stock_id: int,
    result,
) -> bool:
    """Process the result of a PDF download/extraction for a single filing.

    Args:
        conn: SQLite connection.
        entry: BSE manifest entry dict.
        filing_id: DB filing ID.
        stock_id: DB stock ID (used for diff queries).
        result: ExtractionResult from download_pdf_text.

    Returns:
        True if successful (READY), False if error.
    """
    if result.text:
        update_filing_raw_text(conn, filing_id, result.text)
        update_filing_status(conn, filing_id, "READY")
        logger.info("    Extracted %d chars → READY", len(result.text))

        ft = entry.get("filing_type")
        if not ft:
            ft = classify_filing(entry.get("subject", ""))
            update_filing_type(conn, filing_id, ft)

        sections = extract_and_store_sections(conn, filing_id, result.text, ft)
        if not sections:
            logger.info(
                "    No sections extracted for filing %d — filing_type=%s",
                filing_id, ft,
            )
        run_diffs_for_filing(conn, filing_id, stock_id, ft)
        return True
    else:
        error_msg = result.error or "Unknown extraction error"
        update_filing_status(conn, filing_id, "ERROR_EXTRACTION", error_msg)
        logger.info("    Extraction failed → ERROR_EXTRACTION: %s", error_msg)
        return False


_PDF_WORKERS = 3


def run_daily_pipeline(
    conn: sqlite3.Connection | None = None,
) -> None:
    """P0 daily pipeline: crawl BSE announcements, download PDFs, extract, store.

    For each stock in the watchlist:
        1. Fetch announcements from BSE corporate announcements API.
        2. Insert new announcements (QUEUED status).
        3. Download and extract text from filings with PDF URLs.
        4. Update status to READY or ERROR_*.

    Args:
        conn: Optional SQLite connection. If None, opens and manages its own
              connection via init_db(DB_PATH). Pass a connection for testing
              (e.g. :memory:) — caller owns lifecycle and must close it.
    """
    managed: bool = conn is None
    logger.info("=== DiffIQ P0 Pipeline Start ===")

    if managed:
        conn = init_db(DB_PATH)

    # Advisory lock against concurrent pipeline instances
    try:
        _acquire_pipeline_lock(conn)
    except Exception:
        logger.error("Failed to acquire pipeline lock — another instance may be running")
        if managed:
            conn.close()
        return

    total_new: int = 0
    total_errors: int = 0

    try:
        for stock in STOCKS:
            bse_code: str = stock.get("bse_code") or ""
            if not bse_code:
                logger.info(
                    "Skipping %s (no BSE code — ETF/cash equivalent)",
                    stock["name"],
                )
                continue

            name: str = stock["name"]

            # Ensure stock is in DB (use BSE code as unique identifier)
            stock_id: int = upsert_stock(conn, bse_code, name)
            logger.info("Processing %s (BSE=%s, id=%d)", name, bse_code, stock_id)

            # Fetch BSE announcements
            manifest = fetch_manifest(bse_code)
            if not manifest:
                logger.info("  No announcements returned for %s", name)
                sleep(CRAWL_DELAY_SECONDS)
                continue

            new_count: int = 0
            pdf_entries: list[tuple[dict, int]] = []

            # First pass: insert new filings, classify, identify PDF-enabled ones
            for entry in manifest:
                existing = get_filing_by_uuid(conn, entry["filing_uuid"])
                if existing:
                    continue

                filing_id = insert_filing(
                    conn,
                    stock_id,
                    entry["filing_uuid"],
                    entry["filing_date"],
                    entry["subject"],
                    entry["pdf_url"],
                )
                logger.info(
                    "  New filing [%d]: %s — %s",
                    filing_id,
                    entry["filing_date"],
                    entry["subject"][:60],
                )
                new_count += 1

                if entry.get("filing_type"):
                    update_filing_type(conn, filing_id, entry["filing_type"])

                if not entry.get("pdf_url"):
                    update_filing_status(
                        conn, filing_id, "NO_PDF", "No attachment available"
                    )
                    logger.info("    No PDF attachment → NO_PDF")
                    continue

                update_filing_status(conn, filing_id, "DOWNLOADING")
                pdf_entries.append((entry, filing_id))

            # Persist NO_PDF statuses before starting downloads
            conn.commit()

            # Second pass: download PDFs in parallel, process results sequentially
            if pdf_entries:
                conn.commit()
                with ThreadPoolExecutor(max_workers=_PDF_WORKERS) as pool:
                    future_map = {
                        pool.submit(download_pdf_text, en["pdf_url"]): (en, fid)
                        for en, fid in pdf_entries
                    }
                    for future in as_completed(future_map):
                        entry, filing_id = future_map[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            logger.warning(
                                "    Filing %d download failed with exception: %s",
                                filing_id, e,
                            )
                            update_filing_status(
                                conn, filing_id, "ERROR_DOWNLOAD",
                                f"Exception: {e}",
                            )
                            conn.commit()
                            total_errors += 1
                            continue

                        ok = _process_pdf_result(
                            conn, entry, filing_id, stock_id, result,
                        )
                        if not ok:
                            total_errors += 1
                        conn.commit()

            total_new += new_count
            if manifest:
                sleep(CRAWL_DELAY_SECONDS)
    finally:
        _release_pipeline_lock(conn)
        if managed:
            conn.close()
    logger.info(
        "=== Pipeline complete: %d new filings, %d errors ===\n",
        total_new,
        total_errors,
    )


def run_backlog(
    conn: sqlite3.Connection | None = None,
) -> None:
    """Retry QUEUED and ERROR_* filings from previous runs.

    For each pending filing with a PDF URL, re-download, extract text,
    classify, sectionize, and run diffs — just like the initial pipeline
    processing but for filings that were missed or failed.

    Args:
        conn: Optional SQLite connection. If None, opens and manages its own
              connection via init_db(DB_PATH). Pass a connection for testing
              (e.g. :memory:) — caller owns lifecycle and must close it.
    """
    managed: bool = conn is None
    if managed:
        conn = init_db(DB_PATH)

    rows = conn.execute(
        "SELECT f.*, s.bse_code, s.name AS stock_name "
        "FROM filings f "
        "JOIN stocks s ON s.id = f.stock_id "
        "WHERE f.status IN ('QUEUED') "
        "   OR f.status LIKE 'ERROR_%'"
    ).fetchall()

    if not rows:
        logger.info("Backlog: no pending filings to retry")
        if managed:
            conn.close()
        return

    logger.info("Backlog: %d filings to retry", len(rows))
    retried = 0
    for row in rows:
        filing_id = row["id"]
        stock_id = row["stock_id"]
        pdf_url = row["pdf_url"] or ""

        if not pdf_url:
            logger.info("  Filing %d has no PDF URL — skipping", filing_id)
            continue

        update_filing_status(conn, filing_id, "DOWNLOADING")
        conn.commit()

        result = download_pdf_text(pdf_url)
        ok = _process_pdf_result(conn, dict(row), filing_id, stock_id, result)

        if ok:
            retried += 1
        conn.commit()

    if managed:
        conn.close()
    logger.info("Backlog complete: %d filings retried successfully", retried)


def sync(
    conn: sqlite3.Connection | None = None,
) -> None:
    """Backfill all existing READY filings through classify → sectionize → differ.

    Args:
        conn: Optional SQLite connection. If None, opens and manages its own
              connection via init_db(DB_PATH). Pass a connection for testing
              (e.g. :memory:) — caller owns lifecycle and must close it.
    """
    managed: bool = conn is None
    if managed:
        conn = init_db(DB_PATH)

    rows = conn.execute(
        "SELECT id, stock_id, subject, raw_text, filing_type FROM filings WHERE status = 'READY'"
    ).fetchall()

    if not rows:
        logger.info("No READY filings to sync")
        if managed:
            conn.close()
        return

    logger.info("Syncing %d READY filings", len(rows))

    for row in rows:
        try:
            filing_id = row["id"]
            stock_id = row["stock_id"]
            filing_type = row["filing_type"]

            if not filing_type:
                filing_type = classify_filing(row["subject"] or "")
                update_filing_type(conn, filing_id, filing_type)

            raw_text = row["raw_text"]
            if not raw_text:
                logger.info("  Filing %d has no raw_text — skipping", filing_id)
                continue

            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM sections WHERE filing_id = ?",
                (filing_id,),
            ).fetchone()
            if existing and existing["cnt"] == 0:
                extract_and_store_sections(conn, filing_id, raw_text, filing_type)

            # Remove old diffs for this filing before re-running to avoid duplicates
            conn.execute("DELETE FROM diffs WHERE filing_id_new = ?", (filing_id,))
            run_diffs_for_filing(conn, filing_id, stock_id, filing_type)
        except Exception as e:
            logger.error("Filing %d sync failed: %s", row["id"], e)
            continue

    conn.commit()
    if managed:
        conn.close()
    logger.info("Sync complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_daily_pipeline()
