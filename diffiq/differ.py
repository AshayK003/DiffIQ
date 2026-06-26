"""Section-aligned text differ — compares sections against prior filings."""

import difflib
import logging
import sqlite3
from typing import Any

from diffiq.db import (
    get_last_filing_of_type,
    get_sections,
    insert_diff,
)

logger = logging.getLogger(__name__)

ALIGNMENT_THRESHOLD: float = 0.6
# Minimum diff output length to flag as "changed". Unified-diff headers alone
# account for ~50 chars, so thresholds below 30 risk flagging whitespace noise.
# This threshold only controls visual prominence (the "Changed" badge in the
# UI); the full diff text is always stored in the database.
DIFF_CHANGED_MIN_LEN: int = 50


def find_prior_filing(
    conn: sqlite3.Connection,
    stock_id: int,
    filing_type: str,
    current_filing_id: int,
) -> dict[str, Any] | None:
    """Find the most recent same-type filing for a stock, excluding current.

    Delegates to get_last_filing_of_type with the exclude_id parameter.

    Args:
        conn: SQLite connection.
        stock_id: Stock ID.
        filing_type: Filing type string.
        current_filing_id: Exclude this filing ID.

    Returns:
        Prior filing dict or None if none found.
    """
    return get_last_filing_of_type(
        conn, stock_id, filing_type, exclude_id=current_filing_id,
    )

def align_sections(
    new_sections: list[dict[str, Any]],
    old_sections: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Align new sections to old sections by header/text similarity.

    For each new section, finds the best-matching old section using
    difflib.SequenceMatcher. Matching is attempted on header first,
    then on the first 200 characters of text.

    Args:
        new_sections: Sections from the new filing.
        old_sections: Sections from the prior filing.

    Returns:
        List of (new_section, old_section_or_None) aligned pairs.
    """
    aligned: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    used_old_indices: set[int] = set()

    for new_sec in new_sections:
        best_match: dict[str, Any] | None = None
        best_ratio: float = 0.0

        for idx, old_sec in enumerate(old_sections):
            if idx in used_old_indices:
                continue

            header_ratio = difflib.SequenceMatcher(
                None,
                (new_sec.get("header") or "").lower(),
                (old_sec.get("header") or "").lower(),
            ).ratio()

            text_ratio = 0.0
            if header_ratio > 0:
                text_ratio = header_ratio
            elif (new_sec.get("text") or "") and (old_sec.get("text") or ""):
                text_ratio = difflib.SequenceMatcher(
                    None,
                    (new_sec["text"] or "")[:200].lower(),
                    (old_sec["text"] or "")[:200].lower(),
                ).ratio()

            combined = max(header_ratio, text_ratio)
            if combined > best_ratio:
                best_ratio = combined
                best_match = old_sec
                best_match_idx = idx

        if best_match and best_ratio >= ALIGNMENT_THRESHOLD:
            aligned.append((new_sec, best_match))
            used_old_indices.add(best_match_idx)
        else:
            aligned.append((new_sec, None))

    return aligned


def diff_section(new_text: str, old_text: str) -> tuple[str, bool]:
    """Generate a unified diff between two section texts.

    Args:
        new_text: Text from the new filing.
        old_text: Text from the prior filing.

    Returns:
        Tuple of (diff_text_string, changed_boolean).
        changed is True when diff output exceeds DIFF_CHANGED_MIN_LEN characters.
    """
    new_lines = (new_text or "").splitlines(keepends=True)
    old_lines = (old_text or "").splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="previous",
            tofile="current",
            lineterm="\n",
        )
    )

    diff_text = "".join(diff_lines)
    changed = len(diff_text) > DIFF_CHANGED_MIN_LEN
    return diff_text, changed


def run_diffs_for_filing(
    conn: sqlite3.Connection,
    filing_id: int,
    stock_id: int,
    filing_type: str,
) -> int:
    """Run diffs for a filing against its most recent same-type predecessor.

    Orchestrates finding prior filing, aligning sections, generating diffs,
    and storing results.

    Args:
        conn: SQLite connection.
        filing_id: Current filing ID.
        stock_id: Stock ID.
        filing_type: Filing type string.

    Returns:
        Number of sections that changed.
    """
    prior = find_prior_filing(conn, stock_id, filing_type, filing_id)
    if prior is None:
        logger.info("No prior filing for type %s — skipping diff", filing_type)
        return 0

    new_sections = get_sections(conn, filing_id)
    old_sections = get_sections(conn, prior["id"])

    if not new_sections:
        logger.info("No sections for filing %d — skipping diff", filing_id)
        return 0

    aligned = align_sections(new_sections, old_sections)
    changed_count = 0

    for new_sec, old_sec in aligned:
        old_text = (old_sec or {}).get("text", "") if old_sec else ""
        diff_text, changed = diff_section(
            new_sec.get("text", ""), old_text
        )

        # New sections with no prior match get a placeholder diff
        if old_sec is None:
            diff_text = diff_text or "[New section — no equivalent in prior filing]"
            changed = True

        diff_data = {
            "stock_id": stock_id,
            "filing_id_new": filing_id,
            "section_id_new": new_sec.get("id") or 0,
            "section_header": new_sec.get("header", ""),
            "diff_text": diff_text,
            "changed": 1 if changed else 0,
        }

        if old_sec:
            diff_data["filing_id_old"] = prior["id"]
            diff_data["section_id_old"] = old_sec.get("id") or 0

        insert_diff(conn, diff_data)

        if changed:
            changed_count += 1

    logger.info(
        "Filed %d diffs (%d changed) for filing %d",
        len(aligned),
        changed_count,
        filing_id,
    )
    return changed_count
