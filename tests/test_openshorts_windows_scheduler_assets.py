from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_openshorts_once.ps1"
INSTALLER = ROOT / "scripts" / "install_openshorts_scheduled_task.ps1"


class OpenShortsWindowsSchedulerAssetTests(unittest.TestCase):
    def test_runner_reconciles_terminal_jobs_before_one_shot_dispatch(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")
        status_module = "workflow_os.openshorts_status_runtime_entrypoint"
        dispatch_module = "workflow_os.openshorts_runtime_entrypoint"
        self.assertIn(status_module, text)
        self.assertIn(dispatch_module, text)
        self.assertLess(text.index(status_module), text.index(dispatch_module))
        self.assertNotIn("while (", text.lower())
        self.assertNotIn("start-job", text.lower())
        self.assertNotIn("start-process", text.lower())
        self.assertNotIn("OPENSHORTS_API_KEY=", text)
        self.assertNotIn("WORKFLOW_OS_OPENSHORTS_WEBHOOK_SECRET=", text)

    def test_installer_is_bounded_and_prevents_overlap(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("[ValidateRange(5, 60)]", text)
        self.assertIn("-MultipleInstances IgnoreNew", text)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Minutes 15)", text)
        self.assertIn("-LogonType S4U", text)
        self.assertIn("-RunLevel Limited", text)
        self.assertIn("-NonInteractive", text)
        self.assertNotIn("-ExecutionPolicy Bypass", text)
        self.assertNotIn("OPENSHORTS_API_KEY=", text)
        self.assertNotIn("WORKFLOW_OS_OPENSHORTS_WEBHOOK_SECRET=", text)

    def test_existing_task_requires_explicit_replacement_authority(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("[switch]$ReplaceExisting", text)
        self.assertIn("-not $ReplaceExisting", text)
        self.assertIn("-Force:$ReplaceExisting", text)


if __name__ == "__main__":
    unittest.main()
