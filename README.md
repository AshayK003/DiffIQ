<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/DiffIQ-1A1A1A?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0MCIgaGVpZ2h0PSI0MCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNmZmYiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNMTQuNSAySDZhMiAyIDAgMCAwLTIgMnYxNmEyIDIgMCAwIDAgMiAyaDEyYTIgMiAwIDAgMCAyLTJWNy41TDE0LjUgMnoiLz48cG9seWxpbmUgcG9pbnRzPSIxNCAyIDE0IDggMjAgOCIvPjxsaW5lIHgxPSIxNiIgeTE9IjEzIiB4Mj0iOCIgeTI9IjEzIi8+PGxpbmUgeDE9IjE2IiB5MT0iMTciIHgyPSI4IiB5Mj0iMTciLz48L3N2Zz4=">
  </picture>
</p>

<h3 align="center">DiffIQ &middot; Corporate Filing Monitor</h3>

<p align="center">
  Track BSE-listed portfolio stocks — automatically crawl, extract, classify,
  sectionize, and diff corporate announcements.
  <br>
  <em>Zero external services. Pure Python + SQLite.</em>
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick Start</strong></a> ·
  <a href="#architecture"><strong>Architecture</strong></a> ·
  <a href="#usage"><strong>Usage</strong></a> ·
  <a href="#dashboard"><strong>Dashboard</strong></a> ·
  <a href="#testing"><strong>Testing</strong></a>
</p>

---

## Why DiffIQ

If you hold Indian equities, you've seen this pattern:

1. A stock you own files an audit report, related-party transaction, or shareholding change.
2. You don't notice until weeks later (if at all).
3. By then the price has already moved.

DiffIQ automates the observation layer. It polls the BSE Corporate Announcements API daily, downloads the attached PDFs, extracts text, classifies them by type, splits them into logical sections, and diffs each section against the prior filing of the same type — so you can spot what actually *changed* without reading the whole document.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Pipeline                         │
│                                                    │
│  Crawler → Download → Extract → Classify → Store  │
│                     ↓                              │
│               Sectionize → Diff                    │
└──────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────┐
│  SQLite (stocks, filings,   │
│  sections, diffs)           │
└─────────────────────────────┘
         ↓
┌─────────────────────────────┐
│  Streamlit Dashboard        │
│  (portfolio overview,       │
│   filing browser, diff UI)  │
└─────────────────────────────┘
```

### Data Flow

| Step | Component | What happens |
|---|---|---|
| 1 | **crawler.py** | Calls BSE API via the `bse` package for each watchlisted stock. Returns a manifest of announcements (UUID, subject, date, PDF URL). |
| 2 | **pipeline.py** | Orchestrates: inserts new filings (QUEUED), then downloads PDFs in parallel (3 workers). |
| 3 | **extractor.py** | Downloads each PDF via `httpx`, extracts text with `pypdf`. Rejects PDFs >50MB and scanned PDFs (text <100 chars). Caps stored text at 1MB. Returns `ExtractionResult`. |
| 4 | **classifier.py** | Classifies filing subjects into types (AUDIT_REPORT, FINANCIAL_RESULT, RPT, PROMOTER_CHANGE, BOARD_OUTCOME, ROUTINE) using pre-compiled regex patterns. |
| 5 | **extractor.py** (2nd pass) | Splits extracted text into logical sections by filing-type-specific header regexes (e.g. "Opinion", "Basis for Opinion" for audit reports). Falls back to generic numbered-section patterns, then to a single "Body" section. |
| 6 | **differ.py** | Aligns new sections to the most recent same-type filing using `difflib.SequenceMatcher` (header similarity first, then text preview). Generates unified diffs for aligned sections. Stores diff records marked `changed` if output >100 chars. |
| 7 | **dashboard/** | Streamlit app with portfolio overview grid, stock selector, filing expanders, section diff UI. |

### Schema (4 tables)

- **stocks** — watchlist entries (bse_code unique key)
- **filings** — announcements with status lifecycle (QUEUED → DOWNLOADING → READY | ERROR_* | NO_PDF)
- **sections** — extracted document sections per filing
- **diffs** — section-aligned unified diff records per filing pair

---

## Quick Start

### Prerequisites

- Python 3.11+
- Recommended: `uv` (fast pip-compatible installer)

```bash
# Clone
git clone https://github.com/AshayK003/DiffIQ.git
cd DiffIQ

