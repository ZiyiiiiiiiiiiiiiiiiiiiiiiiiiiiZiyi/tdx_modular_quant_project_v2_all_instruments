# -*- coding: utf-8 -*-
"""
View and export strategy selection result.
"""

import pandas as pd

from config import PROCESSED_DIR, REPORT_DIR


def view_strategy_selection(
    export_excel=True,
    print_rows=30,
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

    selection_file = PROCESSED_DIR / "strategy_selection.parquet"

    if not selection_file.exists():
        raise FileNotFoundError(
            f"Strategy selection file not found: {selection_file}"
        )

    sel = pd.read_parquet(selection_file)

    print("\n========== Strategy Selection View ==========")
    print("Selection file:", selection_file)
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

    if "rebalance_date" in sel.columns:
        dates = sel["rebalance_date"].drop_duplicates().sort_values()

        print("\nLatest rebalance dates:")
        print(dates.tail(10))

        latest_date = dates.iloc[-1]

        print(f"\nLatest selection on {latest_date}:")
        print(sel[sel["rebalance_date"] == latest_date])

    if export_excel:
        output_excel = REPORT_DIR / "strategy_selection_view.xlsx"
        output_csv = REPORT_DIR / "strategy_selection_view.csv"

        sel.to_excel(output_excel, index=False)
        sel.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print("\nSaved Excel:", output_excel)
        print("Saved CSV:", output_csv)

    print("=============================================")

    return sel