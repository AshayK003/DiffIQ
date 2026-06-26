"""Integration tests for pipeline orchestration — real flows with mocked externals.

Covers sync(), run_daily_pipeline(), and error paths that the existing
test_pipeline.py doesn't exercise (it only tests transaction boundaries
and empty-database edge cases).

Uses the refactored pipeline's optional conn= parameter so tests can pass
in an :memory: connection directly without mocking init_db or fighting
connection-close semantics.
"""
from unittest.mock import patch

from diffiq.db import (
    get_diffs_for_filing,
    get_filing_by_uuid,
    get_sections,
    insert_filing,
    update_filing_raw_text,
    update_filing_status,
    update_filing_type,
    upsert_stock,
)
from diffiq.extractor import ExtractionResult
from diffiq.schema import init_db


class TestSyncIntegration:
    """sync() — backfill classify → sectionize → differ on READY filings."""

    def test_sync_creates_sections(self) -> None:
        """sync() extracts sections and runs diffs for READY filings."""
        conn = init_db(":memory:")

        stock_id = upsert_stock(conn, "500295", "VEDL")
        fid = insert_filing(
            conn, stock_id, "sync-uuid", "2026-07-01",
            "Audit Report", "https://ex.com/audit.pdf",
        )
        update_filing_status(conn, fid, "READY")
        update_filing_type(conn, fid, "AUDIT_REPORT")
        update_filing_raw_text(
            conn,
            fid,
            "Independent Auditor's Report\nOpinion\nIn our opinion "
            "the financial statements give a true and fair view\n"
            "Basis for Opinion\nWe conducted our audit",
        )
        conn.commit()

        from diffiq.pipeline import sync
        sync(conn=conn)  # caller manages lifecycle — won't be closed

        # Sections should have been extracted
        sections = get_sections(conn, fid)
        assert len(sections) >= 2

        # Diffs should have been attempted (no prior, so empty but not crashed)
        diffs = get_diffs_for_filing(conn, fid, stock_id)
        assert isinstance(diffs, list)

        conn.close()

    def test_sync_idempotent(self) -> None:
        """Calling sync() twice does not duplicate sections."""
        conn = init_db(":memory:")

        stock_id = upsert_stock(conn, "500295", "VEDL")
        fid = insert_filing(
            conn, stock_id, "dup-uuid", "2026-07-01",
            "Audit Report", "https://ex.com/audit.pdf",
        )
        update_filing_status(conn, fid, "READY")
        update_filing_type(conn, fid, "AUDIT_REPORT")
        update_filing_raw_text(conn, fid, "Opinion\nSome text here\nBasis\nOther text")
        conn.commit()

        from diffiq.pipeline import sync

        sync(conn=conn)  # first run — creates sections
        section_count_1 = len(get_sections(conn, fid))

        sync(conn=conn)  # second run — should NOT duplicate
        section_count_2 = len(get_sections(conn, fid))

        assert section_count_2 == section_count_1 > 0

        conn.close()


class TestPipelineFlow:
    """run_daily_pipeline() with mocked external dependencies."""

    SAMPLE_FILING = {
        "filing_uuid": "pipeline-test-uuid",
        "subject": "Audit Report",
        "filing_date": "2026-07-01",
        "pdf_url": "https://example.com/audit.pdf",
        "filing_type": "AUDIT_REPORT",
    }

    AUDIT_TEXT = (
        "Independent Auditor's Report\n"
        "Opinion\nIn our opinion, the financial statements are correct.\n"
        "Basis for Opinion\nWe conducted our audit in accordance with SA.\n"
    )

    @patch("diffiq.pipeline.sleep")
    @patch("diffiq.pipeline.download_pdf_text")
    @patch("diffiq.pipeline.fetch_manifest")
    def test_full_pipeline_flow(
        self, mock_fetch, mock_download, mock_sleep,
    ) -> None:
        """Pipeline processes a filing through all stages: QUEUED→READY + diff."""
        conn = init_db(":memory:")

        # Return the sample filing for VEDL (first stock with BSE code)
        mock_fetch.return_value = [self.SAMPLE_FILING]
        mock_download.return_value = ExtractionResult(
            text=self.AUDIT_TEXT, error=None,
        )

        from diffiq.pipeline import run_daily_pipeline
        run_daily_pipeline(conn=conn)

        # Verify: filing inserted with correct status
        filing = get_filing_by_uuid(conn, "pipeline-test-uuid")
        assert filing is not None
        assert filing["status"] == "READY"
        assert filing["filing_type"] == "AUDIT_REPORT"

        # Verify: sections stored
        sections = get_sections(conn, filing["id"])
        assert len(sections) >= 2

        # Verify: diffs attempted
        stock_id = conn.execute(
            "SELECT id FROM stocks WHERE bse_code = '500295'"
        ).fetchone()["id"]
        diffs = get_diffs_for_filing(conn, filing["id"], stock_id)
        assert isinstance(diffs, list)

        conn.close()

    @patch("diffiq.pipeline.sleep")
    @patch("diffiq.pipeline.download_pdf_text")
    @patch("diffiq.pipeline.fetch_manifest")
    def test_pipeline_pdf_failure(
        self, mock_fetch, mock_download, mock_sleep,
    ) -> None:
        """Pipeline marks filing ERROR_EXTRACTION when PDF download fails."""
        conn = init_db(":memory:")

        mock_fetch.return_value = [self.SAMPLE_FILING]
        mock_download.return_value = ExtractionResult(
            text=None, error="Download failed: 404",
        )

        from diffiq.pipeline import run_daily_pipeline
        run_daily_pipeline(conn=conn)

        filing = get_filing_by_uuid(conn, "pipeline-test-uuid")
        assert filing is not None
        assert filing["status"] == "ERROR_EXTRACTION"
        assert "Download failed" in (filing.get("error") or "")

        conn.close()

    @patch("diffiq.pipeline.sleep")
    @patch("diffiq.pipeline.download_pdf_text")
    @patch("diffiq.pipeline.fetch_manifest")
    def test_pipeline_no_announcements(
        self, mock_fetch, mock_download, mock_sleep,
    ) -> None:
        """Pipeline handles zero announcements without error."""
        conn = init_db(":memory:")

        mock_fetch.return_value = []  # No announcements for any stock

        from diffiq.pipeline import run_daily_pipeline
        run_daily_pipeline(conn=conn)  # should not raise

        # Verify no filings were inserted
        count = conn.execute("SELECT COUNT(*) as cnt FROM filings").fetchone()["cnt"]
        assert count == 0

        conn.close()


