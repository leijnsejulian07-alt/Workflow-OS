"""Acceptance coverage for the CLI: real subprocess restarts, no live side effects."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from workflow_os.sqlite_lifecycle import managed_connection


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_workflow_os_paper_acceptance.py"


class OfflinePaperAcceptanceTests(unittest.TestCase):
    def _launch(self, base: Path) -> dict[str, object]:
        env = os.environ.copy()
        # Deliberately set canary "live" credential variables; the CLI must
        # ignore and exclude them from its subprocess environments.
        env["OPENSHORTS_API_KEY"] = "real-looking-canary-MUST-NOT-BE-USED"
        env["WHOP_API_TOKEN"] = "another-real-looking-canary-MUST-NOT-BE-USED"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--output-dir", str(base)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr[-4000:])
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_full_existing_worker_survives_independent_python_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            summary = self._launch(Path(root))
            self.assertEqual(summary["mode"], "SYNTHETIC_OFFLINE_ONLY")
            self.assertTrue(summary["offline_acceptance_passed"])
            self.assertFalse(summary["test_mode_ready"])
            self.assertEqual(summary["phases"], 7)

            run_dir = Path(summary["run_dir"])
            self.assertEqual(run_dir.parent, Path(root))
            self.assertTrue(Path(summary["sqlite"]).is_file())
            self.assertTrue(Path(summary["events"]).is_file())
            self.assertTrue((run_dir / "summary.json").is_file())

            events = [json.loads(line) for line in Path(summary["events"]).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                [event["phase"] for event in events],
                ["seed", "local_failure", "restart_success", "no_duplicate",
                 "ambiguous_failure", "unknown_after_restart", "verify"],
            )
            self.assertEqual(events[1]["http_calls"], 0)
            self.assertEqual(events[2]["http_calls"], 1)
            self.assertEqual(events[3]["http_calls"], 0)
            self.assertEqual(events[4]["http_calls"], 1)
            self.assertEqual(events[5]["http_calls"], 0)

            with managed_connection(sqlite3.connect(summary["sqlite"])) as db:
                jobs = db.execute(
                    "SELECT idempotency_key, state, attempt_count FROM jobs ORDER BY job_id"
                ).fetchall()
                effects = db.execute(
                    "SELECT state, attempt_count FROM side_effects ORDER BY rowid"
                ).fetchall()
            self.assertEqual(
                jobs,
                [
                    ("paper-only:success", "SUCCEEDED", 2),
                    ("paper-only:unknown", "UNKNOWN", 1),
                ],
            )
            self.assertEqual(effects, [("SUCCEEDED", 1), ("UNKNOWN", 1)])
            combined = (run_dir / "summary.json").read_text(encoding="utf-8")
            combined += Path(summary["events"]).read_text(encoding="utf-8")
            combined += Path(summary["sqlite"]).read_bytes().decode("latin-1")
            self.assertNotIn("real-looking-canary", combined)
            self.assertNotIn("offline-smoke-credential-never-sent", combined)

    def test_repeated_invocations_never_reuse_or_overwrite_prior_state(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            first = self._launch(base)
            second = self._launch(base)
            self.assertNotEqual(first["run_dir"], second["run_dir"])
            self.assertTrue(Path(first["events"]).exists())
            self.assertTrue(Path(second["events"]).exists())
            self.assertTrue(first["offline_acceptance_passed"])
            self.assertTrue(second["offline_acceptance_passed"])


if __name__ == "__main__":
    unittest.main()
