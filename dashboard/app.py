"""DiffIQ — Streamlit Dashboard."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3

from diffiq.config import STOCKS, DB_PATH
from diffiq.dashboard_utils import status_badge_html
import diffiq.db as db
import importlib
importlib.reload(db)  # Force fresh module on Streamlit hot-reload
from diffiq.schema import SCHEMA_SQL, init_db

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
    """Single DB connection per session — avoids re-init on every rerun.

    check_same_thread=False is required because Streamlit may invoke
    this cached-resource getter from a different thread on rerun.
    The connection is created directly rather than calling init_db() to
    guarantee the parameter is applied regardless of stale .pyc / sys.modules.
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ══════════════════════════════════════════════════════════════════
# Cached data helpers (30s TTL — avoids repeated SQLite hits on rerun)
# ══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def _get_cached_portfolio():
    """Portfolio summary, cached for 30s."""
    conn = get_connection()
    return db.get_portfolio_summary(conn)


@st.cache_data(ttl=30)
def _get_cached_filings(bse_code: str):
    """Filings list per stock by BSE code, cached for 30s.

    Args:
        bse_code: BSE scrip code.

    Returns:
        List of filing dicts, or empty list if stock not found.
    """
    if not bse_code:
        return []
    conn = get_connection()
    row = db.get_stock_by_bse_code(conn, bse_code)
    if not row:
        return []
    return db.get_filings_for_stock(conn, row["id"], limit=50)


# ══════════════════════════════════════════════════════════════════
# Session init — seed watchlist from config on first visit
# ══════════════════════════════════════════════════════════════════
if "db_inited" not in st.session_state:
    _init_conn = init_db(DB_PATH)
    for s in STOCKS:
        bse_code = s.get("bse_code") or s["name"]
        db.upsert_stock(_init_conn, bse_code, s["name"])
    _init_conn.commit()
    _init_conn.close()
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
# Stock Selector (from DB — STOCKS config is seed only)
# ══════════════════════════════════════════════════════════════════
all_stocks = db.get_all_stocks(get_connection())
if not all_stocks:
    st.info("Watchlist is empty. Add stocks using the Manage Watchlist section below.")
    st.stop()

stock_names = [s["name"] for s in all_stocks]
selected_stock = st.selectbox("Select Stock", stock_names, index=0)
stock_data = next(s for s in all_stocks if s["name"] == selected_stock)
bse_code = stock_data["bse_code"]
st.caption(f"BSE Code: {bse_code}")

with st.spinner("Loading filings..."):
    filings = _get_cached_filings(bse_code)

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
    stock_row = db.get_stock_by_bse_code(conn, bse_code)
    stock_id = stock_row["id"] if stock_row else None

    # Batch-fetch sections and diffs for all READY filings at once
    ready_ids = [f["id"] for f in filings if f["status"] == "READY"]
    all_sections = db.get_sections_for_filings(conn, ready_ids) if ready_ids else {}
    all_diffs = (
        db.get_diffs_for_filings(conn, ready_ids, stock_id)
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

st.divider()

# ══════════════════════════════════════════════════════════════════
# Watchlist Management
# ══════════════════════════════════════════════════════════════════
st.subheader("Watchlist Management", divider=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Add Stock**")
    add_name = st.text_input(
        "Symbol", placeholder="e.g. INFY", key="add_name",
    )
    add_bse = st.text_input(
        "BSE Code", placeholder="e.g. 500209", key="add_bse",
    )
    if st.button("Add to Watchlist", type="primary"):
        if add_name and add_bse:
            conn = get_connection()
            db.add_stock(
                conn,
                add_bse.strip(),
                add_name.strip().upper(),
            )
            conn.commit()
            st.rerun()
        else:
            st.warning("Both symbol and BSE code are required.")

with col2:
    st.markdown("**Current Watchlist**")
    conn = get_connection()
    watchlist = db.get_all_stocks(conn)
    if watchlist:
        for s in watchlist:
            c1, c2 = st.columns([3, 1])
            c1.write(f"{s['name']} ({s['bse_code']})")
            if c2.button("Remove", key=f"rm_{s['id']}"):
                db.remove_stock(conn, s["id"])
                conn.commit()
                st.rerun()
    else:
        st.write("No stocks in watchlist.")

st.caption(
    "Data source: BSE Corporate Announcements API. "
    "Run `python -m diffiq.pipeline` to fetch new filings."
)
