param(
    [string]$PythonExe = "python.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$srcPath = Join-Path $repoRoot "src"
$previousPythonPath = $env:PYTHONPATH
$pushed = $false

try {
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $srcPath
    }
    else {
        $env:PYTHONPATH = "$srcPath;$previousPythonPath"
    }

    Push-Location $repoRoot
    $pushed = $true

    & $PythonExe -m workflow_os.openshorts_status_runtime_entrypoint
    $statusExitCode = $LASTEXITCODE
    if ($statusExitCode -ne 0) {
        throw "OpenShorts terminal reconciliation exited with code $statusExitCode"
    }

    & $PythonExe -m workflow_os.openshorts_runtime_entrypoint
    $runtimeExitCode = $LASTEXITCODE
    if ($runtimeExitCode -ne 0) {
        throw "OpenShorts runtime exited with code $runtimeExitCode"
    }
}
finally {
    if ($pushed) {
        Pop-Location
    }
    $env:PYTHONPATH = $previousPythonPath
}
