"""Prove that an abruptly killed offline parent releases the OS lock and is reconciled."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from workflow_os.offline_run_lock import exclusive_paper_run_lock
from workflow_os_offline_windows_runner import _reconcile


class AbruptProcessRecoveryTests(unittest.TestCase):
    def test_killed_parent_releases_lock_and_reconciles_started_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runtime"
            ready = root / "ready.flag"
            code = (
                "import sys,time; from pathlib import Path;"
                "sys.path.insert(0,sys.argv[2]); sys.path.insert(0,sys.argv[3]);"
                "from workflow_os.offline_run_lock import exclusive_paper_run_lock;"
                "from workflow_os_offline_windows_runner import _audit;"
                "root=Path(sys.argv[1]);"
                "\nwith exclusive_paper_run_lock(root/'scheduler'):\n"
                " root.mkdir(parents=True,exist_ok=True)\n"
                " _audit(root,run_id='abrupt-paper-parent',status='STARTED')\n"
                " (root/'ready.flag').write_text('locked',encoding='utf-8')\n"
                " time.sleep(120)\n"
            )
            allowed = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
            env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
            proc = subprocess.Popen(
                [sys.executable, "-B", "-c", code, str(root), str(ROOT / "src"), str(ROOT / "scripts")],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.is_file() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not ready.is_file():
                    self.fail("child never acquired lock before deadline; child_exit=" + str(proc.poll()))
                with self.assertRaisesRegex(RuntimeError, "overlap denied"):
                    with exclusive_paper_run_lock(root / "scheduler"):
                        pass
                proc.kill()
                proc.wait(timeout=5)
                with exclusive_paper_run_lock(root / "scheduler"):
                    self.assertEqual(_reconcile(root), 1)
                    self.assertEqual(_reconcile(root), 0)
                records = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual([record["status"] for record in records], ["STARTED", "INTERRUPTED"])
                self.assertEqual([record["run_id"] for record in records], ["abrupt-paper-parent"] * 2)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stderr is not None:
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
