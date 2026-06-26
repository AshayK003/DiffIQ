"""DiffIQ — Streamlit Dashboard (P1)."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diffiq.config import STOCKS, DB_PATH
from diffiq.dashboard_utils import status_badge_html
from diffiq.db import (
    get_diffs_for_filings,
    get_filings_for_stock,
    get_portfolio_summary,
    get_sections_for_filings,
    get_stock_by_bse_code,
    upsert_stock,
)
from diffiq.schema import init_db

st.set_page_config(
    page_title="DiffIQ Corporate Filing Monitor",
    page_icon="📄",
    layout="centered",
)

# ══════════════════════════════════════════════════════════════════
# Cached connection
# ══════════════════════════════════════════════════════════════════
@st.cache_resource
def get_connection():
    """Single DB connection per session — avoids re-init on every rerun."""
    return init_db(DB_PATH)


# ══════════════════════════════════════════════════════════════════
# Cached data helpers (30s TTL — avoids repeated SQLite hits on rerun)
# ══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _get_cached_portfolio():
    """Portfolio summary, cached for 30s."""
    conn = get_connection()
    return get_portfolio_summary(conn)


@st.cache_data(ttl=30)
def _get_cached_filings(stock_name: str, bse_code_for_cache: str):
    """Filings list per stock, cached for 30s.

    Args:
        stock_name: Stock name as displayed in selectbox.
        bse_code_for_cache: BSE code used as cache key discriminator
            (ensures cache invalidates across stocks).

    Returns:
        List of filing dicts, or empty list if stock not found.
    """
    stock = next((s for s in STOCKS if s["name"] == stock_name), None)
    if not stock:
        return []
    conn = get_connection()
    bse_code = stock.get("bse_code") or stock["name"]
    row = get_stock_by_bse_code(conn, bse_code)
    if not row:
        return []
    return get_filings_for_stock(conn, row["id"], limit=50)


@st.cache_data(ttl=30)
def _get_cached_stock_data(stock_name: str):
    """Stock data dict by name, cached for 30s."""
    return next((s for s in STOCKS if s["name"] == stock_name), None)


# ══════════════════════════════════════════════════════════════════
# Session init
# ══════════════════════════════════════════════════════════════════
if "db_inited" not in st.session_state:
    conn = get_connection()
    for s in STOCKS:
        bse_code = s.get("bse_code") or s["name"]
        upsert_stock(conn, bse_code, s["name"])
    conn.commit()
    st.session_state["db_inited"] = True

# ══════════════════════════════════════════════════════════════════
# Header
# ══════════════════════════════════════════════════════════════════
st.markdown(
    '<div class="main-header">'
    '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 '
    '2-2V7.5L14.5 2z"/>'
    '<polyline points="14 2 14 8 20 8"/>'
    '<line x1="16" y1="13" x2="8" y2="13"/>'
    '<line x1="16" y1="17" x2="8" y2="17"/>'
    '</svg>'
    '<h1 style="margin:0;font-size:1.8rem;font-weight:600;">'
    'DiffIQ &middot; Corporate Filing Monitor</h1></div>',
    unsafe_allow_html=True,
)
st.caption("Tracks BSE-listed portfolio stock filings.")

# ══════════════════════════════════════════════════════════════════
# Portfolio Overview
# ══════════════════════════════════════════════════════════════════
st.subheader("Portfolio Overview")

with st.spinner("Loading portfolio..."):
    summary = _get_cached_portfolio()

if summary:
    for i in range(0, len(summary), 4):
        row_stocks = summary[i:i + 4]
        cols = st.columns(4)
        for j, stock in enumerate(row_stocks):
            with cols[j]:
                st.markdown(
                    f'<div class="stock-card">'
                    f'<div class="stock-card-name">{stock["name"]}</div>'
                    f'<div class="stock-card-code">{stock["bse_code"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.metric("Total Filings", stock["total_filings"])
                inner = st.columns(2)
                inner[0].metric("Ready", stock["ready_count"])
                inner[1].metric("Errors", stock["error_count"])
                if stock["latest_filing_date"]:
                    st.caption(f"Latest: {stock['latest_filing_date']}")
else:
    st.info("No corporate stocks found.")

st.divider()

# ══════════════════════════════════════════════════════════════════
# Stock Selector
# ══════════════════════════════════════════════════════════════════
stock_names = [s["name"] for s in STOCKS]
selected_stock = st.selectbox("Select Stock", stock_names, index=0)

stock_data = next(s for s in STOCKS if s["name"] == selected_stock)
bse_code = stock_data.get("bse_code") or "-"
st.caption(f"BSE Code: {bse_code}")

with st.spinner("Loading filings..."):
    bse_cache_key = stock_data.get("bse_code") or stock_data["name"]
    filings = _get_cached_filings(selected_stock, bse_cache_key)

# ══════════════════════════════════════════════════════════════════
# Filing Summary Metrics
# ══════════════════════════════════════════════════════════════════
if filings:
    total = len(filings)
    ready_count = sum(1 for f in filings if f["status"] == "READY")
    error_count = sum(1 for f in filings if f["status"].startswith("ERROR"))
    pending_count = sum(1 for f in filings if f["status"] == "QUEUED")

    cols = st.columns(4)
    cols[0].metric("Total Filings", total)
    cols[1].metric("Ready", ready_count)
    cols[2].metric("Pending", pending_count)
    cols[3].metric("Errors", error_count)
else:
    has_bse = bool(stock_data.get("bse_code"))
    if not has_bse:
        st.info(f"**{selected_stock}** is an ETF — no corporate filings to track.")
    else:
        st.info(
            "No filings yet. Run the pipeline first:\n\n"
            "`python -m diffiq.pipeline`"
        )

st.divider()

# ══════════════════════════════════════════════════════════════════
# Filing Expanders — with batch section/diff queries
# ══════════════════════════════════════════════════════════════════
if filings:
    conn = get_connection()
    stock_row = get_stock_by_bse_code(conn, bse_code)
    stock_id = stock_row["id"] if stock_row else None

    # Batch-fetch sections and diffs for all READY filings at once
    ready_ids = [f["id"] for f in filings if f["status"] == "READY"]
    all_sections = get_sections_for_filings(conn, ready_ids) if ready_ids else {}
    all_diffs = (
        get_diffs_for_filings(conn, ready_ids, stock_id)
        if ready_ids and stock_id
        else {}
    )

    for f in filings:
        fid = f["id"]
        subject = f.get("subject", "") or ""
        status = f["status"]

        with st.expander(
            f"{f['filing_date']} | {subject[:72]}"
            f"{'...' if len(subject) > 72 else ''}",
            expanded=False,
        ):
            # Filing metadata row
            meta = st.columns([1.2, 1.2, 1, 0.8])
            meta[0].markdown(f"**Type:** {f.get('filing_type') or '-'}")
            meta[1].markdown(
                f"**Status:** {status_badge_html(status)}",
                unsafe_allow_html=True,
            )
            meta[2].markdown(f"**ID:** {fid}")
            meta[3].markdown(f"[PDF]({f.get('pdf_url', '')})")

            if f.get("error"):
                st.error(f"Error: {f['error']}")

            # Sections with diffs (uses pre-fetched batch data)
            if status == "READY":
                sections = all_sections.get(fid, [])
                if sections:
                    st.markdown(f"**Sections ({len(sections)})**")

                    diffs_by_header: dict = {}
                    if stock_id and fid in all_diffs:
                        for d in all_diffs[fid]:
                            diffs_by_header[d["section_header"]] = d

                    for sec in sections:
                        header = sec["header"]
                        sec_text = sec.get("text", "")
                        has_diff = (
                            header in diffs_by_header
                            and diffs_by_header[header].get("changed")
                        )

                        with st.expander(
                            f"**{header}**",
                            expanded=bool(has_diff),
                        ):
                            if has_diff:
                                st.markdown(
                                    '<span class="diff-badge">'
                                    '<svg xmlns="http://www.w3.org/2000/svg" '
                                    'width="12" height="12" viewBox="0 0 24 24" '
                                    'fill="none" stroke="currentColor" '
                                    'stroke-width="2" stroke-linecap="round" '
                                    'stroke-linejoin="round">'
                                    '<path d="M12 3v18"/>'
                                    '<path d="M9 6l3-3 3 3"/>'
                                    '<path d="M9 18l3 3 3-3"/>'
                                    "</svg> Changed</span>",
                                    unsafe_allow_html=True,
                                )

                            preview = sec_text[:500]
                            st.text(preview + ("..." if len(sec_text) > 500 else ""))

                            if has_diff:
                                st.code(
                                    diffs_by_header[header].get("diff_text", "")[:2000],
                                    language="diff",
                                )

st.caption(
    "Data source: BSE Corporate Announcements API. "
    "Run `python -m diffiq.pipeline` to fetch new filings."
)
