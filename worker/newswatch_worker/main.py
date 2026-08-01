"""Worker entrypoint: `newswatch run-cycle [--dry]`, `newswatch eval`,
`newswatch process-source-tests`, and `newswatch serve` (the long-running
APScheduler loop, docs/02-architecture.md §3).
"""

from __future__ import annotations

import argparse
import logging
import sys

from newswatch_worker.cycle import run_cycle
from newswatch_worker.db import get_engine, table
from newswatch_worker.eval import print_drift_report, print_pm_drift_report, run_eval, run_pm_eval
from newswatch_worker.scheduler import run_forever
from newswatch_worker.source_tests import process_pending_source_tests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newswatch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_cycle_parser = subparsers.add_parser(
        "run-cycle",
        help="Run one digest cycle to completion, or resume an incomplete one.",
    )
    run_cycle_parser.add_argument(
        "--dry",
        action="store_true",
        help="Walk the cycle state machine with no-op steps only (Phase 1 skeleton mode).",
    )

    subparsers.add_parser(
        "process-source-tests",
        help="Drain pending source_tests rows (Settings 'Test' button handshake, arch §6).",
    )

    subparsers.add_parser(
        "eval",
        help="Run golden-fixture triage/analysis drift report against the live API (docs/04 §10).",
    )

    subparsers.add_parser(
        "serve",
        help="Run forever: scheduled cycles per settings['schedule'], manual-run and source_tests polling (arch §3).",
    )

    args = parser.parse_args(argv)

    if args.command == "run-cycle":
        final_state = run_cycle(dry=args.dry, kind="manual")
        print(f"cycle finished in state: {final_state}")
        return 0 if final_state == "DONE" else 1

    if args.command == "process-source-tests":
        engine = get_engine()
        tables = {"source_tests": table("source_tests"), "sources": table("sources")}
        with engine.begin() as conn:
            count = process_pending_source_tests(conn, tables=tables)
        print(f"processed {count} source test(s)")
        return 0

    if args.command == "eval":
        engine = get_engine()
        # Committed like any other cycle's calls: eval calls cost real money
        # and go through the same budget guard, so the spend ledger should
        # reflect them (eval.py's module docstring).
        with engine.begin() as conn:
            reports = run_eval(conn)
            pm_reports = run_pm_eval(conn)
        all_passed = print_drift_report(reports)
        print()
        pm_all_passed = print_pm_drift_report(pm_reports)
        return 0 if all_passed and pm_all_passed else 1

    if args.command == "serve":
        run_forever()
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(cli())
