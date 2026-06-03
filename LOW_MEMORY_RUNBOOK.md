# Low-memory runbook

Use the main Anaconda interpreter from the project directory:

```powershell
cd /d "F:\通信达量化\tdx_modular_quant_project_v2_all_instruments"
& "E:\ForANACONDA\python.exe" --version
```

Recommended main entry point:

```powershell
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --batch-size 1 --batch-index 0
```

Then increase `--batch-index`:

```powershell
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --batch-size 1 --batch-index 1
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --batch-size 1 --batch-index 2
```

If memory is stable, use four strategies per batch:

```powershell
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --batch-size 4 --batch-index 0
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --batch-size 4 --batch-index 1
```

To run through data checks/features first, remove `--skip-data-steps`. This can take much longer and use more memory:

```powershell
& "E:\ForANACONDA\python.exe" main.py --low-memory --mode all --batch-size 1 --batch-index 0
```

Quick smoke check through `main.py`:

```powershell
& "E:\ForANACONDA\python.exe" main.py --low-memory --skip-data-steps --mode all --only kline_shape
```

Spyder one-click run:

Open this file in Spyder and press Run:

```text
F:\通信达量化\tdx_modular_quant_project_v2_all_instruments\spyder_run_all_low_memory.py
```

Default settings are safe for about 5GB usable memory:

```python
BATCH_SIZE = 1
SKIP_DATA_STEPS = True
START_BATCH_INDEX = 0
RESUME = False
```

If a run stops midway, set `START_BATCH_INDEX` to the next unfinished batch and run the file again.  If you want to skip outputs that already exist, set `RESUME = True`.

Fallback standalone batch runner:

```powershell
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode all --batch-size 1 --batch-index 0
```

Recommended settings for this machine:

- safest: `--batch-size 1`
- upper bound: `--batch-size 4`
- run batches sequentially: increment `--batch-index` from `0`
- resume finished outputs: add `--resume`

Examples:

```powershell
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode select --batch-size 4 --batch-index 0
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode select --batch-size 4 --batch-index 1
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode backtest --batch-size 4 --batch-index 0
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode all --only momentum
```

For ML-heavy runs, use one strategy at a time:

```powershell
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode all --only ml_elasticnet
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode all --only classic_ml_forward_return_short
```

Quick smoke check:

```powershell
& "E:\ForANACONDA\python.exe" run_strategy_batches.py --mode select --sources rule --smoke
```
