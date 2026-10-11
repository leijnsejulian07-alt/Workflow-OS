#!/usr/bin/env python3
"""Read-only Workflow OS runtime diagnostics, without requiring provider credentials.

Usage:
    python scripts/workflow_os_doctor.py
    python scripts/workflow_os_doctor.py --state-db C:\path\state.sqlite
    python scripts/workflow_os_doctor.py --paper-run-dir C:\path\paper-... --output report.json

Nothing is installed, retried, reconciled, submitted or modified in SQLite.
This check cannot prove a live payment, publication or unattended scheduler.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


_EXPECTED_PHASES = (
    "seed", "local_failure", "restart_success", "no_duplicate",
    "ambiguous_failure", "unknown_after_restart", "verify",
)
_EXPECTED_PAPER_JOBS = {
    "paper-only:success": ("SUCCEEDED", 2),
    "paper-only:unknown": ("UNKNOWN", 1),
}


def _open_read_only(path: Path) -> sqlite3.Connection:
    # URI quoting prevents ?/# and spaces in Windows paths from changing mode.
    uri = path.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=3)
    db.execute("PRAGMA query_only=ON")
    return db


def _counts(db: sqlite3.Connection, table: str) -> dict[str, int]:
    if table not in {"jobs", "side_effects"}:
        raise ValueError("invalid diagnostic table")
    present = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not present:
        return {}
    return {str(state): int(count) for state, count in db.execute(
        f"SELECT state, COUNT(*) FROM {table} GROUP BY state"
    )}


def inspect_state_db(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"status": "NOT_CONFIGURED", "jobs": {}, "side_effects": {}}
    if not path.is_absolute():
        return {"status": "INVALID_PATH", "jobs": {}, "side_effects": {}}
    if not path.is_file():
        return {"status": "MISSING", "jobs": {}, "side_effects": {}}

    db: sqlite3.Connection | None = None
    try:
        db = _open_read_only(path)
        check = db.execute("PRAGMA quick_check(1)").fetchone()
        if not check or str(check[0]) != "ok":
            return {"status": "INTEGRITY_ERROR", "jobs": {}, "side_effects": {}}
        jobs = _counts(db, "jobs")
        effects = _counts(db, "side_effects")
        now = datetime.now(timezone.utc)
        stale_leases = 0
        malformed_leases = 0
        if jobs:
            for (expiry,) in db.execute(
                "SELECT lease_expires_at FROM jobs WHERE state='LEASED'"
            ):
                try:
                    dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                    if dt.tzinfo is None or dt.utcoffset() is None:
                        raise ValueError("timezone missing")
                except (ValueError, TypeError):
                    malformed_leases += 1
                    continue
                if dt.astimezone(timezone.utc) <= now:
                    stale_leases += 1
        return {
            "status": "OK",
            "jobs": jobs,
            "side_effects": effects,
            "unknown_jobs": jobs.get("UNKNOWN", 0),
            "unknown_effects": effects.get("UNKNOWN", 0),
            "stale_leases": stale_leases,
            "malformed_leases": malformed_leases,
        }
    except (OSError, sqlite3.Error) as exc:
        # Exception detail intentionally omitted: a local path or data can be sensitive.
        return {
            "status": "UNREADABLE",
            "error_type": type(exc).__name__,
            "jobs": {},
            "side_effects": {},
        }
    finally:
        if db is not None:
            db.close()


def inspect_paper_evidence(run_dir: Path | None) -> dict[str, object]:
    if run_dir is None:
        return {"status": "NOT_SUPPLIED", "valid": False}
    root = run_dir.expanduser().resolve()
    summary_file = root / "summary.json"
    events_file = root / "events.jsonl"
    db_file = root / "paper-only.sqlite"
    if not all(p.is_file() for p in (summary_file, events_file, db_file)):
        return {"status": "MISSING_FILES", "valid": False}
    try:
        if summary_file.stat().st_size > 256 * 1024 or events_file.stat().st_size > 256 * 1024:
            return {"status": "OVERSIZED_LOG", "valid": False}
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in events_file.read_text(encoding="utf-8").splitlines()
        ]
        valid_header = (
            isinstance(summary, dict)
            and summary.get("mode") == "SYNTHETIC_OFFLINE_ONLY"
            and summary.get("offline_acceptance_passed") is True
            and summary.get("test_mode_ready") is False
            and summary.get("phases") == len(_EXPECTED_PHASES)
            and Path(str(summary.get("sqlite", ""))).resolve() == db_file
            and Path(str(summary.get("events", ""))).resolve() == events_file
            and Path(str(summary.get("run_dir", ""))).resolve() == root
        )
        valid_events = (
            len(events) == len(_EXPECTED_PHASES)
            and all(isinstance(event, dict) for event in events)
            and tuple(event.get("phase") for event in events) == _EXPECTED_PHASES
            and events[1].get("http_calls") == 0
            and events[2].get("http_calls") == 1
            and events[3].get("http_calls") == 0
            and events[4].get("http_calls") == 1
            and events[5].get("http_calls") == 0
        )
        with _open_read_only(db_file) as db:
            actual_jobs = {
                str(k): (str(state), int(attempts))
                for k, state, attempts in db.execute(
                    "SELECT idempotency_key, state, attempt_count FROM jobs"
                )
            }
            effects = Counter(str(state) for (state,) in db.execute(
                "SELECT state FROM side_effects"
            ))
        passed = (
            valid_header and valid_events
            and actual_jobs == _EXPECTED_PAPER_JOBS
            and effects == Counter({"SUCCEEDED": 1, "UNKNOWN": 1})
        )
        return {
            "status": "PASS" if passed else "EVIDENCE_MISMATCH",
            "valid": bool(passed),
            "phase_count": len(events),
            "note": "Synthetic worker/QC/provider tests only; no real platform call or payout",
        }
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, json.JSONDecodeError):
        return {"status": "INVALID_EVIDENCE", "valid": False}


def build_report(
    state_db: Path | None = None,
    paper_run_dir: Path | None = None,
) -> dict[str, object]:
    db = inspect_state_db(state_db)
    paper = inspect_paper_evidence(paper_run_dir)
    blockers: list[str] = []
    if sys.version_info < (3, 12):
        blockers.append("Python 3.12+ recommended for supported Workflow OS runtime")
    if db["status"] != "OK":
        blockers.append("Authorized runtime SQLite state is not verified")
    if db.get("unknown_jobs", 0) or db.get("unknown_effects", 0):
        blockers.append("UNKNOWN outcomes need external reconciliation; never retry blindly")
    if db.get("stale_leases", 0) or db.get("malformed_leases", 0):
        blockers.append("Expired or malformed leases require bounded recovery/reconciliation")
    if not paper["valid"]:
        blockers.append("Offline worker acceptance proof missing or invalid")
    blockers.append("Unattended scheduling/restart on the authorized Windows runtime not verified")
    blockers.append("Provider rights, KYC, authorized external actions and real settlement not verified")
    return {
        "project": "Workflow OS",
        "mode": "READ_ONLY_LOCAL_DIAGNOSTICS",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": ".".join(map(str, sys.version_info[:3])),
        "runtime_database": db,
        "paper_acceptance": paper,
        "TEST_MODE_READY": "NO",
        "LIVE_MODE_READY": "NO",
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-db", type=Path,
        help="Existing authorized Workflow OS SQLite file; opened strictly READ ONLY",
    )
    parser.add_argument(
        "--paper-run-dir", type=Path,
        help="Path of one completed synthetic acceptance run (summary.json + events.jsonl)",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Optionally create a NEW sanitized JSON report; never overwrite an existing file",
    )
    args = parser.parse_args(argv)
    config = os.environ.get("WORKFLOW_OS_OPENSHORTS_STATE_DB", "").strip()
    state_db = args.state_db if args.state_db is not None else (Path(config) if config else None)
    report = build_report(state_db=state_db, paper_run_dir=args.paper_run_dir)
    if args.output is not None:
        output = args.output.expanduser().resolve()
        # Explicit no-clobber; no secrets or user-specific absolute DB paths in report.
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
