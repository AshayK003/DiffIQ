"""DiffIQ — Streamlit Dashboard (P1)."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diffiq.config import STOCKS, DB_PATH
from diffiq.db import (
    get_diffs_for_filing,
    get_filings_for_stock,
    get_portfolio_summary,
    get_sections,
    get_stock_by_bse_code,
    upsert_stock,
)
from diffiq.schema import init_db

st.set_page_config(
    page_title="DiffIQ Corporate Filing Monitor",
    page_icon="📄",
    layout="centered",
)

# ── CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Stock cards */
.stock-card { border:1px solid #EAEAEA; border-radius:8px; padding:16px;
    text-align:center; background:#F9F9F8; margin-bottom:4px; }
.stock-card-name { font-weight:600; font-size:1rem; }
.stock-card-code { color:#888; font-size:0.8rem; }

/* Status badges */
.badge { display:inline-block; padding:2px 10px; border-radius:9999px;
    font-size:0.75rem; font-weight:600; white-space:nowrap; }
.badge-ready { background:#EDF3EC; color:#346538; }
.badge-error { background:#FDEBEC; color:#9F2F2D; }
.badge-queued { background:#FBF3DB; color:#956400; }
.badge-no-pdf { background:#F0F0F0; color:#666; }
.badge-downloading { background:#E1F3FE; color:#1F6C9F; }

/* Section diff badge */
.diff-badge { display:inline-flex; align-items:center; gap:4px;
    background:#EDF3EC; color:#346538; padding:2px 10px;
    border-radius:9999px; font-size:0.75rem; font-weight:600; }

/* Header */
.main-header { display:flex; align-items:center; gap:10px; margin-bottom:0; }
</style>""", unsafe_allow_html=True)

# ── Cached Connection ──────────────────────────────────────────
@st.cache_resource
def get_connection():
    """Single DB connection per session — avoids re-init on every rerun."""
    return init_db(DB_PATH)


# ── Session init ────────────────────────────────────────────────
if "db_inited" not in st.session_state:
    conn = get_connection()
    for s in STOCKS:
        bse_code = s.get("bse_code") or s["symbol"]
        upsert_stock(conn, bse_code, s["name"])
    conn.commit()  # pipeline owns transactions
    st.session_state["db_inited"] = True

# ── Header (Lucide file-text SVG, no em-dash) ──────────────────
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

# ── Portfolio Overview ──────────────────────────────────────────
st.subheader("Portfolio Overview")

with st.spinner("Loading portfolio..."):
    conn = get_connection()
    summary = get_portfolio_summary(conn)

if summary:
    for i in range(0, len(summary), 4):
        row = summary[i:i + 4]
        cols = st.columns(4)
        for j, stock in enumerate(row):
            with cols[j]:
                total = stock["total_filings"]
                ready = stock["ready_count"]
                errors = stock["error_count"]

                st.markdown(
                    f'<div class="stock-card">'
                    f'<div class="stock-card-name">{stock["name"]}</div>'
                    f'<div class="stock-card-code">{stock["bse_code"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.metric("Total Filings", total)
                inner = st.columns(2)
                inner[0].metric("Ready", ready)
                inner[1].metric("Errors", errors)
                if stock["latest_filing_date"]:
                    st.caption(f"Latest: {stock['latest_filing_date']}")
else:
    st.info("No corporate stocks found.")

st.divider()

# ── Helpers ─────────────────────────────────────────────────────
def load_filings(stock_name: str) -> list[dict]:
    """Fetch filings for a stock using the cached connection."""
    stock = next((s for s in STOCKS if s["name"] == stock_name), None)
    if not stock:
        return []
    conn = get_connection()
    bse_code = stock.get("bse_code") or stock["symbol"]
    row = get_stock_by_bse_code(conn, bse_code)
    if not row:
        return []
    return get_filings_for_stock(conn, row["id"], limit=50)


def status_badge_html(status: str) -> str:
    """Render a color-coded status badge span.

    Maps status strings to muted-pastel badges matching the minimalist
    colour palette: green (ready), red (error), amber (queued), gray (no-pdf),
    blue (downloading).
    """
    if status.startswith("ERROR_"):
        return '<span class="badge badge-error">Error</span>'
    css = status.lower().replace("_", "-")
    labels = {
        "ready": "Ready",
        "queued": "Queued",
        "no-pdf": "No PDF",
        "downloading": "Downloading",
    }
    label = labels.get(css, status)
    known = {"ready", "error", "queued", "no-pdf", "downloading"}
    css_class = css if css in known else "error"
    return f'<span class="badge badge-{css_class}">{label}</span>'


# ── Stock Selector ──────────────────────────────────────────────
stock_names = [s["name"] for s in STOCKS]
selected_stock = st.selectbox("Select Stock", stock_names, index=0)

stock_data = next(s for s in STOCKS if s["name"] == selected_stock)
bse_code = stock_data.get("bse_code") or "-"
st.caption(f"BSE Code: {bse_code}")

with st.spinner("Loading filings..."):
    filings = load_filings(selected_stock)

# ── Filing Summary Metrics ──────────────────────────────────────
if filings:
    total = len(filings)
    ready = sum(1 for f in filings if f["status"] == "READY")
    errors = sum(1 for f in filings if f["status"].startswith("ERROR"))
    pending = sum(1 for f in filings if f["status"] == "QUEUED")

    cols = st.columns(4)
    cols[0].metric("Total Filings", total)
    cols[1].metric("Ready", ready)
    cols[2].metric("Pending", pending)
    cols[3].metric("Errors", errors)
else:
    has_bse = bool(stock_data.get("bse_code"))
    if not has_bse:
        st.info(f"**{selected_stock}** is an ETF - no corporate filings to track.")
    else:
        st.info(
            "No filings yet. Run the pipeline first:\n\n"
            "`python -m diffiq.pipeline`"
        )

st.divider()

# ── Filing Expanders ────────────────────────────────────────────
if filings:
    conn = get_connection()
    stock_row = get_stock_by_bse_code(conn, bse_code)
    stock_id = stock_row["id"] if stock_row else None

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

            # Sections with diffs
            if status == "READY":
                sections = get_sections(conn, fid)
                if sections:
                    st.markdown(f"**Sections ({len(sections)})**")

                    if stock_id:
                        diffs = {
                            d["section_header"]: d
                            for d in get_diffs_for_filing(conn, fid, stock_id)
                        }
                    else:
                        diffs = {}

                    for sec in sections:
                        header = sec["header"]
                        sec_text = sec.get("text", "")
                        has_diff = header in diffs and diffs[header].get("changed")

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
                                    diffs[header].get("diff_text", "")[:2000],
                                    language="diff",
                                )

    conn.close()

st.caption(
    "Data source: BSE Corporate Announcements API. "
    "Run `python -m diffiq.pipeline` to fetch new filings."
)
