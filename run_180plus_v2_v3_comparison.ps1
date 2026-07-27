param(
    [ValidateRange(180, 2000)]
    [int]$Days = 180,
    [string]$StartDate = "2024-01-01",
    [string]$EndDate = "2024-12-31",
    [string]$CabinetRunId = "pruned_run20260714_184846_581132_20260715_230524",
    [ValidateRange(0.0, 1.0)]
    [double]$MonthlyLgbmMaximumWeight = 0.20,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Python = "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe"
$Project = $PSScriptRoot

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python interpreter not found: $Python"
}
if (-not (Test-Path -LiteralPath $Project -PathType Container)) {
    throw "Project directory not found: $Project"
}
Set-Location -LiteralPath $Project

$CabinetPath = Join-Path $Project "results\factor_cabinet\$CabinetRunId\factor_cabinet.json"
if (-not (Test-Path -LiteralPath $CabinetPath -PathType Leaf)) {
    throw "Factor cabinet not found: $CabinetPath"
}

& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Python preflight failed with exit code $LASTEXITCODE" }

$Common = @(
    "main.py",
    "--governance",
    "--governance-start-date", $StartDate,
    "--governance-end-date", $EndDate,
    "--governance-max-days", "$Days",
    "--governance-universe", "hs300_csi500_a500_strict",
    "--governance-variant", "governance_layer_validation",
    "--governance-control-mode", "factor_only",
    "--factor-source", "selected_factor_cabinet",
    "--factor-cabinet-run-id", $CabinetRunId,
    "--pit-mode", "research",
    "--capital-profile", "small_capital_branch",
    "--initial-cash", "20000",
    "--max-positions", "5",
    "--capital-usage-mode", "allow_cash",
    "--no-governance-shadow-portfolios",
    "--no-live-monitor"
)

$Experiments = @(
    @{
        Name = "mainline_v2"
        Extra = @("--strategy-logic-version", "mainline_v2")
    },
    @{
        Name = "mainline_v3_cabinet_native"
        Extra = @("--strategy-logic-version", "mainline_v3_cabinet_native")
    },
    @{
        Name = "mainline_v3_reliability_weighted"
        Extra = @("--strategy-logic-version", "mainline_v3_reliability_weighted")
    },
    @{
        Name = "mainline_v3_monthly_lgbm_hybrid"
        Extra = @(
            "--strategy-logic-version", "mainline_v3_monthly_lgbm_hybrid",
            "--monthly-lgbm-maximum-weight", "$MonthlyLgbmMaximumWeight"
        )
    }
)

foreach ($Experiment in $Experiments) {
    $Arguments = @($Common) + @($Experiment.Extra)
    if ($DryRun) {
        Write-Host "[DRY RUN] $Python $($Arguments -join ' ')"
        continue
    }
    Write-Host "Running fixed comparison arm: $($Experiment.Name) ($Days days)..."
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$($Experiment.Name) failed with exit code $LASTEXITCODE"
    }
}

if ($DryRun) {
    Write-Host "Dry run complete: four fixed comparison arms validated; no backtest was started."
} else {
    Write-Host "Four fixed runs completed: v2, Cabinet Native, v3.1 reliability, and v3 dual-horizon monthly LightGBM."
}
