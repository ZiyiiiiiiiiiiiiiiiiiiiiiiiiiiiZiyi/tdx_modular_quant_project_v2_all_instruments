Strategy selection patch

Put this file into your current project:

    functions/strategy_selection.py

Then you can test it directly in Spyder:

    runfile("F:/通信达量化/tdx_modular_quant_project_v2_all_instruments/functions/strategy_selection.py")

Or import it in main.py:

    from functions.strategy_selection import run_strategy_selection

Add this switch:

    RUN_STEP_4_STRATEGY_SELECTION = True

Then add this in main():

    if RUN_STEP_4_STRATEGY_SELECTION:
        print("\n========== STEP 4: Strategy selection ==========")
        run_strategy_selection(
            score_col="score_mom_lowvol",
            top_n=5,
            freq="ME",
            include_types=("stock", "etf_fund"),
        )

Output:
    data/processed/strategy_selection.parquet
    data/reports/strategy_selection_summary.csv

Meaning:
    For every rebalance date, it selects top N instruments by score.
