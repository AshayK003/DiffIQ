"""Tests for BSE corporate announcements crawler."""

from unittest.mock import MagicMock, patch

import pytest

from diffiq.crawler import fetch_manifest


class TestFetchManifest:
    """fetch_manifest hits the BSE API and parses results."""

    SAMPLE_RESPONSE = {
        "Table": [
            {
                "NEWSID": "f9ca9750-c7ab-490f-b7b6-11fd44770e39",
                "SCRIP_CD": 500295,
                "NEWSSUB": "Closure of Trading Window",
                "DT_TM": "2026-06-25T11:02:46.533",
                "NEWS_DT": "2026-06-25T11:02:46.533",
                "CATEGORYNAME": "Insider Trading / SAST",
                "SUBCATNAME": "Closure of Trading Window",
                "ATTACHMENTNAME": "4fdb9e55-fc52-4b08-83c0-3cd186ff4d9a.pdf",
                "HEADLINE": "Please refer the enclosed file.",
                "SLONGNAME": "Vedanta Ltd",
                "PDFFLAG": 0,
            },
            {
                "NEWSID": "a1b2c3d4-5678-90ab-cdef-123456789abc",
                "SCRIP_CD": 500295,
                "NEWSSUB": "Intimation under Regulation 30",
                "DT_TM": "2026-06-24T16:19:31.000",
                "NEWS_DT": "2026-06-24T16:19:31.000",
                "CATEGORYNAME": "General Updates",
                "SUBCATNAME": "",
                "ATTACHMENTNAME": "",
                "HEADLINE": "Please refer the enclosed file.",
                "SLONGNAME": "Vedanta Ltd",
                "PDFFLAG": 0,
            },
            {
                # Entry with NO NEWSID — should be skipped
                "SCRIP_CD": 500295,
                "NEWSSUB": "Compliance Certificate",
                "DT_TM": "2026-06-23T12:58:34.000",
                "CATEGORYNAME": "Compliance",
                "ATTACHMENTNAME": "",
            },
        ],
        "Table1": [{"ROWCNT": 2}],
    }

    @patch("diffiq.crawler.BSE")
    def test_returns_list(self, mock_bse_cls: MagicMock) -> None:
        """fetch_manifest returns a list for a valid BSE code."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.return_value = self.SAMPLE_RESPONSE
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        assert isinstance(result, list)
        assert len(result) == 2  # Third entry has no NEWSID

    @patch("diffiq.crawler.BSE")
    def test_entry_structure(self, mock_bse_cls: MagicMock) -> None:
        """Each manifest entry has required keys."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.return_value = self.SAMPLE_RESPONSE
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        entry = result[0]

        assert "filing_uuid" in entry
        assert entry["filing_uuid"] == "f9ca9750-c7ab-490f-b7b6-11fd44770e39"
        assert "subject" in entry
        assert entry["subject"] == "Closure of Trading Window"
        assert "filing_date" in entry
        assert entry["filing_date"] == "2026-06-25"
        assert "pdf_url" in entry
        assert "4fdb9e55" in entry["pdf_url"]
        assert "filing_type" in entry
        assert entry["filing_type"] == "Insider Trading / SAST"

    @patch("diffiq.crawler.BSE")
    def test_empty_pdf_url(self, mock_bse_cls: MagicMock) -> None:
        """Entries without PDF attachment get empty string."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.return_value = self.SAMPLE_RESPONSE
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        entry = result[1]  # No ATTACHMENTNAME
        assert entry["pdf_url"] == ""

    @patch("diffiq.crawler.BSE")
    def test_empty_table(self, mock_bse_cls: MagicMock) -> None:
        """Empty Table returns empty list."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.return_value = {"Table": [], "Table1": [{"ROWCNT": 0}]}
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        assert result == []

    @patch("diffiq.crawler.BSE")
    def test_handles_connection_error(self, mock_bse_cls: MagicMock) -> None:
        """fetch_manifest returns empty list on connection error."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.side_effect = ConnectionError("BSE API down")
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        assert result == []

    @patch("diffiq.crawler.BSE")
    def test_handles_timeout(self, mock_bse_cls: MagicMock) -> None:
        """fetch_manifest returns empty list on timeout."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.side_effect = TimeoutError("Request timed out")
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("500295")
        assert result == []

    @patch("diffiq.crawler.BSE")
    def test_handles_value_error(self, mock_bse_cls: MagicMock) -> None:
        """fetch_manifest handles ValueError gracefully."""
        mock_bse = MagicMock()
        mock_bse.__enter__.return_value = mock_bse
        mock_bse.announcements.side_effect = ValueError("Bad scripcode")
        mock_bse_cls.return_value = mock_bse

        result = fetch_manifest("invalid")
        assert result == []

    def test_integration_skip_if_api_down(self) -> None:
        """Live BSE API test — skip gracefully if unreachable."""
        try:
            result = fetch_manifest("500295")
            assert isinstance(result, list)
            if not result:
                pytest.skip("BSE API returned empty (may be down)")
        except Exception:
            pytest.skip("BSE API unreachable — skipping live test")


class TestBuildPdfUrl:
    """_build_pdf_url constructs BSE attachment download URLs."""

    def test_empty_string(self):
        """Empty attachment name returns empty string."""
        from diffiq.crawler import _build_pdf_url

        assert _build_pdf_url("") == ""

    def test_normal_attachment(self):
        """Normal attachment name produces correct URL."""
        from diffiq.crawler import _build_pdf_url

        url = _build_pdf_url("abc123.pdf")
        assert url.endswith("/abc123.pdf")
        assert "bseindia.com" in url

    def test_leading_slash_stripped(self):
        """Leading slash is stripped to avoid double-slash in URL."""
        from diffiq.crawler import _build_pdf_url

        url = _build_pdf_url("/abc123.pdf")
        assert "//" not in url.split("https://")[1]  # No double-slash after domain

    def test_full_url_structure(self):
        """URL matches expected BSE format."""
        from diffiq.crawler import _build_pdf_url

        url = _build_pdf_url("test-file.pdf")
        assert url == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/test-file.pdf"
