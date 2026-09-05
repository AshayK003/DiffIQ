"""BSE corporate announcements crawler.

Uses the `bse` Python package (https://pypi.org/project/bse/) which wraps
the undocumented BSE API with proper session handling and throttling.
"""

from typing import Any
from urllib.parse import urljoin
from datetime import datetime

import structlog
from bse import BSE
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from diffiq.config import BSE_PDF_BASE, PDF_CACHE_DIR

logger = structlog.get_logger(__name__)


def _parse_filing_date(dt_raw: str) -> str:
    """Normalize a BSE datetime to YYYY-MM-DD; "" when unparseable.

    Accepts ISO datetimes ("2026-06-25T11:02:46.533"), plain YYYY-MM-DD,
    and DD-MM-YYYY. Anything else yields "" (caller skips date ordering
    rather than storing garbage).
    """
    dt_raw = (dt_raw or "").strip()
    if not dt_raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(dt_raw[:26], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _build_pdf_url(attachment_name: str) -> str:
    """Build full PDF URL from BSE attachment filename."""
    if not attachment_name:
        return ""
    return urljoin(BSE_PDF_BASE + "/", attachment_name.lstrip("/"))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, ValueError)),
    reraise=True,
    before_sleep=lambda retry_state: logger.warning(
        "BSE API retry %d for code %s",
        retry_state.attempt_number,
        retry_state.args[0] if retry_state.args else "",
    ),
)
def _raw_fetch_manifest(bse_code: str) -> dict:
    """Inner fetch with retry — wrapped by fetch_manifest for logging."""
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with BSE(download_folder=str(PDF_CACHE_DIR)) as b:
        return b.announcements(scripcode=bse_code, page_no=1)


def fetch_manifest(bse_code: str) -> list[dict[str, Any]]:
    """Fetch corporate announcements for a BSE scrip code.

    Args:
        bse_code: BSE scrip code (e.g. '500295' for VEDL).

    Returns:
        List of announcement dicts with keys:
            filing_uuid: unique BSE filing UUID (NEWSID).
            subject:     announcement headline/description.
            filing_date: date string in YYYY-MM-DD format.
            pdf_url:     full URL to download the PDF (or empty string).
            filing_type: category name from BSE.
        Returns empty list on any failure.
    """
    try:
        data = _raw_fetch_manifest(bse_code)
    except (ConnectionError, TimeoutError, ValueError) as e:
        logger.warning("BSE API error for code %s after retries: %s", bse_code, e)
        return []

    table: list[dict] = data.get("Table", [])
    if not table:
        logger.info("No announcements for BSE code %s", bse_code)
        return []

    filings: list[dict[str, Any]] = []
    for entry in table:
        news_id: str = (entry.get("NEWSID") or "").strip()
        if not news_id:
            continue

        # BSE returns ISO datetime like "2026-06-25T11:02:46.533".
        # Validate — a DD-MM-YYYY or garbage value would silently corrupt
        # ORDER BY filing_date prior-filing selection downstream.
        dt_raw: str = entry.get("DT_TM") or entry.get("NEWS_DT") or ""
        filing_date: str = _parse_filing_date(dt_raw)

        attachment: str = (entry.get("ATTACHMENTNAME") or "").strip()
        subject: str = (entry.get("NEWSSUB") or "").strip()
        category: str = (entry.get("CATEGORYNAME") or "").strip()

        filings.append({
            "filing_uuid": news_id,
            "subject": subject,
            "filing_date": filing_date,
            "pdf_url": _build_pdf_url(attachment) if attachment else "",
            "filing_type": category,
        })

    logger.info(
        "Fetched %d announcements for BSE code %s",
        len(filings),
        bse_code,
    )
    return filings
