"""Regression tests for the Sep 2026 audit fixes (P0/P1/P2)."""

import sqlite3

from diffiq.crawler import _parse_filing_date
from diffiq.classifier import classify_filing
from diffiq.differ import align_sections
from diffiq.db import upsert_stock, insert_filing
from diffiq.extractor import _is_bse_pdf_url, extract_and_store_sections
from diffiq.pipeline import _acquire_pipeline_lock, _release_pipeline_lock


def _file_db(tmp_path):
    import diffiq.schema as schema
    path = str(tmp_path / "t.db")
    conn = schema.init_db(path)
    return conn, path


def test_lock_excludes_second_instance(tmp_path):
    c1, _ = _file_db(tmp_path)
    c2 = sqlite3.connect(str(tmp_path / "t.db"))
    try:
        _acquire_pipeline_lock(c1)
        try:
            _acquire_pipeline_lock(c2)
        except RuntimeError:
            pass
        else:
            raise AssertionError("second instance must be rejected")
        _release_pipeline_lock(c1)
        _acquire_pipeline_lock(c2)  # free again after release
        _release_pipeline_lock(c2)
    finally:
        c1.close()
        c2.close()


def test_lock_steals_stale_holder(tmp_path):
    import sqlite3 as _sql
    c1, _ = _file_db(tmp_path)
    _acquire_pipeline_lock(c1)
    c1.execute("UPDATE _pipeline_lock SET locked_at = '2000-01-01 00:00:00' WHERE id = 1")
    c1.commit()
    c1.close()
    c2 = _sql.connect(str(tmp_path / "t.db"))
    try:
        _acquire_pipeline_lock(c2)  # must steal, not block
        _release_pipeline_lock(c2)
    finally:
        c2.close()


def test_sections_carry_content_hash(db):
    sid = upsert_stock(db, "500209", "Infosys")
    fid = insert_filing(db, sid, "u1", "2026-01-01", "Results", "https://x/y.pdf")
    secs = extract_and_store_sections(db, fid, "HEADER ONE\n\nSome body text here.", "ROUTINE")
    assert secs, "expected sections extracted"
    rows = db.execute("SELECT chunk_hash FROM sections WHERE filing_id = ?", (fid,)).fetchall()
    assert rows and all(r["chunk_hash"] and len(r["chunk_hash"]) == 64 for r in rows)


def test_alignment_uses_text_fallback():
    new = [{"header": "Totally Different Header", "text": "identical body content here"}]
    old = [{"header": "Original Header", "text": "identical body content here"}]
    paired = align_sections(new, old)
    assert paired[0][1] is not None  # text similarity rescues weak header match


def test_generic_headers_stay_case_sensitive():
    from diffiq.extractor import extract_sections
    text = "this is a plain lowercase body line with enough words\nanother ordinary lowercase line here"
    secs = extract_sections(text, None)
    assert len(secs) == 1 and secs[0]["header"] == "Body"


def test_classifier_financial_before_audit():
    assert classify_filing("audit of quarterly results") == "FINANCIAL_RESULT"
    assert classify_filing("Auditor's Report") == "AUDIT_REPORT"
    assert classify_filing("Outcome of the Board meeting") == "BOARD_OUTCOME"
    assert classify_filing("Board Meeting Outcome") == "BOARD_OUTCOME"


def test_filing_date_normalized():
    assert _parse_filing_date("2026-06-25T11:02:46.533") == "2026-06-25"
    assert _parse_filing_date("25-06-2026") == "2026-06-25"
    assert _parse_filing_date("") == ""
    assert _parse_filing_date("garbage") == ""


def test_pdf_url_allowlist():
    assert _is_bse_pdf_url("https://www.bseindia.com/xml-data/x.pdf")
    assert _is_bse_pdf_url("https://bseindia.com/y.pdf")
    assert not _is_bse_pdf_url("http://www.bseindia.com/y.pdf")
    assert not _is_bse_pdf_url("https://evil.com/bseindia.com/x.pdf")
    assert not _is_bse_pdf_url("https://169.254.169.254/x.pdf")
    assert not _is_bse_pdf_url("")
