#requires -Version 5.1
<#
Install an hourly, strictly synthetic Workflow OS paper acceptance task.
Never installs a live provider, publishing, payment, or trading workflow.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Low')]
param(
    [string]$TaskName = 'Workflow OS - Offline Paper Acceptance',
    [string]$PythonExe = 'python.exe'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows Task Scheduler is required.'
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runner = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'workflow_os_offline_windows_runner.py')).Path
$remote = (& git -C $repoRoot remote get-url origin)
if ($LASTEXITCODE -ne 0 -or $remote.Trim() -ne 'https://github.com/leijnsejulian07-alt/Workflow-OS.git') {
    throw 'Repository origin does not match the authorized Workflow OS repository.'
}
$branch = (& git -C $repoRoot branch --show-current)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
    throw 'A named Workflow OS branch is required.'
}
$changes = @(& git -C $repoRoot status --porcelain=v1 --untracked-files=normal)
if ($LASTEXITCODE -ne 0 -or ($changes | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
    throw 'Refusing to install from a dirty worktree; use a clean isolated checkout.'
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    throw 'Task already exists; refusing to replace any scheduled task.'
}

$pythonCommand = Get-Command $PythonExe -CommandType Application -ErrorAction Stop
$pythonPath = $pythonCommand.Source
if (-not [IO.Path]::IsPathRooted($pythonPath) -or [IO.Path]::GetFullPath($pythonPath) -ne $pythonPath -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Python must resolve to an existing absolute executable.'
}
& $pythonPath -B -c 'import sqlite3,sys; assert sys.version_info >= (3, 12)'
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12+ with sqlite3 is required.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($null -eq $identity -or [string]::IsNullOrWhiteSpace($identity.Name)) {
    throw 'Could not resolve Windows identity.'
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw 'LOCALAPPDATA must be available for the current identity.'
}
$dataDir = Join-Path $env:LOCALAPPDATA 'WorkflowOS\offline-paper'
$arguments = ('-B "{0}" --data-dir "{1}"' -f $runner.Replace('"', '""'), $dataDir.Replace('"', '""'))
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Synthetic offline Workflow OS paper acceptance only. No network credentials or live side effects.'

if ($PSCmdlet.ShouldProcess($TaskName, 'Register hourly synthetic offline paper task (S4U, no overlap)')) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop | Out-Null
    $registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($registered.Settings.MultipleInstances -ne 'IgnoreNew' -or
        $registered.Principal.LogonType -ne 'S4U' -or
        $registered.Actions.Execute -ne $pythonPath -or
        $registered.Actions.Arguments -ne $arguments) {
        throw 'Registered task failed post-install safety verification.'
    }
    Write-Output ('INSTALLED: {0}; branch={1}; synthetic-only; hourly; no overlap.' -f $TaskName, $branch.Trim())
} else {
    Write-Output ('NOT INSTALLED (WhatIf): {0}; branch={1}; synthetic-only; hourly.' -f $TaskName, $branch.Trim())
}
