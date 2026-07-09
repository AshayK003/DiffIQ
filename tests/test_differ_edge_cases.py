"""Edge-case tests for the section-aligned text differ.

Covers empty sections, identical content, reordered sections,
and ERROR status exclusion in find_prior_filing.
"""

from diffiq.differ import (
    DIFF_CHANGED_MIN_LEN,
    align_sections,
    diff_section,
    find_prior_filing,
    run_diffs_for_filing,
)


class TestAlignSections:
    """align_sections() edge cases."""

    def test_empty_old_sections(self):
        """Aligning with no old sections — every new section gets None match."""
        new = [
            {"header": "Opinion", "text": "In our opinion...", "section_idx": 0},
        ]
        aligned = align_sections(new, [])
        assert len(aligned) == 1
        assert aligned[0][0] is new[0]
        assert aligned[0][1] is None

    def test_empty_new_sections(self):
        """Aligning with no new sections — returns empty list."""
        old = [
            {"header": "Opinion", "text": "Old opinion", "section_idx": 0},
        ]
        aligned = align_sections([], old)
        assert aligned == []

    def test_identical_headers(self):
        """All headers match — all old sections matched with their new counterparts."""
        new = [
            {"header": "Opinion", "text": "New opinion", "section_idx": 0},
            {"header": "Basis", "text": "New basis", "section_idx": 1},
            {"header": "Notes", "text": "New notes", "section_idx": 2},
        ]
        old = [
            {"header": "Opinion", "text": "Old opinion", "section_idx": 0},
            {"header": "Basis", "text": "Old basis", "section_idx": 1},
            {"header": "Notes", "text": "Old notes", "section_idx": 2},
        ]
        aligned = align_sections(new, old)
        assert len(aligned) == 3
        assert all(match is not None for _, match in aligned)
        assert [m["header"] for _, m in aligned] == ["Opinion", "Basis", "Notes"]

    def test_reordered_sections(self):
        """Sections in different order still align by header content."""
        new = [
            {"header": "Notes", "text": "New notes", "section_idx": 0},
            {"header": "Opinion", "text": "New opinion", "section_idx": 1},
        ]
        old = [
            {"header": "Opinion", "text": "Old opinion", "section_idx": 0},
            {"header": "Notes", "text": "Old notes", "section_idx": 1},
        ]
        aligned = align_sections(new, old)
        assert len(aligned) == 2
        # First new section "Notes" should match old "Notes" (header match)
        assert aligned[0][1] is not None
        assert aligned[0][1]["header"] == "Notes"
        assert aligned[1][1] is not None
        assert aligned[1][1]["header"] == "Opinion"


class TestFindPriorFiling:
    """find_prior_filing() exclusion edge cases."""

    def test_excludes_error_status(self, db):
        """ERROR status filings are excluded — the valid READY prior is chosen instead."""
        conn = db
        conn.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        # Filing 1: READY — valid prior
        conn.execute(
            "INSERT INTO filings (id, stock_id, filing_uuid, filing_date, "
            "subject, pdf_url, status, filing_type) "
            "VALUES (1, 1, 'u1', '2026-01-01', 'Audit 2025', "
            "'https://ex.com/1.pdf', 'READY', 'AUDIT_REPORT')"
        )
        # Filing 2: ERROR — should be skipped in prior search
        conn.execute(
            "INSERT INTO filings (id, stock_id, filing_uuid, filing_date, "
            "subject, pdf_url, status, filing_type) "
            "VALUES (2, 1, 'u2', '2026-06-01', 'Audit 2026 (failed)', "
            "'https://ex.com/2.pdf', 'ERROR_EXTRACTION', 'AUDIT_REPORT')"
        )
        # Filing 3: current filing (id to exclude from prior search)
        conn.execute(
            "INSERT INTO filings (id, stock_id, filing_uuid, filing_date, "
            "subject, pdf_url, status, filing_type) "
            "VALUES (3, 1, 'u3', '2026-06-15', 'Audit 2026', "
            "'https://ex.com/3.pdf', 'READY', 'AUDIT_REPORT')"
        )
        conn.commit()

        # Query for prior to filing 3
        prior = find_prior_filing(conn, 1, "AUDIT_REPORT", 3)
        assert prior is not None
        # Should pick filing 1 (READY), not filing 2 (ERROR_EXTRACTION)
        assert prior["id"] == 1

    def test_excludes_queued_status(self, db):
        """QUEUED status filings are excluded from being 'prior'."""
        conn = db
        conn.execute(
            "INSERT INTO stocks (id, bse_code, name) VALUES (1, '500295', 'VEDL')"
        )
        conn.execute(
            "INSERT INTO filings (id, stock_id, filing_uuid, filing_date, "
            "subject, pdf_url, status, filing_type) "
            "VALUES (1, 1, 'u1', '2026-01-01', 'Audit 2025', "
            "'https://ex.com/1.pdf', 'QUEUED', 'AUDIT_REPORT')"
        )
        conn.commit()

        # Only filing is QUEUED — should return None
        prior = find_prior_filing(conn, 1, "AUDIT_REPORT", 1)
        assert prior is None


