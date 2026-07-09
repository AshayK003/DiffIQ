"""Allow running DiffIQ pipeline via `python -m diffiq`."""

import argparse
import logging
import sys

from diffiq.pipeline import run_daily_pipeline, run_backlog, sync


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="diffiq",
        description="DiffIQ — Corporate Filing Monitor",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run daily pipeline (crawl + extract + diff)")
    sub.add_parser("backlog", help="Retry failed/queued filings")
    sub.add_parser("sync", help="Backfill sections and diffs for READY filings")

    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "run":
        run_daily_pipeline()
    elif args.command == "backlog":
        run_backlog()
    elif args.command == "sync":
        sync()
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
