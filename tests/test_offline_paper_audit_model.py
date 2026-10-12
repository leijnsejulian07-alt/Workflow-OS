"""Deterministic model checks for bounded synthetic audit rotation.

No external providers, credentials, networking, or Windows scheduler required.
"""
from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import workflow_os_offline_windows_runner as runner


class AuditModelTests(unittest.TestCase):
    def test_rotation_never_silently_forgets_unfinished_runs(self) -> None:
        checked = 0
        blocked = 0
        for seed in range(150):
            rng = random.Random(seed)
            with tempfile.TemporaryDirectory() as folder, patch.object(runner, "MAX_LOG_BYTES", 256):
                root = Path(folder)
                pending: set[str] = set()
                for step in range(70):
                    if pending and rng.random() < 0.68:
                        run_id = rng.choice(sorted(pending))
                        status = rng.choice(("PASS", "FAIL", "INTERRUPTED"))
                    else:
                        run_id = f"model-{seed}-{step}"
                        status = "STARTED"
                    try:
                        runner._audit(root, run_id=run_id, status=status)
                    except RuntimeError as exc:
                        self.assertRegex(str(exc), "audit rotation would discard unresolved run|audit recovery capacity reached|oversized audit ledger")
                        blocked += 1
                        break  # A blocked append must never be counted as persisted.
                    if status == "STARTED":
                        pending.add(run_id)
                    else:
                        pending.discard(run_id)
                    actual, _ = runner._pending_audit_runs(root)
                    self.assertEqual(actual, pending, f"seed={seed} step={step}")
                    checked += 1
        self.assertGreaterEqual(checked, 1000)
        self.assertGreater(blocked, 0)


if __name__ == "__main__":
    unittest.main()