# Create virtualenv
python -m venv .venv
source .venv/bin/activate    # Linux/Mac
.venv\Scripts\activate        # Windows

# Install
pip install -r requirements.txt
```

> [!NOTE]
> `uv` users: `uv pip install -r requirements.txt` works identically and is 10-50x faster.

### Verify

```bash
pytest — 97 tests should pass
```

---

## Usage

### Run the daily pipeline

```bash
python -m diffiq.pipeline
```

This crawls all BSE-coded stocks in the watchlist, fetches new announcements, downloads PDFs, extracts text, classifies, sectionizes, and diffs. Runs sequentially per stock with a 5-second delay between BSE API calls. PDFs download in parallel (3 workers).

**Schedule it** via cron (Linux/Mac) or Task Scheduler (Windows):

```cron
# Every weekday at 9 AM IST (3:30 UTC)
30 3 * * 1-5 cd /path/to/DiffIQ && .venv/bin/python -m diffiq.pipeline
```

### Retry failed filings

```bash
python -c "from diffiq.pipeline import run_backlog; run_backlog()"
```

Re-processes any filings stuck in `QUEUED` or `ERROR_*` status. Safe to run repeatedly — checks each filing has a PDF URL before attempting.

### Backfill sections & diffs

```bash
python -c "from diffiq.pipeline import sync; sync()"
```

Processes existing `READY` filings through the sectionize → diff pipeline. Useful after adding new section patterns or fixing extraction logic. **Idempotent** — deletes and re-creates diffs for each filing.

### Dashboard

```bash
streamlit run dashboard/app.py
```

Opens a browser UI at `localhost:8501`. Shows:
- **Portfolio Overview** — grid of all stocks with filing counts and latest dates
- **Stock browser** — select a stock, see all filings with status badges
- **Filing detail** — expand a filing to see its metadata, sections, and diffs against the prior filing
- **Section diff UI** — sections with changes auto-expand with a green "Changed" badge and code diff view
- **Watchlist management** — add/remove stocks directly from the dashboard (persisted to DB)

---

## Configuration

### Stock Watchlist

Edit `diffiq/config.py`, or use the dashboard **Watchlist Management** section:

```python
STOCKS = [
    {"symbol": "VEDL", "name": "VEDL", "bse_code": "500295"},
    {"symbol": "HDFCBANK", "name": "HDFCBANK", "bse_code": "500180"},
    # ETFs have empty bse_code — skipped by pipeline but shown in dashboard
    {"symbol": "NEXT50IETF", "name": "NEXT50IETF", "bse_code": ""},
]
```

The config file seeds the DB on first visit. After that, you can add/remove stocks via the dashboard UI — changes persist in `diffiq.db`.

### Other Settings (also in `config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `PDF_DOWNLOAD_TIMEOUT` | 120s | HTTP client timeout for PDF downloads |
| `CRAWL_DELAY_SECONDS` | 5s | Delay between BSE API calls per stock |
| `PDF_CACHE_DIR` | `data/pdfs/` | Created automatically; currently unused by extraction |
| `DATA_DIR` | `data/` | Where the SQLite database lives |

---

## Project Structure

```
diffiq/
├── __init__.py
├── config.py            # Stock watchlist, paths, constants
├── crawler.py           # BSE API via `bse` package
├── pipeline.py          # Orchestration: run_daily_pipeline, sync, run_backlog
├── extractor.py         # PDF download (httpx) + text extraction (pypdf) + section splitting
├── classifier.py        # Subject-line regex classification
├── differ.py            # Section alignment + unified diff generation
├── db.py                # SQLite helpers (parameterized queries, batch fetch)
├── schema.py            # CREATE TABLE, connection init with WAL + busy_timeout
├── dashboard_utils.py   # Status badge HTML for Streamlit
dashboard/
├── app.py               # Streamlit UI — portfolio, filing browser, diff viewer
.streamlit/
├── config.toml          # Streamlit theme (green, sans-serif, fast reruns)
├── style.css            # Stock cards, badges, diff badge styles
tests/                   # 97 tests across 10 test files
data/                    # gitignored — runtime SQLite DB + PDF cache
```

