"""Coverage gap tests for DB helper functions.

Covers get_diffs_for_filing, get_portfolio_summary with real data,
and error-status exclusion in get_last_filing_of_type.
"""

from diffiq.db import (
    get_diffs_for_filing,
    get_diffs_for_stock,
    get_last_filing_of_type,
    get_portfolio_summary,
    insert_diff,
    insert_filing,
    insert_sections,
    update_filing_status,
    update_filing_type,
    upsert_stock,
)


class TestGetDiffsForFiling:
    """get_diffs_for_filing() — the filtered query."""

    def test_filters_by_both_stock_and_filing(self, db):
        """Query returns only diffs matching both stock_id AND filing_id."""
        conn = db
        s1 = upsert_stock(conn, "500295", "VEDL")
        s2 = upsert_stock(conn, "500180", "HDFCBANK")

        # Create a filing for each stock
        f1 = insert_filing(conn, s1, "u1", "2026-06-01", "Filing 1", "https://ex.com/1.pdf")
        f2 = insert_filing(conn, s2, "u2", "2026-06-01", "Filing 2", "https://ex.com/2.pdf")

        # Insert sections so diff FK constraint is satisfied
        conn.execute(
            "INSERT INTO sections (id, filing_id, header, text, section_idx) VALUES (1, ?, 'Opinion', 'v1', 0)",
            (f1,),
        )
        conn.execute(
            "INSERT INTO sections (id, filing_id, header, text, section_idx) VALUES (2, ?, 'Opinion', 'v2', 0)",
            (f2,),
        )

        # Insert diffs: one for stock1/filing1, one for stock2/filing2
        insert_diff(conn, {"stock_id": s1, "filing_id_new": f1, "section_id_new": 1,
                           "section_header": "Opinion", "diff_text": "--- old\n+++ new", "changed": 1})
        insert_diff(conn, {"stock_id": s2, "filing_id_new": f2, "section_id_new": 2,
                           "section_header": "Opinion", "diff_text": "--- old\n+++ new", "changed": 1})
        conn.commit()

        # Query diffs for stock1/filing1 — should return exactly 1
        result = get_diffs_for_filing(conn, f1, s1)
        assert len(result) == 1
        assert result[0]["stock_id"] == s1
        assert result[0]["filing_id_new"] == f1

    def test_no_diffs_returns_empty_list(self, db):
        """Stock with no diffs → [] not crash."""
        conn = db
        s1 = upsert_stock(conn, "500295", "VEDL")
        f1 = insert_filing(conn, s1, "u1", "2026-06-01", "No diffs", "https://ex.com/1.pdf")
        conn.commit()

        result = get_diffs_for_filing(conn, f1, s1)
        assert result == []


class TestGetDiffsForStock:
    """get_diffs_for_stock() edge cases."""

    def test_no_diffs_returns_empty(self, db):
        """Stock with no diffs → [] not crash."""
        conn = db
        s1 = upsert_stock(conn, "500295", "VEDL")
        result = get_diffs_for_stock(conn, s1)
        assert result == []


class TestPortfolioSummary:
    """get_portfolio_summary() with real data."""

    def test_with_data(self, db):
        """Counts, latest_subject populated, ETFs with bse_code='' excluded."""
        conn = db

        # Stock with filings
        s1 = upsert_stock(conn, "500295", "VEDL")
        upsert_stock(conn, "", "NEXT50IETF")  # ETF — should be excluded

        f1 = insert_filing(conn, s1, "u1", "2026-01-15", "Audit 2025", "https://ex.com/1.pdf")
        update_filing_status(conn, f1, "READY")
        update_filing_type(conn, f1, "AUDIT_REPORT")
        conn.execute("UPDATE filings SET raw_text = 'text' WHERE id = ?", (f1,))

        f2 = insert_filing(conn, s1, "u2", "2026-06-20", "Audit 2026", "https://ex.com/2.pdf")
        update_filing_status(conn, f2, "ERROR_EXTRACTION")
        conn.execute("UPDATE filings SET raw_text = 'text' WHERE id = ?", (f2,))
        conn.commit()

        summary = get_portfolio_summary(conn)

        # Check ETF excluded (not in results or filtered)
        codes = [s["bse_code"] for s in summary]
        assert "" not in codes, "ETFs with empty bse_code should be excluded"

        # Check VEDL stats
        vedl = next(s for s in summary if s["name"] == "VEDL")
        assert vedl["total_filings"] == 2
        assert vedl["ready_count"] == 1
        assert vedl["error_count"] == 1
        # latest_subject should come from the READY filing (latest by date)
        assert vedl["latest_subject"] is not None

    def test_empty_db(self, db):
        """No stocks or filings → empty list."""
        result = get_portfolio_summary(db)
        assert result == []


class TestLastFilingOfType:
    """get_last_filing_of_type() error-status exclusion."""

    def test_excludes_error_status(self, db):
        """Error-status filing should NOT be returned as 'last'."""
        conn = db
        s1 = upsert_stock(conn, "500295", "VEDL")

        f1 = insert_filing(conn, s1, "u1", "2026-06-20", "Failed Audit", "https://ex.com/1.pdf")
        update_filing_status(conn, f1, "ERROR_EXTRACTION")
        update_filing_type(conn, f1, "AUDIT_REPORT")
        conn.commit()

        # Only filing is ERROR — should return None
        last = get_last_filing_of_type(conn, s1, "AUDIT_REPORT")
        assert last is None

    def test_returns_ready_over_error(self, db):
        """READY filing preferred over older ERROR one."""
        conn = db
        s1 = upsert_stock(conn, "500295", "VEDL")

        f1 = insert_filing(conn, s1, "u1", "2026-01-15", "Old Ready", "https://ex.com/1.pdf")
        update_filing_status(conn, f1, "READY")
        update_filing_type(conn, f1, "AUDIT_REPORT")

        f2 = insert_filing(conn, s1, "u2", "2026-06-20", "New Error", "https://ex.com/2.pdf")
        update_filing_status(conn, f2, "ERROR_EXTRACTION")
        update_filing_type(conn, f2, "AUDIT_REPORT")
        conn.commit()

        # Should return the READY (older but valid) filing, not the ERROR one
        last = get_last_filing_of_type(conn, s1, "AUDIT_REPORT")
        assert last is not None
        assert last["filing_uuid"] == "u1"
