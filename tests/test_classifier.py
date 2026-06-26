"""Tests for filing type classifier."""

import pytest
from diffiq.classifier import classify_filing, classify_pending_filings
from diffiq.schema import init_db


class TestClassifier:
    def test_audit_report(self) -> None:
        assert classify_filing("Auditor's Report") == "AUDIT_REPORT"

    def test_financial_result(self) -> None:
        assert classify_filing("Quarterly Results") == "FINANCIAL_RESULT"
        assert classify_filing("Half Yearly Financial Results") == "FINANCIAL_RESULT"
        assert classify_filing("Annual Financial Results") == "FINANCIAL_RESULT"
        assert classify_filing("Standalone Financial Results") == "FINANCIAL_RESULT"

    def test_rpt(self) -> None:
        assert classify_filing("Related Party Transactions") == "RPT"
        assert classify_filing("RPT Disclosure") == "RPT"

    def test_promoter_change(self) -> None:
        assert classify_filing("Promoter Pledge") == "PROMOTER_CHANGE"
        assert classify_filing("Shareholding Pattern") == "PROMOTER_CHANGE"

    def test_board_outcome(self) -> None:
        assert classify_filing("Board Meeting Outcome") == "BOARD_OUTCOME"
        assert classify_filing("Board Meeting") == "BOARD_OUTCOME"
        assert classify_filing("Board Resolution") == "BOARD_OUTCOME"

    def test_routine_default(self) -> None:
        assert classify_filing("Compliance Certificate") == "ROUTINE"
        assert classify_filing("Closure of Trading Window") == "ROUTINE"
        assert classify_filing("") == "ROUTINE"

    def test_case_insensitive(self) -> None:
        assert classify_filing("AUDIT REPORT") == "AUDIT_REPORT"
        assert classify_filing("Quarterly Results") == "FINANCIAL_RESULT"

    def test_empty_subject(self) -> None:
        assert classify_filing("") == "ROUTINE"
        assert classify_filing(None) == "ROUTINE"

    def test_partial_match(self) -> None:
        assert classify_filing("Audit Committee") == "AUDIT_REPORT"

    def test_pending(self) -> None:
        conn = init_db(":memory:")
        conn.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        conn.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status)
               VALUES (1, 1, 'u1', '2026-01-01', 'Audit Report', 'https://ex.com/1.pdf', 'READY')"""
        )
        conn.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status)
               VALUES (2, 1, 'u2', '2026-01-02', 'Compliance Certificate', 'https://ex.com/2.pdf', 'READY')"""
        )
        conn.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status)
               VALUES (3, 1, 'u3', '2026-01-03', 'Quarterly Results', 'https://ex.com/3.pdf', 'READY')"""
        )

        count = classify_pending_filings(conn)
        assert count == 3

        rows = conn.execute(
            "SELECT id, filing_type FROM filings ORDER BY id"
        ).fetchall()
        assert rows[0]["filing_type"] == "AUDIT_REPORT"
        assert rows[1]["filing_type"] == "ROUTINE"
        assert rows[2]["filing_type"] == "FINANCIAL_RESULT"

        conn.close()

    def test_pending_idempotent(self) -> None:
        conn = init_db(":memory:")
        conn.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        conn.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status, filing_type)
               VALUES (1, 1, 'u1', '2026-01-01', 'Audit Report', 'https://ex.com/1.pdf', 'READY', 'AUDIT_REPORT')"""
        )

        count = classify_pending_filings(conn)
        assert count == 0

        conn.close()

    def test_pending_persists_across_connections(self) -> None:
        """classify_pending_filings commits data visible from another connection."""
        import tempfile, os
        db_path = tempfile.mktemp(suffix=".db")

        # Connection 1: insert + classify + commit (inside classify_pending_filings)
        conn1 = init_db(db_path)
        conn1.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        conn1.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status)
               VALUES (1, 1, 'cross-uuid', '2026-01-01', 'Audit Report', 'https://ex.com/1.pdf', 'READY')"""
        )
        conn1.commit()

        count = classify_pending_filings(conn1)
        assert count == 1
        conn1.close()

        # Connection 2: read without any prior connection — should see the commit
        conn2 = init_db(db_path)
        row = conn2.execute(
            "SELECT filing_type FROM filings WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row["filing_type"] == "AUDIT_REPORT"
        conn2.close()
        os.unlink(db_path)
