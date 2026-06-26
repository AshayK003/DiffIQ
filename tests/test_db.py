"""Tests for SQLite data layer."""

import pytest
from diffiq.schema import init_db
from diffiq.db import (
    get_diffs_for_stock,
    get_filing_by_uuid,
    get_filings_for_stock,
    get_last_filing_of_type,
    get_pending_filings,
    get_sections,
    get_stock_by_bse_code,
    insert_diff,
    insert_filing,
    insert_sections,
    update_filing_raw_text,
    update_filing_status,
    update_filing_type,
    upsert_stock,
)


@pytest.fixture
def conn():
    """In-memory SQLite database for testing."""
    c = init_db(":memory:")
    yield c
    c.close()


class TestStocks:
    def test_upsert_new(self, conn) -> None:
        stock_id = upsert_stock(conn, "VEDL", "VEDL")
        assert stock_id is not None
        assert stock_id > 0

    def test_upsert_duplicate(self, conn) -> None:
        id1 = upsert_stock(conn, "VEDL", "VEDL")
        id2 = upsert_stock(conn, "VEDL", "VEDL")
        assert id1 == id2

    def test_get_by_bse_code(self, conn) -> None:
        upsert_stock(conn, "VEDL", "VEDL")
        row = get_stock_by_bse_code(conn, "VEDL")
        assert row is not None
        assert row["name"] == "VEDL"
        assert row["bse_code"] == "VEDL"

    def test_get_missing(self, conn) -> None:
        row = get_stock_by_bse_code(conn, "000000")
        assert row is None


class TestFilings:
    def test_insert_and_query(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(
            conn, stock_id, "test-uuid", "2026-06-25",
            "Test Filing", "https://example.com/test.pdf",
        )
        assert fid is not None

        filings = get_filings_for_stock(conn, stock_id)
        assert len(filings) == 1
        assert filings[0]["filing_uuid"] == "test-uuid"
        assert filings[0]["status"] == "QUEUED"

    def test_get_by_uuid(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        insert_filing(
            conn, stock_id, "uuid-1", "2026-06-25",
            "Filing 1", "https://example.com/1.pdf",
        )
        row = get_filing_by_uuid(conn, "uuid-1")
        assert row is not None
        assert row["subject"] == "Filing 1"

    def test_get_by_uuid_missing(self, conn) -> None:
        row = get_filing_by_uuid(conn, "nonexistent")
        assert row is None

    def test_update_status(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(
            conn, stock_id, "uuid-2", "2026-06-25",
            "Filing 2", "https://example.com/2.pdf",
        )
        update_filing_status(conn, fid, "READY")
        row = get_filing_by_uuid(conn, "uuid-2")
        assert row["status"] == "READY"

    def test_update_status_with_error(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(
            conn, stock_id, "uuid-3", "2026-06-25",
            "Filing 3", "https://example.com/3.pdf",
        )
        update_filing_status(conn, fid, "ERROR_DOWNLOAD", "Connection timeout")
        row = get_filing_by_uuid(conn, "uuid-3")
        assert row["status"] == "ERROR_DOWNLOAD"
        assert row["error"] == "Connection timeout"

    def test_update_type(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(
            conn, stock_id, "uuid-4", "2026-06-25",
            "Auditors Report", "https://example.com/4.pdf",
        )
        update_filing_type(conn, fid, "AUDIT_REPORT")
        row = get_filing_by_uuid(conn, "uuid-4")
        assert row["filing_type"] == "AUDIT_REPORT"

    def test_update_raw_text(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(
            conn, stock_id, "uuid-5", "2026-06-25",
            "Filing 5", "https://example.com/5.pdf",
        )
        update_filing_raw_text(conn, fid, "Extracted text content here")
        row = get_filing_by_uuid(conn, "uuid-5")
        assert row["raw_text"] == "Extracted text content here"

    def test_pending_filings(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        insert_filing(conn, stock_id, "uuid-p1", "2026-06-25", "P1", "https://ex.com/1.pdf")
        insert_filing(conn, stock_id, "uuid-p2", "2026-06-25", "P2", "https://ex.com/2.pdf")
        insert_filing(conn, stock_id, "uuid-p3", "2026-06-25", "P3", "https://ex.com/3.pdf")

        # Mark one as READY
        update_filing_status(conn, 3, "READY")

        pending = get_pending_filings(conn)
        assert len(pending) == 2
        assert all(f["status"] == "QUEUED" for f in pending)

    def test_get_last_filing_of_type(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid1 = insert_filing(conn, stock_id, "uuid-t1", "2026-01-15", "Audit 2025", "https://ex.com/1.pdf")
        update_filing_type(conn, fid1, "AUDIT_REPORT")
        update_filing_status(conn, fid1, "READY")

        fid2 = insert_filing(conn, stock_id, "uuid-t2", "2026-06-20", "Audit 2026", "https://ex.com/2.pdf")
        update_filing_type(conn, fid2, "AUDIT_REPORT")
        update_filing_status(conn, fid2, "READY")

        last = get_last_filing_of_type(conn, stock_id, "AUDIT_REPORT")
        assert last is not None
        assert last["filing_uuid"] == "uuid-t2"


class TestSections:
    def test_insert_and_query(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(conn, stock_id, "sec-uuid", "2026-06-25", "Test", "https://ex.com/sec.pdf")

        sections = [
            {"header": "Auditor's Report", "text": "We have audited...", "chunk_hash": None, "page_num": 1, "section_idx": 0},
            {"header": "Notes to Accounts", "text": "Significant accounting policies...", "chunk_hash": None, "page_num": 5, "section_idx": 1},
        ]
        insert_sections(conn, fid, sections)

        result = get_sections(conn, fid)
        assert len(result) == 2
        assert result[0]["header"] == "Auditor's Report"
        assert result[0]["section_idx"] == 0
        assert result[1]["header"] == "Notes to Accounts"


class TestDiffs:
    def test_insert_and_query(self, conn) -> None:
        stock_id = upsert_stock(conn, "531456", "VEDL")
        fid = insert_filing(conn, stock_id, "diff-uuid", "2026-06-25", "Test", "https://ex.com/diff.pdf")

        # Insert a section so the diff FK constraint is satisfied
        conn.execute(
            "INSERT INTO sections (id, filing_id, header, text, section_idx) VALUES (1, ?, 'Opinion', 'test text', 0)",
            (fid,),
        )

        diff_id = insert_diff(conn, {
            "stock_id": stock_id,
            "filing_id_new": fid,
            "section_id_new": 1,
            "section_header": "Auditor's Report",
            "diff_text": "--- old\n+++ new\n@@ -1 +1 @@\n-true and fair\n+subject to conformity",
            "changed": 1,
        })
        assert diff_id is not None

        diffs = get_diffs_for_stock(conn, stock_id)
        assert len(diffs) == 1
        assert diffs[0]["section_header"] == "Auditor's Report"
        assert diffs[0]["changed"] == 1
