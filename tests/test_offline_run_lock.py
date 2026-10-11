"""No-overlap and crash recovery for offline acceptance runs."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from workflow_os.offline_run_lock import exclusive_paper_run_lock


class OfflineRunLockTests(unittest.TestCase):
    def test_second_process_cannot_overlap_and_lock_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with exclusive_paper_run_lock(root) as locked_root:
                self.assertEqual(locked_root, root)
                self.assertTrue((root / ".workflow-os-paper.lock").is_file())
                with self.assertRaisesRegex(RuntimeError, "overlap denied"):
                    with exclusive_paper_run_lock(root):
                        self.fail("second lock acquired unexpectedly")
            # Persistent lock file remains in place, but the kernel lock releases.
            with exclusive_paper_run_lock(root):
                pass

    def test_abrupt_process_exit_releases_os_lock_without_manual_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            code = (
                "import os, sys; "
                "from workflow_os.offline_run_lock import exclusive_paper_run_lock; "
                "with_scope = exclusive_paper_run_lock(sys.argv[1]); "
                "with_scope.__enter__(); "
                "os._exit(17)"
            )
            cp = subprocess.run(
                [sys.executable, "-c", code, str(root)], cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(cp.returncode, 17, msg=cp.stderr)
            with exclusive_paper_run_lock(root):
                self.assertTrue((root / ".workflow-os-paper.lock").is_file())


if __name__ == "__main__":
    unittest.main()
