param(
    [Parameter(Mandatory = $true)]
    [string]$SelectionPath,
    [Parameter(Mandatory = $true)]
    [string]$TranscriptPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe"
$env:TDX_INTERACTIVE_VISIBLE_WORKER = "1"
Set-Location -LiteralPath $projectRoot
Start-Transcript -LiteralPath $TranscriptPath -Force
try {
    & $pythonExe -u "main.py" --interactive-selection-file $SelectionPath
    $workerExitCode = $LASTEXITCODE
} finally {
    Stop-Transcript
}
Write-Host "Worker exit code: $workerExitCode"
Read-Host "Press Enter to close this validation window"
exit $workerExitCode
