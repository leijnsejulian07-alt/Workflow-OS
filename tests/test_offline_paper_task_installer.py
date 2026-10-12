"""Regression checks for the synthetic-only Windows Task Scheduler installer."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install_workflow_os_offline_paper_task.ps1"


class OfflinePaperTaskInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = INSTALLER.read_text(encoding="utf-8")

    def test_powershell_51_compatible_path_validation(self) -> None:
        self.assertIn("#requires -Version 5.1", self.source)
        self.assertNotIn("IsPathFullyQualified", self.source)
        self.assertIn("[IO.Path]::IsPathRooted($pythonPath)", self.source)
        self.assertIn("[IO.Path]::GetFullPath($pythonPath)", self.source)
        self.assertIn("Test-Path -LiteralPath $pythonPath -PathType Leaf", self.source)

    def test_supported_python_version_is_required(self) -> None:
        self.assertIn("sys.version_info >= (3, 12)", self.source)
        self.assertIn("Python 3.12+ with sqlite3 is required", self.source)

    def test_installer_remains_synthetic_and_fail_closed(self) -> None:
        for guard in (
            "https://github.com/leijnsejulian07-alt/Workflow-OS.git",
            "git -C $repoRoot status --porcelain=v1",
            "Task already exists; refusing to replace any scheduled task.",
            "SupportsShouldProcess = $true",
            "-LogonType S4U -RunLevel Limited",
            "-MultipleInstances IgnoreNew",
            "-ExecutionTimeLimit (New-TimeSpan -Minutes 10)",
            "workflow_os_offline_windows_runner.py",
        ):
            with self.subTest(guard=guard):
                self.assertIn(guard, self.source)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                         "Windows PowerShell 5.1 parser unavailable")
    def test_installer_parses_with_windows_powershell(self) -> None:
        command = (
            "$tokens=$null;$errors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "'" + str(INSTALLER).replace("'", "''") + "',"
            "[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){$errors|Out-String|Write-Error;exit 1}"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
