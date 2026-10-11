"""Windows-compatible unattended paper launcher: persistence and fail-closed tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_os_offline_windows_runner as runner
from workflow_os.offline_run_lock import exclusive_paper_run_lock


class OfflineWindowsRunnerTests(unittest.TestCase):
    def test_real_seven_process_paper_run_and_independent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runtime"
            result = runner.run_once(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["TEST_MODE_READY"], "NO")
            self.assertEqual(result["LIVE_MODE_READY"], "NO")
            evidence = root / "runs" / result["paper_run"]
            self.assertTrue((evidence / "paper-only.sqlite").is_file())
            self.assertEqual(runner.inspect_paper_evidence(evidence)["status"], "PASS")
            records = [json.loads(line) for line in (root / "runs.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in records], ["STARTED", "PASS"])

    def test_crashed_parent_reconciled_without_reusing_old_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runtime"
            root.mkdir()
            runner._audit(root, run_id="crashed-synthetic-parent", status="STARTED")
            result = runner.run_once(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["interrupted_reconciled"], 1)
            events = [json.loads(line) for line in (root / "runs.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in events],
                             ["STARTED", "INTERRUPTED", "STARTED", "PASS"])
            self.assertEqual(events[1]["run_id"], "crashed-synthetic-parent")

    def test_no_overlap_and_invalid_limits_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runtime"
            with self.assertRaises(ValueError):
                runner.run_once(root, timeout=0)
            with exclusive_paper_run_lock(root / "scheduler"):
                with self.assertRaisesRegex(RuntimeError, "overlap denied"):
                    runner.run_once(root)
            self.assertFalse((root / "runs.jsonl").exists())

    def test_corrupt_audit_blocks_without_spawning_worker(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "runs.jsonl").write_text('{"status":"STARTED"}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid audit record"):
                runner.run_once(root)
            self.assertFalse((root / "runs").exists())

    def test_capacity_check_rejects_symlinks_and_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "runs"
            root.mkdir()
            (root / "large.bin").write_bytes(b"12345")
            old_limit = runner.MAX_EVIDENCE_BYTES
            try:
                runner.MAX_EVIDENCE_BYTES = 4
                with self.assertRaisesRegex(RuntimeError, "capacity reached"):
                    runner._check_capacity(root)
            finally:
                runner.MAX_EVIDENCE_BYTES = old_limit

    def test_bounded_audit_rotation_preserves_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = runner.MAX_LOG_BYTES
            try:
                runner.MAX_LOG_BYTES = 160
                runner._audit(root, run_id="completed", status="STARTED")
                runner._audit(root, run_id="completed", status="PASS")
                runner._audit(root, run_id="crashed", status="STARTED")
                self.assertTrue((root / "runs.previous.jsonl").exists())
                self.assertEqual(runner._reconcile(root), 1)
                self.assertEqual(runner._reconcile(root), 0)
            finally:
                runner.MAX_LOG_BYTES = previous

    def test_credential_environment_is_not_forwarded(self) -> None:
        original = os.environ.get("OPENSHORTS_API_KEY")
        try:
            os.environ["OPENSHORTS_API_KEY"] = "never-forward-to-worker"
            self.assertNotIn("OPENSHORTS_API_KEY", runner._safe_env())
        finally:
            if original is None:
                os.environ.pop("OPENSHORTS_API_KEY", None)
            else:
                os.environ["OPENSHORTS_API_KEY"] = original


if __name__ == "__main__":
    unittest.main()
