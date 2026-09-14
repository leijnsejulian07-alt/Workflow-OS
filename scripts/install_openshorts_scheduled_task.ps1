param(
    [string]$TaskName = "Workflow OS - OpenShorts",
    [ValidateRange(5, 60)]
    [int]$IntervalMinutes = 5,
    [string]$PythonExe = "python.exe",
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw "This installer is only supported on Windows."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runner = (Resolve-Path (Join-Path $PSScriptRoot "run_openshorts_once.ps1")).Path
$pythonCommand = Get-Command $PythonExe -ErrorAction Stop
$pythonPath = $pythonCommand.Source
if (-not [System.IO.Path]::IsPathFullyQualified($pythonPath) -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python executable must resolve to an existing absolute file path."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing -and -not $ReplaceExisting) {
    throw "Scheduled task already exists. Re-run with -ReplaceExisting only after reviewing the existing task."
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($null -eq $identity -or [string]::IsNullOrWhiteSpace($identity.Name)) {
    throw "Unable to resolve the current Windows identity."
}

$escapedRunner = $runner.Replace('"', '""')
$escapedPython = $pythonPath.Replace('"', '""')
$arguments = "-NoProfile -NonInteractive -File `"$escapedRunner`" -PythonExe `"$escapedPython`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Runs one bounded Workflow OS OpenShorts revenue-worker cycle. Secrets remain runtime-only environment configuration."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force:$ReplaceExisting | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($registered.Settings.MultipleInstances -ne "IgnoreNew") {
    throw "Scheduled task registration failed the no-overlap invariant."
}

Write-Output "Registered '$TaskName' every $IntervalMinutes minute(s) with no overlapping instances."
