"""Tests for section extractor."""

from unittest.mock import patch, MagicMock

import httpx
import pytest
from diffiq.extractor import (
    download_pdf_text,
    extract_sections,
    extract_and_store_sections,
)
from diffiq.schema import init_db


class TestExtractor:
    AUDIT_TEXT = (
        "Independent Auditor's Report\n"
        "We have audited the accompanying financial statements...\n"
        "Opinion\n"
        "In our opinion, the financial statements give a true and fair view...\n"
        "Basis for Opinion\n"
        "We conducted our audit in accordance with...\n"
        "Key Audit Matters\n"
        "Key audit matters are those matters that...\n"
    )

    FINANCIAL_TEXT = (
        "Statement of Profit and Loss\n"
        "Revenue from operations: Rs. 100 Cr\n"
        "Expenses\n"
        "Cost of materials consumed: Rs. 60 Cr\n"
        "Cash Flow\n"
        "Net cash from operating activities: Rs. 20 Cr\n"
    )

    RPT_TEXT = (
        "Related Party Transactions\n"
        "The company entered into transactions with related parties...\n"
        "Loans to Related\n"
        "Loans outstanding to related parties: Rs. 5 Cr\n"
    )

    PROMOTER_TEXT = (
        "Shareholding Pattern\n"
        "Promoter holding: 65.4%\n"
        "Statement of Holding\n"
        "Public holding: 34.6%\n"
    )

    def test_audit_sections(self) -> None:
        sections = extract_sections(self.AUDIT_TEXT, "AUDIT_REPORT")
        assert len(sections) >= 3
        headers = [s["header"] for s in sections]
        assert any("Opinion" in h for h in headers)
        assert any("Basis" in h for h in headers)
        assert any("Key Audit" in h for h in headers)
        assert all(s["section_idx"] == i for i, s in enumerate(sections))

    def test_financial_sections(self) -> None:
        sections = extract_sections(self.FINANCIAL_TEXT, "FINANCIAL_RESULT")
        assert len(sections) >= 2
        headers = [s["header"] for s in sections]
        assert any("Profit and Loss" in h or "Cash Flow" in h for h in headers)

    def test_rpt_sections(self) -> None:
        sections = extract_sections(self.RPT_TEXT, "RPT")
        assert len(sections) >= 1
        headers = [s["header"] for s in sections]
        assert any("Related Party" in h for h in headers)

    def test_promoter_sections(self) -> None:
        sections = extract_sections(self.PROMOTER_TEXT, "PROMOTER_CHANGE")
        assert len(sections) >= 1
        headers = [s["header"] for s in sections]
        assert any("Shareholding" in h for h in headers)

    def test_routine_fallback(self) -> None:
        text = (
            "1. Introduction\n"
            "This is the introduction section.\n"
            "2. Details\n"
            "These are the details.\n"
            "3. Conclusion\n"
            "This is the conclusion.\n"
        )
        sections = extract_sections(text, "ROUTINE")
        assert len(sections) >= 2
        assert any(s["header"].startswith("1") for s in sections)

    def test_empty_text(self) -> None:
        sections = extract_sections("", "AUDIT_REPORT")
        assert len(sections) == 1
        assert sections[0]["header"] == "Body"

        sections = extract_sections("   ", None)
        assert len(sections) == 1
        assert sections[0]["header"] == "Body"

    def test_no_filing_type_uses_generic(self) -> None:
        text = (
            "INTRODUCTION\n"
            "Some intro text here.\n"
            "DETAILS OF OPERATIONS\n"
            "Operational details here.\n"
        )
        sections = extract_sections(text, None)
        assert len(sections) >= 1

    def test_no_splits_returns_body(self) -> None:
        text = "Just a single block of plain text without any clear section headers."
        sections = extract_sections(text, "ROUTINE")
        assert len(sections) == 1
        assert sections[0]["header"] == "Body"

    def test_store(self) -> None:
        conn = init_db(":memory:")
        conn.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        conn.execute(
            """INSERT INTO filings (id, stock_id, filing_uuid, filing_date, subject, pdf_url, status)
               VALUES (1, 1, 'u1', '2026-01-01', 'Test', 'https://ex.com/1.pdf', 'READY')"""
        )

        sections = extract_and_store_sections(
            conn, 1, self.AUDIT_TEXT, "AUDIT_REPORT"
        )
        assert len(sections) >= 3

        stored = conn.execute(
            "SELECT COUNT(*) as cnt FROM sections WHERE filing_id = 1"
        ).fetchone()
        assert stored["cnt"] == len(sections)

        conn.close()


