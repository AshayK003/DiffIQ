"""DiffIQ CLI — Corporate Filing Monitor.

Usage:
    python -m diffiq run          Run daily pipeline
    python -m diffiq backlog      Retry failed/queued filings
    python -m diffiq sync         Backfill sections and diffs
    python -m diffiq run --verbose
"""

import fire
import structlog

from diffiq.pipeline import run_daily_pipeline, run_backlog, sync as _pipeline_sync

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


def run(verbose: bool = False) -> None:
    """Run daily pipeline (crawl + extract + diff)."""
    structlog.get_logger().info("Running daily pipeline")
    run_daily_pipeline()


def backlog() -> None:
    """Retry failed/queued filings."""
    structlog.get_logger().info("Retrying failed/queued filings")
    run_backlog()


def sync_() -> None:
    """Backfill sections and diffs for READY filings."""
    structlog.get_logger().info("Backfilling sections and diffs")
    _pipeline_sync()


if __name__ == "__main__":
    fire.Fire({"run": run, "backlog": backlog, "sync": sync_})
