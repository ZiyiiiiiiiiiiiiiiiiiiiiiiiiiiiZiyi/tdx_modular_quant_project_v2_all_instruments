# External Data Runbook

## One-Click Completion After VPN Is Disabled

Run this command first:

```powershell
& "E:\ForANACONDA\python.exe" auto_complete_after_vpn.py
```

It performs these stages automatically:

1. Check BaoStock DNS and `public-api.baostock.com:10030`.
2. Resume and publish BaoStock adjustment-factor and dividend data.
3. Publish TDX finance market-cap history.
4. Rebuild the full feature parquet.
5. Regenerate and backtest every configured strategy in fresh low-memory subprocesses.
6. Validate that all strategy batches use the current execution-model version and publish the complete summary.
7. Rebuild formal-readiness artifacts, roadmap audit, and mainline verification.

Progress is stored in:

```text
data/reports/auto_complete_after_vpn_state.json
```

If the process stops, run the same command again. Completed stages are skipped.
To deliberately rebuild everything from the beginning:

```powershell
& "E:\ForANACONDA\python.exe" auto_complete_after_vpn.py --reset-state
```

Preview the commands without running them:

```powershell
& "E:\ForANACONDA\python.exe" auto_complete_after_vpn.py --dry-run
```

## Interpreter Split

Use `E:\ForANACONDA\python.exe` for the main pipeline and offline verification.

The currently installed BaoStock and Mootdx packages are in:

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe"
```

Use that interpreter for external reference-data fetching unless the packages are installed into `E:\ForANACONDA`.

## VPN Diagnosis

Run:

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" diagnose_external_data_environment.py
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" fetch_baostock_reference_data.py --limit 1 --batch-size 1 --request-delay-seconds 0 --batch-delay-seconds 0 --login-retries 1 --login-retry-delay-seconds 0
```

If DNS is healthy but `public-api.baostock.com:10030` reports `TCP_FAILED`, disable VPN or proxy software and rerun the diagnosis and single-symbol validation fetch before starting the full resume command.

## Full Resume Fetch

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" fetch_baostock_reference_data.py --publish --resume --batch-size 50 --request-delay-seconds 0.6 --batch-delay-seconds 3 --login-retries 5 --login-retry-delay-seconds 8
```

The TDX finance market-cap path can run offline from already downloaded ZIP files:

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" fetch_market_cap_history.py --source tdx_finance --use-existing-reports-only --publish
```