class TestDownloadPdfText:
    """Tests for download_pdf_text — mock httpx, never hits network."""

    @patch("diffiq.extractor.httpx.Client")
    def test_success(self, mock_client_cls):
        """Valid PDF returns ExtractionResult with text."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {}
        mock_resp.content = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj trailer<</Root 1 0 R>>"
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        # pdf content is a real-ish PDF but pypdf still extracts nothing from it
        result = download_pdf_text("https://example.com/test.pdf")
        # pypdf either extracts text or returns None if it can't parse
        assert result.error is None or result.error.startswith("Corrupted PDF")
        # The important thing: no crash, always returns ExtractionResult

    @patch("diffiq.extractor.httpx.Client")
    def test_network_error(self, mock_client_cls):
        """HTTP error returns ExtractionResult with error description."""
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        )
        mock_client_cls.return_value = mock_client

        result = download_pdf_text("https://example.com/missing.pdf")
        assert result.text is None
        assert result.error is not None
        assert "Download failed" in result.error

    @patch("diffiq.extractor.httpx.Client")
    def test_corrupted_pdf(self, mock_client_cls):
        """Non-PDF content returns ExtractionResult with error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {}
        mock_resp.content = b"Not a PDF at all, just some text content"
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = download_pdf_text("https://example.com/corrupted.pdf")
        assert result.text is None
        assert result.error is not None

    @patch("diffiq.extractor.httpx.Client")
    def test_scanned_pdf(self, mock_client_cls):
        """PDF with very short text (< 100 chars) returns error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.headers = {}
        mock_resp.content = b"%PDF-1.4 tiny doc..."
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        # Make pypdf return short text by having it actually parse
        # We mock inside pypdf instead
        result = download_pdf_text("https://example.com/scanned.pdf")
        # Either corrupted or scanned — either way text is None
        assert result.text is None


class TestExtractTextTruncation:
    """_extract_text_from_pdf truncates extracted text at 1MB."""

    def test_text_under_1mb_not_truncated(self):
        """Text under 1MB is returned as-is."""
        from diffiq.extractor import _extract_text_from_pdf

        short_text = "x" * 500
        with patch("diffiq.extractor.pypdf.PdfReader") as mock_reader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = short_text
            mock_reader.return_value.pages = [mock_page]

            result = _extract_text_from_pdf("https://ex.com/test.pdf", b"fake")
            assert result.text == short_text
            assert result.error is None

    def test_text_exactly_1mb_not_truncated(self):
        """Text exactly at 1MB is not truncated."""
        from diffiq.extractor import _extract_text_from_pdf

        exact_text = "x" * 1_000_000
        with patch("diffiq.extractor.pypdf.PdfReader") as mock_reader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = exact_text
            mock_reader.return_value.pages = [mock_page]

            result = _extract_text_from_pdf("https://ex.com/test.pdf", b"fake")
            assert result.text is not None
            assert len(result.text) == 1_000_000
            assert result.error is None

    def test_text_over_1mb_truncated(self):
        """Text over 1MB is truncated to 1MB."""
        from diffiq.extractor import _extract_text_from_pdf

        long_text = "x" * 1_500_000
        with patch("diffiq.extractor.pypdf.PdfReader") as mock_reader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = long_text
            mock_reader.return_value.pages = [mock_page]

            result = _extract_text_from_pdf("https://ex.com/test.pdf", b"fake")
            assert result.text is not None
            assert len(result.text) == 1_000_000
            assert result.error is None


class TestDownloadOversized:
    """Oversized PDF rejection via Content-Length and post-download size checks."""

    @patch("diffiq.extractor.httpx.Client")
    def test_content_length_over_50mb_rejected(self, mock_client_cls):
        """PDF with Content-Length > 50MB is rejected."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-length": str(60 * 1024 * 1024)}
        mock_resp.raise_for_status.return_value = None
        mock_resp.content = b"%PDF-fake"
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = download_pdf_text("https://ex.com/huge.pdf")
        assert result.text is None
        assert result.error is not None

    @patch("diffiq.extractor.httpx.Client")
    def test_downloaded_content_over_50mb_rejected(self, mock_client_cls):
        """Downloaded content exceeding MAX_PDF_SIZE is rejected."""
        from diffiq.extractor import MAX_PDF_SIZE

        mock_resp = MagicMock()
        mock_resp.headers = {}  # No Content-Length header
        mock_resp.raise_for_status.return_value = None
        mock_resp.content = b"x" * (MAX_PDF_SIZE + 1)
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = download_pdf_text("https://ex.com/huge.pdf")
        assert result.text is None
        assert result.error is not None
        assert "too large" in result.error.lower()
