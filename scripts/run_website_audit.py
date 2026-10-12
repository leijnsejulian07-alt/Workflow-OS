#!/usr/bin/env python3
"""Audit locally supplied HTML files without network access or external actions.

Usage:
    python scripts/run_website_audit.py --site-dir C:\path\to\static-site
    python scripts/run_website_audit.py --site-dir ./demo --output ./report.json

Reports are limited static heuristics, not verified accessibility/SEO scores.
Existing outputs are NEVER overwritten, and no website is fetched or contacted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from workflow_os.website_audit import audit_local_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, required=True, help="Directory containing your own .html/.htm files")
    parser.add_argument("--output", type=Path, help="Create a NEW JSON report; existing files are never overwritten")
    options = parser.parse_args(argv)
    try:
        report = audit_local_site(options.site_dir)
        text = json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if options.output is not None:
            # Create only. Avoid partial reports that could be mistaken for a PASS.
            path = options.output.expanduser().absolute()
            with path.open("x", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
        print(text, end="")
        return 0
    except (OSError, ValueError, TypeError) as exc:
        # Do not print arbitrary user-supplied HTML, file names or private paths.
        print(f"Offline website audit blocked: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
