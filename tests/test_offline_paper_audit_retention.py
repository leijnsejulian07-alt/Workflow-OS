"""Bounded audit rotation must preserve crash recovery without silent loss."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_os_offline_windows_runner as runner


class AuditRetentionTests(unittest.TestCase):
    def test_rotation_blocks_loss_then_reconciles_orphan(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "MAX_LOG_BYTES", 160):
            root = Path(tmp)
            runner._audit(root, run_id="orphan", status="STARTED")
            runner._audit(root, run_id="completed", status="STARTED")
            runner._audit(root, run_id="completed", status="PASS")
            runner._audit(root, run_id="new", status="STARTED")
            with self.assertRaisesRegex(RuntimeError, "discard unresolved run"):
                runner._audit(root, run_id="new", status="PASS")
            self.assertEqual(runner._reconcile(root), 2)
            self.assertEqual(runner._reconcile(root), 0)
            records = [json.loads(line) for name in ("runs.previous.jsonl", "runs.jsonl")
                       for line in (root / name).read_text(encoding="utf-8").splitlines()]
            self.assertIn(("orphan", "INTERRUPTED"),
                          {(x["run_id"], x["status"]) for x in records})

    def test_recovery_capacity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "MAX_LOG_BYTES", 160):
            root = Path(tmp)
            prev = root / "runs.previous.jsonl"
            prev.write_text(json.dumps({"run_id": "orphan", "status": "STARTED"}) + "\n")
            cur = root / "runs.jsonl"
            cur.write_text("".join(json.dumps({"run_id": f"done-{i}", "status": state}) + "\n"
                                   for i in range(3) for state in ("STARTED", "PASS")))
            original = prev.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "oversized audit ledger|capacity reached"):
                runner._audit(root, run_id="orphan", status="INTERRUPTED")
            self.assertEqual(prev.read_bytes(), original)

    def test_corrupt_previous_blocks_rotation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "MAX_LOG_BYTES", 160):
            root = Path(tmp)
            (root / "runs.previous.jsonl").write_text("not json\n")
            (root / "runs.jsonl").write_text(json.dumps({"run_id": "x", "status": "STARTED"}) * 5)
            with self.assertRaises(json.JSONDecodeError):
                runner._audit(root, run_id="x", status="PASS")

    def test_completed_records_rotate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "MAX_LOG_BYTES", 160):
            root = Path(tmp)
            for i in range(6):
                runner._audit(root, run_id=f"done-{i}", status="STARTED")
                runner._audit(root, run_id=f"done-{i}", status="PASS")
            self.assertEqual(runner._reconcile(root), 0)
            self.assertLess((root / "runs.jsonl").stat().st_size, 320)


if __name__ == "__main__":
    unittest.main()
