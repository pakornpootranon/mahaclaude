"""Worker entrypoint. Phase 1: `newswatch run-cycle [--dry]`. The
APScheduler-driven scheduled-cycle loop (docs/02-architecture.md §3) and
`newswatch eval` (docs/04 §10) land in later phases.
"""

from __future__ import annotations

import argparse
import logging
import sys

from newswatch_worker.cycle import run_cycle

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

    args = parser.parse_args(argv)

    if args.command == "run-cycle":
        final_state = run_cycle(dry=args.dry, kind="manual")
        print(f"cycle finished in state: {final_state}")
        return 0 if final_state == "DONE" else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(cli())
