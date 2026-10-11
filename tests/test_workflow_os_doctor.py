"""Read-only runtime diagnostics must remain truthful and not leak credentials."""
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
DOCTOR = ROOT / "scripts" / "workflow_os_doctor.py"
ACCEPTANCE = ROOT / "scripts" / "run_workflow_os_paper_acceptance.py"


class WorkflowOSDoctorTests(unittest.TestCase):
    def _run(self, *args: str, success: bool = True) -> dict[str, object] | subprocess.CompletedProcess:
        env = os.environ.copy()
        env["OPENSHORTS_API_KEY"] = "secret-do-not-print"
        run = subprocess.run(
            [sys.executable, str(DOCTOR), *args], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=10, check=False,
        )
        if not success:
            return run
        self.assertEqual(run.returncode, 0, msg=run.stderr)
        self.assertNotIn("secret-do-not-print", run.stdout)
        return json.loads(run.stdout)

    def test_missing_runtime_is_reported_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "state.sqlite"
            out = self._run("--state-db", str(missing))
            self.assertEqual(out["runtime_database"]["status"], "MISSING")
            self.assertEqual(out["paper_acceptance"]["status"], "NOT_SUPPLIED")
            self.assertEqual(out["TEST_MODE_READY"], "NO")
            self.assertEqual(out["LIVE_MODE_READY"], "NO")
            self.assertFalse(missing.exists())

    def test_read_only_sqlite_unknown_and_stale_lease_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            db_path = Path(root) / "runtime.sqlite"
            with managed_connection(sqlite3.connect(db_path)) as db:
                db.execute("CREATE TABLE jobs (state TEXT, lease_expires_at TEXT)")
                db.execute("CREATE TABLE side_effects (state TEXT)")
                db.execute("INSERT INTO jobs VALUES('UNKNOWN',NULL)")
                db.execute("INSERT INTO jobs VALUES('LEASED','2000-01-01T00:00:00+00:00')")
                db.execute("INSERT INTO side_effects VALUES('UNKNOWN')")
            original = db_path.read_bytes()
            report = self._run("--state-db", str(db_path))
            self.assertEqual(report["runtime_database"]["status"], "OK")
            self.assertEqual(report["runtime_database"]["unknown_jobs"], 1)
            self.assertEqual(report["runtime_database"]["unknown_effects"], 1)
            self.assertEqual(report["runtime_database"]["stale_leases"], 1)
            self.assertIn("UNKNOWN outcomes need external reconciliation; never retry blindly", report["blockers"])
            self.assertEqual(db_path.read_bytes(), original)

    def test_independently_checks_real_offline_acceptance_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / "runs"
            cp = subprocess.run(
                [sys.executable, str(ACCEPTANCE), "--output-dir", str(parent)],
                cwd=ROOT, capture_output=True, text=True, timeout=45, check=False,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)
            acceptance = json.loads(cp.stdout)
            report = self._run(
                "--paper-run-dir", str(acceptance["run_dir"]),
                "--state-db", str(acceptance["sqlite"]),
            )
            self.assertEqual(report["paper_acceptance"]["status"], "PASS")
            self.assertTrue(report["paper_acceptance"]["valid"])
            self.assertEqual(report["runtime_database"]["status"], "OK")
            self.assertEqual(report["TEST_MODE_READY"], "NO")
            # A forged status flag alone does not imply operational readiness.
            summary_file = Path(acceptance["run_dir"]) / "summary.json"
            data = json.loads(summary_file.read_text())
            data["mode"] = "LIVE"
            summary_file.write_text(json.dumps(data))
            changed = self._run("--paper-run-dir", str(acceptance["run_dir"]))
            self.assertEqual(changed["paper_acceptance"]["status"], "EVIDENCE_MISMATCH")

    def test_report_output_is_no_clobber_and_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            report = self._run("--output", str(path))
            self.assertEqual(json.loads(path.read_text())["mode"], "READ_ONLY_LOCAL_DIAGNOSTICS")
            self.assertEqual(report["mode"], "READ_ONLY_LOCAL_DIAGNOSTICS")
            contents = path.read_bytes()
            retry = self._run("--output", str(path), success=False)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(path.read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
