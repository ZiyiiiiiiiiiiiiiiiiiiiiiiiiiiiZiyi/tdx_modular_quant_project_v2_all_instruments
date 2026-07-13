"""Combined PIT fundamental composite factors."""
from __future__ import annotations

import pandas as pd

from functions.factors.cashflow_quality_factors import append_cashflow_quality_factors
from functions.factors.growth_quality_factors import append_growth_quality_factors
from functions.factors.profitability_quality_factors import append_profitability_quality_factors


FUNDAMENTAL_COMPOSITE_COLUMNS = [
    "quality_growth_combo",
    "value_quality_combo",
    "peg_proxy",
    "profit_cashflow_combo",
    "defensive_quality_score",
    "fundamental_risk_score",
]


def append_fundamental_composite_factors(df: pd.DataFrame) -> pd.DataFrame:
    frame = append_growth_quality_factors(df)
    frame = append_profitability_quality_factors(frame)
    frame = append_cashflow_quality_factors(frame)
    value_rank = _rank(frame.get("fcf_yield")) + _rank(frame.get("growth_value_combo"))
    quality_rank = _rank(frame.get("piotroski_f_score_proxy")) + _rank(frame.get("cash_profit_quality"))
    growth_rank = _rank(frame.get("growth_consistency")) + _rank(frame.get("growth_surprise"))
    frame["quality_growth_combo"] = quality_rank + growth_rank
    frame["value_quality_combo"] = value_rank + quality_rank
    frame["peg_proxy"] = frame.get("growth_value_combo")
    frame["profit_cashflow_combo"] = _rank(frame.get("roe_ttm_ind_neutral")) + _rank(frame.get("ocf_to_net_profit"))
    frame["defensive_quality_score"] = quality_rank + _rank(frame.get("cashflow_stability")) + _rank(frame.get("roe_vol_neg"))
    frame["fundamental_risk_score"] = -_rank(frame.get("accruals_neg")) - _rank(frame.get("capex_intensity_neg"))
    return frame


def _rank(values) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").rank(pct=True)
