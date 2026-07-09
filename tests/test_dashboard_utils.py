"""Tests for dashboard utility functions — extracted from Streamlit for testability."""

from diffiq.dashboard_utils import status_badge_html


class TestStatusBadgeHtml:
    """status_badge_html() returns correct CSS classes and labels."""

    def test_ready(self):
        html = status_badge_html("READY")
        assert 'class="badge badge-ready"' in html
        assert "Ready" in html

    def test_queued(self):
        html = status_badge_html("QUEUED")
        assert 'class="badge badge-queued"' in html
        assert "Queued" in html

    def test_downloading(self):
        html = status_badge_html("DOWNLOADING")
        assert 'class="badge badge-downloading"' in html
        assert "Downloading" in html

    def test_no_pdf(self):
        html = status_badge_html("NO_PDF")
        assert 'class="badge badge-no-pdf"' in html
        assert "No PDF" in html

    def test_error_generic(self):
        html = status_badge_html("ERROR_UNKNOWN")
        assert 'class="badge badge-error"' in html
        assert "Error" in html

    def test_error_extraction(self):
        html = status_badge_html("ERROR_EXTRACTION")
        assert 'class="badge badge-error"' in html
        assert "Error" in html

    def test_error_download(self):
        html = status_badge_html("ERROR_DOWNLOAD")
        assert 'class="badge badge-error"' in html
        assert "Error" in html

    def test_unknown_status_falls_back_to_error(self):
        """An unrecognized status gets 'error' CSS class and passes status as label."""
        html = status_badge_html("SOME_WEIRD_STATUS")
        assert 'class="badge badge-error"' in html
        # Falls through to return the status itself as label
        assert "SOME_WEIRD_STATUS" in html


class TestStatusBadgeHtmlEdgeCases:
    """Edge cases for status_badge_html that can cause ugly dashboard rendering."""

    def test_empty_string(self):
        """Empty status string doesn't crash."""
        html = status_badge_html("")
        assert isinstance(html, str)
        assert "badge" in html

    def test_downloading_label(self):
        """DOWNLOADING status shows 'Downloading' label, not raw string."""
        html = status_badge_html("DOWNLOADING")
        assert "Downloading" in html
        assert "DOWNLOADING" not in html

    def test_nested_error_status(self):
        """Deeply nested error status maps to error badge."""
        html = status_badge_html("ERROR_EXTRACTION_TIMEOUT")
        assert "badge-error" in html

    def test_mixed_case_ready(self):
        """Mixed case status is normalized correctly."""
        html = status_badge_html("Ready")
        assert "badge-ready" in html
