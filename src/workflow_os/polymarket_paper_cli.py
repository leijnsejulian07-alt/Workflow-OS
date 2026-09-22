from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .polymarket_paper_runner import run_paper_cycle
from .polymarket_paper_state import PolymarketPaperStore
from .polymarket_xai_estimator import estimate_with_xai


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow OS Polymarket paper-only test runner")
    parser.add_argument("--db", default="polymarket-paper.sqlite3", help="SQLite paper ledger path")
    parser.add_argument("--bankroll", type=float, default=50.0, help="Initial paper bankroll for a new ledger")
    parser.add_argument("--market-limit", type=int, default=25, help="Maximum markets to inspect in this cycle")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.market_limit < 1 or args.market_limit > 100:
        print(json.dumps({"ok": False, "reason": "INVALID_MARKET_LIMIT"}))
        return 2
    if not os.getenv("XAI_API_KEY", "").strip():
        print(json.dumps({"ok": False, "reason": "XAI_API_KEY_REQUIRED", "network_started": False}))
        return 2

    try:
        store = PolymarketPaperStore(Path(args.db), starting_bankroll_usd=args.bankroll)
        summary = run_paper_cycle(store=store, estimator=estimate_with_xai, market_limit=args.market_limit)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "reason": type(exc).__name__}))
        return 1

    payload = {"ok": True, "mode": "PAPER_ONLY", **asdict(summary)}
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