---

## Testing

```bash
pytest              # 97 tests, 0 failures expected
pytest -v           # verbose mode
pytest -k "sync"    # run only sync-related tests
```

### Test Architecture

- **`conftest.py`** — provides a `db` fixture: in-memory SQLite database created fresh per test, auto-closed.
- **Dependency injection** — all pipeline functions accept an optional `sqlite3.Connection`. Tests pass an `:memory:` connection, avoiding filesystem writes and side effects.
- **Mocked externals** — HTTP calls (`httpx.Client`, BSE API via `bse.BSE`) are patched at the call site using `unittest.mock.patch`.
- **Coverage**: 10 test files covering extractors, classifiers, differ, DB helpers, pipeline orchestration, dashboard utilities, and BSE crawler.

---

## Deployment

The dashboard is a single-file Streamlit app. Deploy to **Streamlit Community Cloud**:

1. Push your fork to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect the repo, set main file to `dashboard/app.py`
4. No secrets or build commands needed (free tier works)

> The pipeline runs *locally* (or on a cron server) — the dashboard is read-only from the DB.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No announcements returned" for a stock | BSE API rate-limited or stock has no recent filings | Wait and retry, or check the BSE website manually |
| Filings stuck in `QUEUED` | Pipeline crashed before download | Run `run_backlog()` |
| Filings stuck in `DOWNLOADING` | Pipeline crashed mid-download | Run `run_backlog()` — or manually set to QUEUED: `UPDATE filings SET status = 'QUEUED' WHERE status = 'DOWNLOADING'` |
| "pypdf extraction failed" | PDF is password-protected or uses image-only content | These filings are flagged as errors; no workaround |
| "Scanned PDF" status | Text < 100 chars extracted | The PDF contains no extractable text (image scan) |
| Streamlit dashboard is empty | Pipeline hasn't been run yet | Run `python -m diffiq.pipeline` |
| `bse` package import error | Package not installed | `pip install bse>=0.1.0` |
| `sqlite3.DatabaseError: database is locked` | Concurrent writes to the same DB file | Built-in WAL mode + `busy_timeout=5000` handles most cases; ensure only one pipeline runs at a time |

---

## FAQ

**Q: Does this need API keys?**  
A: No. BSE corporate announcements are public. The `bse` package talks to the undocumented but public BSE API. No signup required.

**Q: Can I use this for NSE-listed stocks?**  
A: Not yet. The crawler uses the BSE API. NSE blocks programmatic access. A future version may pipe in NSE data through alternate sources.

**Q: Why SQLite?**  
A: It's a local single-user tool. SQLite means zero infra: no daemon, no config, no Docker. Backup is a single file copy.

**Q: What happens if a PDF is encrypted or scanned?**  
A: `pypdf` raises on encrypted PDFs (status: `ERROR_EXTRACTION`). Scanned PDFs produce <100 chars of text, flagged as `ERROR_EXTRACTION` with a "Scanned PDF" error.

**Q: How do I reset the database?**  
A: Delete `data/diffiq.db` and re-run the pipeline. Tables are re-created via `CREATE TABLE IF NOT EXISTS`. All state is regenerated.

---

## Extending

### Adding a new filing type

Two places to update:

1. **`classifier.py`** — add a regex pattern to `_FilingClassifier._patterns`
2. **`extractor.py`** — add section header patterns to `SECTION_HEADERS`

Example: adding a "MERGER" type:

```python
# classifier.py
("MERGER", re.compile(r"\bmerger|amalgamation|scheme\s+of\s+arrangement\b", re.IGNORECASE)),

# extractor.py
"MERGER": [
    r"Scheme\s+of\s+Arrangement",
    r"Share\s+Exchange\s+Ratio",
    r"Appointed\s+Date",
],
```

### Adding a new stock

Add to the watchlist via the dashboard **Watchlist Management** section or edit `config.py:STOCKS`. Find the BSE scrip code (numeric) from the BSE website stock profile page.

### Customizing the dashboard

- Theme colors: edit `.streamlit/config.toml`
- Badge styles: edit `.streamlit/style.css`
- Layout: edit `dashboard/app.py` — it's a single file Streamlit app

---

## License

AGPL v3 — see [LICENSE](LICENSE).