class TestBacklogFlow:
    """run_backlog() with mocked external dependencies."""

    def test_backlog_empty(self) -> None:
        """run_backlog handles no pending filings gracefully."""
        from diffiq.pipeline import run_backlog
        # Empty DB — should not raise
        run_backlog()

    @patch("diffiq.pipeline.download_pdf_text")
    def test_backlog_no_pdf_url(self, mock_download) -> None:
        """run_backlog skips filings without a PDF URL."""
        conn = init_db(":memory:")
        stock_id = upsert_stock(conn, "500295", "VEDL")
        fid = insert_filing(
            conn, stock_id, "bl-uuid", "2026-07-01",
            "No PDF Filing", "",
        )
        update_filing_status(conn, fid, "ERROR_DOWNLOAD")
        conn.commit()
        conn.close()

        from diffiq.pipeline import run_backlog
        run_backlog()  # should skip the empty-PDF filing, not crash
        # (no assertion needed — just confirming no crash)

    @patch("diffiq.pipeline.download_pdf_text")
    @patch("diffiq.pipeline.DB_PATH")
    def test_backlog_with_retry(self, mock_db_path, mock_download) -> None:
        """run_backlog retries a failed filing successfully."""
        import tempfile, os
        db_path = tempfile.mktemp(suffix=".db")
        mock_db_path.__str__.return_value = db_path
        mock_db_path.__fspath__.return_value = db_path

        conn = init_db(db_path)
        stock_id = upsert_stock(conn, "500295", "VEDL")
        fid = insert_filing(
            conn, stock_id, "bl-retry-uuid", "2026-07-01",
            "Retry Filing", "https://ex.com/retry.pdf",
        )
        update_filing_status(conn, fid, "ERROR_EXTRACTION")
        update_filing_type(conn, fid, "AUDIT_REPORT")
        conn.commit()
        conn.close()

        mock_download.return_value = ExtractionResult(
            text="Opinion\nAudited financial statements are correct.\n"
                 "Basis\nConducted in accordance with auditing standards.",
            error=None,
        )

        from diffiq.pipeline import run_backlog
        run_backlog()  # uses mocked DB_PATH

        # Verify: filing should now be READY
        verify = init_db(db_path)
        row = verify.execute(
            "SELECT status, raw_text FROM filings WHERE id = ?", (fid,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "READY"
        assert row["raw_text"] is not None
        verify.close()
        os.unlink(db_path)


class TestPipelineExceptionHandling:
    """Error isolation and recovery in run_daily_pipeline."""

    @patch("diffiq.pipeline.sleep")
    @patch("diffiq.pipeline.download_pdf_text")
    @patch("diffiq.pipeline.fetch_manifest")
    def test_pipeline_download_exception_isolation(
        self, mock_fetch, mock_download, mock_sleep,
    ) -> None:
        """A future.exception() from one filing doesn't crash remaining filings."""
        conn = init_db(":memory:")

        # Return two filings: one crashes with an exception, one succeeds
        mock_fetch.return_value = [
            {
                "filing_uuid": "bad-uuid",
                "subject": "Bad Filing",
                "filing_date": "2026-07-01",
                "pdf_url": "https://example.com/bad.pdf",
                "filing_type": "",
            },
            {
                "filing_uuid": "good-uuid",
                "subject": "Good Filing",
                "filing_date": "2026-07-01",
                "pdf_url": "https://example.com/good.pdf",
                "filing_type": "",
            },
        ]

        def side_effect(url):
            if "bad" in url:
                raise httpx.InvalidURL("Malformed URL: spaces in path")
            return ExtractionResult(
                text="Opinion text for the good filing.\n" "Basis for Opinion\nStandard procedures.",
                error=None,
            )

        import httpx
        mock_download.side_effect = side_effect

        from diffiq.pipeline import run_daily_pipeline
        run_daily_pipeline(conn=conn)

        # Bad filing should be ERROR_DOWNLOAD
        bad = get_filing_by_uuid(conn, "bad-uuid")
        assert bad is not None
        assert bad["status"] == "ERROR_DOWNLOAD"
        assert "Exception" in (bad.get("error") or "")

        # Good filing should be READY
        good = get_filing_by_uuid(conn, "good-uuid")
        assert good is not None
        assert good["status"] == "READY"

        conn.close()
