#!/usr/bin/env python3
"""Crash-audited launcher for synthetic Workflow OS acceptance on Windows.

Never makes real provider submissions, trades, payments or publications.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from workflow_os.offline_run_lock import exclusive_paper_run_lock
from workflow_os_doctor import inspect_paper_evidence

MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024 * 1024


def _audit(root: Path, **event: object) -> None:
    path = root / "runs.jsonl"
    if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
        os.replace(path, root / "runs.previous.jsonl")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), **event}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

def _reconcile(root: Path) -> int:
    active: set[str] = set()
    for name in ("runs.previous.jsonl", "runs.jsonl"):
        path = root / name
        if not path.exists():
            continue
        if path.stat().st_size > MAX_LOG_BYTES * 2:
            raise RuntimeError("oversized audit ledger")
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            key = item.get("run_id")
            if not isinstance(key, str):
                raise RuntimeError("invalid audit record")
            if item.get("status") == "STARTED":
                active.add(key)
            elif item.get("status") in {"PASS", "FAIL", "INTERRUPTED"}:
                active.discard(key)
            else:
                raise RuntimeError("invalid audit state")
    for key in sorted(active):
        _audit(root, run_id=key, status="INTERRUPTED")
    return len(active)


def _safe_env() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _check_capacity(root: Path) -> None:
    total = 0
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink():
                raise RuntimeError("symlink in paper evidence directory")
            if path.is_file():
                total += path.stat().st_size
                if total > MAX_EVIDENCE_BYTES:
                    raise RuntimeError("paper evidence capacity reached")

def run_once(root: Path, timeout: int = 240) -> dict[str, object]:
    if not 30 <= timeout <= 600:
        raise ValueError("timeout outside allowed bounds")
    with exclusive_paper_run_lock(root / "scheduler"):
        root.mkdir(parents=True, exist_ok=True)
        interrupted = _reconcile(root)
        _check_capacity(root / "runs")
        run_id = secrets.token_hex(12)
        _audit(root, run_id=run_id, status="STARTED")
        status, error, paper_run = "FAIL", None, None
        try:
            cp = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "run_workflow_os_paper_acceptance.py"),
                 "--output-dir", str(root / "runs")],
                cwd=ROOT, env=_safe_env(), timeout=timeout,
                capture_output=True, text=True, check=False,
            )
            if cp.returncode:
                raise RuntimeError("offline acceptance process failed")
            result = json.loads(cp.stdout)
            if result.get("mode") != "SYNTHETIC_OFFLINE_ONLY" or result.get("test_mode_ready") is not False:
                raise RuntimeError("unsafe acceptance result")
            candidate = Path(result["run_dir"]).resolve()
            if candidate.parent != (root / "runs").resolve() or not candidate.name.startswith("paper-"):
                raise RuntimeError("unexpected evidence path")
            if inspect_paper_evidence(candidate).get("valid") is not True:
                raise RuntimeError("independent evidence validation failed")
            paper_run, status = candidate.name, "PASS"
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error = type(exc).__name__
        finally:
            _audit(root, run_id=run_id, status=status, error_type=error, paper_run=paper_run)
        return {"mode": "SYNTHETIC_OFFLINE_ONLY", "status": status, "run_id": run_id,
                "paper_run": paper_run, "interrupted_reconciled": interrupted,
                "TEST_MODE_READY": "NO", "LIVE_MODE_READY": "NO"}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
                        / "WorkflowOS" / "offline-paper")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    try:
        result = run_once(args.data_dir.expanduser().resolve(), timeout=args.timeout)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        result = {"mode": "SYNTHETIC_OFFLINE_ONLY", "status": "BLOCKED",
                  "error_type": type(exc).__name__, "TEST_MODE_READY": "NO", "LIVE_MODE_READY": "NO"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
