"""DiffIQ configuration — stock watchlist, BSE params, paths.

WARNING: This file is committed to the repo. Do NOT add secrets (API keys,
passwords, tokens) here.
"""

from pathlib import Path

# Stock watchlist with BSE scrip codes.
# Corporate entities file announcements on BSE. ETFs are listed in the
# dashboard for display but have no corporate filings to track.
STOCKS: list[dict] = [
    {"name": "VEDL", "bse_code": "500295"},
    {"name": "HDFCBANK", "bse_code": "500180"},
    {"name": "GROWW", "bse_code": "544603"},
    {"name": "ENERGY", "bse_code": "544604"},
    # ETFs — trade on BSE but no corporate filings
    {"name": "NEXT50IETF", "bse_code": ""},
    {"name": "NIFTYBEES", "bse_code": ""},
    {"name": "MIDCAPETF", "bse_code": ""},
    {"name": "GOLDBEES", "bse_code": ""},
    {"name": "MODEFENCE", "bse_code": ""},
    {"name": "MAKEINDIA", "bse_code": ""},
    {"name": "MASPTOP50", "bse_code": ""},
    {"name": "METALETF", "bse_code": ""},
    {"name": "PWL", "bse_code": ""},
    {"name": "LIQUIDCASE", "bse_code": ""},
]

# BSE endpoints
BSE_PDF_BASE: str = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"

PDF_DOWNLOAD_TIMEOUT: int = 120
CRAWL_DELAY_SECONDS: int = 5

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
DB_PATH: Path = DATA_DIR / "diffiq.db"
PDF_CACHE_DIR: Path = DATA_DIR / "pdfs"
