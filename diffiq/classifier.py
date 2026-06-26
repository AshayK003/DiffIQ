"""Filing type classifier — regex-based subject matching."""

import logging
import re
import sqlite3

from diffiq.db import update_filing_type

logger = logging.getLogger(__name__)

class _FilingClassifier:
    """Filing type classifier with pre-compiled regex patterns."""

    def __init__(self) -> None:
        self._patterns: list[tuple[str, re.Pattern]] = [
            ("AUDIT_REPORT", re.compile(r"\baudit", re.IGNORECASE)),
            (
                "FINANCIAL_RESULT",
                re.compile(
                    r"(?=.*\bresult(?:s)?\b)"
                    r"(?=.*\b(?:quarter(?:ly)?|half\s*year(?:ly)?|annual|standalone|consolidated|financial)\b)",
                    re.IGNORECASE,
                ),
            ),
            ("RPT", re.compile(r"\b(?:related\s*party|rpt)\b", re.IGNORECASE)),
            ("PROMOTER_CHANGE", re.compile(r"\b(?:promoter|pledge|shareholding\s*pattern)\b", re.IGNORECASE)),
            ("BOARD_OUTCOME", re.compile(r"\bboard\b.*\b(?:meeting|outcome|resolution)\b", re.IGNORECASE)),
        ]

    def classify(self, subject: str) -> str:
        """Classify a filing by its subject line.

        Args:
            subject: The filing subject line.

        Returns:
            A filing type string: AUDIT_REPORT, FINANCIAL_RESULT, RPT,
            PROMOTER_CHANGE, BOARD_OUTCOME, or ROUTINE.
        """
        if not subject:
            return "ROUTINE"
        for filing_type, compiled in self._patterns:
            if compiled.search(subject):
                return filing_type
        return "ROUTINE"


_CLASSIFIER = _FilingClassifier()
classify_filing = _CLASSIFIER.classify


def classify_pending_filings(conn: sqlite3.Connection) -> int:
    """Classify all filings where filing_type is NULL.

    Args:
        conn: SQLite connection.

    Returns:
        Number of filing records updated.
    """
    rows = conn.execute(
        "SELECT id, subject FROM filings WHERE filing_type IS NULL"
    ).fetchall()

    count = 0
    for row in rows:
        filing_type = classify_filing(row["subject"] or "")
        update_filing_type(conn, row["id"], filing_type)
        count += 1

    if count:
        conn.commit()
        logger.info("Classified %d pending filings", count)

    return count
