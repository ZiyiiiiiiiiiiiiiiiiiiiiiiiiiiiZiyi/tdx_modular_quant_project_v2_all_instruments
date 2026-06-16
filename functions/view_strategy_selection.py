# -*- coding: utf-8 -*-
"""
View and export strategy selection result.
"""

import pandas as pd

from config import PROCESSED_DIR, REPORT_DIR


def view_strategy_selection(
    export_excel=True,
    print_rows=30,
    strategy_names=None,
):
    """
    Load strategy selection result and export it for viewing.

    Parameters
    ----------
    export_excel : bool
        If True, export strategy selection to Excel.
    print_rows : int
        Number of rows to print in console.
    """

    if strategy_names is None:
        files = sorted(
            path for path in PROCESSED_DIR.glob("*.parquet")
            if path.name not in {
                "tdx_daily_raw.parquet",
                "tdx_daily_clean.parquet",
                "tdx_daily_features.parquet",
                "strategy_selection.parquet",
            }
        )
    else:
        files = [PROCESSED_DIR / f"{name}.parquet" for name in strategy_names]

    missing = [path for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Strategy selection file not found: "
            + ", ".join(str(path) for path in missing)
        )
    if not files:
        raise FileNotFoundError(f"No strategy selection parquet files found in {PROCESSED_DIR}")

    frames = []
    for selection_file in files:
        one = pd.read_parquet(selection_file)
        if "strategy_name" in one.columns:
            one = one.drop(columns=["strategy_name"])
        one.insert(0, "strategy_name", selection_file.stem)
        frames.append(one)

    sel = pd.concat(frames, ignore_index=True)

    print("\n========== Strategy Selection View ==========")
    print("Selection files:", [str(path) for path in files])
    print("Shape:", sel.shape)
    print("Columns:", sel.columns.tolist())

    print("\nHead:")
    print(sel.head(print_rows))

    print("\nTail:")
    print(sel.tail(print_rows))

    if "instrument_type" in sel.columns:
        print("\nInstrument type count:")
        print(sel["instrument_type"].value_counts())

    if "symbol" in sel.columns:
        print("\nMost selected symbols:")
        print(sel["symbol"].value_counts().head(30))

    if "sector_parent" in sel.columns:
        print("\nSector parent count:")
        print(sel["sector_parent"].value_counts().head(20))

    if "sector_branch" in sel.columns:
        print("\nSector branch count:")
        print(sel["sector_branch"].value_counts().head(30))

    if "rebalance_date" in sel.columns:
        dates = sel["rebalance_date"].drop_duplicates().sort_values()

        print("\nLatest rebalance dates:")
        print(dates.tail(10))

        if not dates.empty:
            latest_date = dates.iloc[-1]

            print(f"\nLatest selection on {latest_date}:")
            print(sel[sel["rebalance_date"] == latest_date])

            # Last-day selection summary with scores for all strategies
            _print_last_day_summary(sel, latest_date)

    if export_excel:
        output_excel = REPORT_DIR / "strategy_selection_view.xlsx"
        output_csv = REPORT_DIR / "strategy_selection_view.csv"

        sel.to_excel(output_excel, index=False)
        sel.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print("\nSaved Excel:", output_excel)
        print("Saved CSV:", output_csv)

    # Export last-day selection summary
    if "rebalance_date" in sel.columns:
        dates = sel["rebalance_date"].drop_duplicates().sort_values()
        if not dates.empty:
            latest_date = dates.iloc[-1]
            _export_last_day_summary(sel, latest_date)

    print("=============================================")

    return sel


def _print_last_day_summary(sel, latest_date):
    """Print a consolidated summary of all strategies' last-day selections with scores."""
    last_day = sel[sel["rebalance_date"] == latest_date].copy()
    if last_day.empty:
        return

    # Determine score column
    score_col = "score" if "score" in last_day.columns else "selection_score"
    if score_col not in last_day.columns:
        print(f"\n[WARN] No score column found in last-day selection.")
        return

    print(f"\n========== Last Day Selection Summary ({latest_date}) ==========")

    # Per-strategy summary
    strategies = last_day["strategy_name"].drop_duplicates().sort_values()
    for strategy in strategies:
        strat_data = last_day[last_day["strategy_name"] == strategy].copy()
        if strat_data.empty:
            continue
        strat_data = strat_data.sort_values(score_col, ascending=False)
        count = len(strat_data)
        avg_score = strat_data[score_col].mean()
        print(f"\n--- {strategy} ({count} stocks, avg score: {avg_score:.4f}) ---")
        display_cols = ["symbol", score_col]
        if "rank" in strat_data.columns:
            display_cols.insert(1, "rank")
        if "sector_parent" in strat_data.columns:
            display_cols.append("sector_parent")
        if "weight" in strat_data.columns:
            display_cols.append("weight")
        available = [c for c in display_cols if c in strat_data.columns]
        print(strat_data[available].to_string(index=False))

    # Cross-strategy: which stocks appear in multiple strategies
    stock_counts = last_day.groupby("symbol").agg(
        n_strategies=("strategy_name", "nunique"),
        strategies=("strategy_name", lambda x: ", ".join(sorted(x.unique()))),
        avg_score=(score_col, "mean"),
        max_score=(score_col, "max"),
    ).reset_index()
    stock_counts = stock_counts.sort_values(["n_strategies", "avg_score"], ascending=[False, False])

    multi = stock_counts[stock_counts["n_strategies"] > 1]
    if not multi.empty:
        print(f"\n========== Stocks Selected by Multiple Strategies ({latest_date}) ==========")
        print(multi.to_string(index=False))

    print(f"\n========== All Selected Stocks Ranked by Score ({latest_date}) ==========")
    all_stocks = last_day.groupby("symbol").agg(
        n_strategies=("strategy_name", "nunique"),
        strategies=("strategy_name", lambda x: ", ".join(sorted(x.unique()))),
        avg_score=(score_col, "mean"),
        max_score=(score_col, "max"),
        min_score=(score_col, "min"),
    ).reset_index()
    all_stocks = all_stocks.sort_values("avg_score", ascending=False)
    print(all_stocks.to_string(index=False))


def _export_last_day_summary(sel, latest_date):
    """Export last-day selection summary to CSV."""
    last_day = sel[sel["rebalance_date"] == latest_date].copy()
    if last_day.empty:
        return

    score_col = "score" if "score" in last_day.columns else "selection_score"
    if score_col not in last_day.columns:
        return

    # Per-stock summary across strategies
    all_stocks = last_day.groupby("symbol").agg(
        n_strategies=("strategy_name", "nunique"),
        strategies=("strategy_name", lambda x: ", ".join(sorted(x.unique()))),
        avg_score=(score_col, "mean"),
        max_score=(score_col, "max"),
        min_score=(score_col, "min"),
    ).reset_index()
    all_stocks = all_stocks.sort_values("avg_score", ascending=False)

    # Add sector info if available
    if "sector_parent" in last_day.columns:
        sector_map = last_day.drop_duplicates("symbol").set_index("symbol")["sector_parent"]
        all_stocks["sector_parent"] = all_stocks["symbol"].map(sector_map)

    output_path = REPORT_DIR / f"last_day_selection_{latest_date.date()}.csv"
    all_stocks.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved last-day selection summary: {output_path}")
