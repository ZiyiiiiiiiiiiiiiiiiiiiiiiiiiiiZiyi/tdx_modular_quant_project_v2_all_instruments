"""Investment factors derived from PIT balance-sheet and CAPEX metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


INVESTMENT_FACTOR_COLUMNS = [
    "asset_growth_neg", "capex_growth_neg", "capex_to_assets_neg",
]


def append_investment_quality_factors(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    frame = df.copy()
    frame["asset_growth_neg"] = -_num(frame, "asset_growth")
    frame["capex_to_assets_neg"] = -_num(frame, "capex_to_assets")
    frame["capex_growth_neg"] = -_num(frame, "capex_growth")
    return frame


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")
