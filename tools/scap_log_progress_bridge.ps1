param(
    [Parameter(Mandatory = $true)][string]$LogPath,
    [Parameter(Mandatory = $true)][int]$TargetPid,
    [Parameter(Mandatory = $true)][string]$StatePath
)

$ErrorActionPreference = "Stop"
$resolvedLog = [System.IO.Path]::GetFullPath($LogPath)
$resolvedState = [System.IO.Path]::GetFullPath($StatePath)

function Write-State([hashtable]$Payload) {
    $Payload["updated_at"] = (Get-Date).ToString("o")
    $json = $Payload | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText(
        $resolvedState,
        $json,
        [System.Text.UTF8Encoding]::new($false)
    )
}

while ($true) {
    $process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    $latest = Get-Content -LiteralPath $resolvedLog -Tail 120 -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "Governance Backtest:" } |
        Select-Object -Last 1

    if ($latest -and $latest -match "([0-9.]+)% \((\d+)/(\d+)\) \| Elapsed: (.*?) \| Remaining: (.*?) \| Date: ([0-9-]+) \| NAV: ([0-9,]+) \| Holdings: (\d+)") {
        $percent = [double]$matches[1]
        $current = [int]$matches[2]
        $total = [int]$matches[3]
        $elapsed = $matches[4]
        $remaining = $matches[5]
        $date = $matches[6]
        $nav = $matches[7]
        $holdings = $matches[8]
        $command = if ($process) { "stage" } else { "finish" }
        Write-State @{
            command = $command
            title = "SCAP-V1 2025-01 to 2026-05"
            progress_pct = $percent
            step = "governance_backtest"
            message = "$date | NAV $nav | Holdings $holdings"
            detail = "$current / $total days | Elapsed $elapsed | ETA $remaining | PID $TargetPid"
            current = $current
            total = $total
            eta_text = $remaining
            elapsed_text = $elapsed
            target_pid = $TargetPid
        }
    } else {
        Write-State @{
            command = if ($process) { "stage" } else { "finish" }
            title = "SCAP-V1 long window"
            progress_pct = 0.0
            step = "initializing"
            message = "Waiting for progress log"
            detail = "PID $TargetPid"
            target_pid = $TargetPid
        }
    }

    if (-not $process) {
        break
    }
    Start-Sleep -Seconds 5
}