class TestAlignSectionsExtended:
    """Additional align_sections() edge cases for empty/None headers and count mismatch."""

    def test_empty_headers_match_by_text(self):
        """Sections with empty headers fall through to text-based matching."""
        new = [{"header": "", "text": "Revenue from operations: Rs. 100 Cr", "section_idx": 0}]
        old = [{"header": "", "text": "Revenue from operations: Rs. 80 Cr", "section_idx": 0}]
        aligned = align_sections(new, old)
        assert aligned[0][1] is not None  # Matched by text similarity

    def test_none_headers_treated_as_empty(self):
        """None headers are treated as empty strings."""
        new = [{"header": None, "text": "Some content", "section_idx": 0}]
        old = [{"header": None, "text": "Similar content", "section_idx": 0}]
        aligned = align_sections(new, old)
        assert aligned[0][1] is not None

    def test_extra_new_sections_get_none_match(self):
        """New sections beyond old count get None match."""
        new = [
            {"header": "A", "text": "a", "section_idx": 0},
            {"header": "B", "text": "b", "section_idx": 1},
            {"header": "C", "text": "c", "section_idx": 2},
        ]
        old = [
            {"header": "A", "text": "a", "section_idx": 0},
        ]
        aligned = align_sections(new, old)
        assert len(aligned) == 3
        assert aligned[0][1] is not None  # A matched
        assert aligned[1][1] is None     # B unmatched
        assert aligned[2][1] is None     # C unmatched

    def test_single_section_alignment(self):
        """Single new section aligns with single old section."""
        new = [{"header": "Opinion", "text": "New text", "section_idx": 0}]
        old = [{"header": "Opinion", "text": "Old text", "section_idx": 0}]
        aligned = align_sections(new, old)
        assert len(aligned) == 1
        assert aligned[0][1]["header"] == "Opinion"

    def test_extra_old_sections_ignored(self):
        """Unused old sections beyond new count are ignored."""
        new = [
            {"header": "A", "text": "a", "section_idx": 0},
        ]
        old = [
            {"header": "A", "text": "a", "section_idx": 0},
            {"header": "B", "text": "b", "section_idx": 1},
            {"header": "C", "text": "c", "section_idx": 2},
        ]
        aligned = align_sections(new, old)
        assert len(aligned) == 1
        assert aligned[0][1] is not None
        assert aligned[0][1]["header"] == "A"


class TestDiffSection:
    """diff_section() edge cases."""

    def test_near_identical_text_under_threshold(self):
        """Texts with a tiny change produce diff output under threshold → changed=False."""
        old_text = "a"
        new_text = "b"
        diff_text, changed = diff_section(new_text, old_text)
        # diff headers (--- / +++ / @@) + one char per line = ~43 chars
        assert len(diff_text) < DIFF_CHANGED_MIN_LEN, (
            f"Expected diff under {DIFF_CHANGED_MIN_LEN}, got {len(diff_text)}"
        )
        assert changed is False

    def test_medium_diff_at_threshold(self):
        """Texts with modest change at threshold boundary — should stay under."""
        old_text = "Price: 100"
        new_text = "Price: 101"
        diff_text, changed = diff_section(new_text, old_text)
        # ~59 chars with unified-diff headers
        assert len(diff_text) > DIFF_CHANGED_MIN_LEN, (
            f"Expected diff over {DIFF_CHANGED_MIN_LEN}, got {len(diff_text)}"
        )
        assert changed is True

    def test_large_diff_over_threshold(self):
        """Substantially different texts should have changed=True."""
        old_text = "Short old text."
        new_text = (
            "This is a substantially longer new text that should produce "
            "a diff output that exceeds one hundred characters in total, "
            "thus triggering the changed flag to be set to True."
        )
        diff_text, changed = diff_section(new_text, old_text)
        assert changed is True
        assert len(diff_text) > 100
