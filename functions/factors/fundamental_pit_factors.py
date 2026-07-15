"""PIT-safe report-period and daily valuation factor calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.data.pit_level2_store import validate_pit_level2_frame


FLOW_COLUMNS = (
    "revenue", "net_profit", "deducted_net_profit", "gross_profit",
    "operating_profit", "operating_cashflow", "capex",
)
BALANCE_COLUMNS = ("total_assets", "total_equity")

REPORT_FACTOR_COLUMNS = (
    "revenue_ttm", "net_profit_ttm", "deducted_net_profit_ttm",
    "gross_profit_ttm", "operating_profit_ttm", "operating_cashflow_ttm",
    "capex_ttm", "revenue_yoy", "profit_yoy", "revenue_yoy_accel",
    "profit_yoy_accel", "deducted_profit_yoy", "growth_consistency",
    "growth_stability", "growth_surprise", "revenue_profit_sync",
    "roe_ttm", "roa_ttm", "gross_margin_ttm", "operating_margin_ttm",
    "asset_growth", "capex_growth", "capex_to_assets", "ocf_to_net_profit",
    "ocf_to_revenue", "accruals_neg", "cash_profit_quality",
)

DAILY_FUNDAMENTAL_FACTOR_COLUMNS = (
    "earnings_yield_ttm", "book_to_price", "fcf_yield",
    "roe_ttm_ind_neutral", "roa_ttm_ind_neutral", "asset_growth_neg",
    "capex_to_assets_neg", *REPORT_FACTOR_COLUMNS,
)


def prepare_financial_report_factors(reports: pd.DataFrame) -> pd.DataFrame:
    """Replay report revisions and calculate metrics using only then-known rows."""
    if reports is None or reports.empty:
        return pd.DataFrame(columns=[*getattr(reports, "columns", []), *REPORT_FACTOR_COLUMNS])
    audit = validate_pit_level2_frame(reports, table_name="financial_statement_pit")
    failed = audit[~audit["passed"].fillna(False).astype(bool)]
    if not failed.empty:
        detail = "; ".join(f"{row.check}:{row.detail}" for row in failed.itertuples())
        raise ValueError(f"financial_statement_pit validation failed: {detail}")
    data = reports.copy()
    data["symbol"] = data["symbol"].astype(str)
    for column in ("report_period", "known_at", "effective_from"):
        data[column] = pd.to_datetime(data[column], errors="coerce")
    invalid_basis = ~data["period_value_basis"].astype(str).str.lower().isin({"ytd", "quarter"})
    if invalid_basis.any():
        raise ValueError(f"Unsupported period_value_basis rows: {int(invalid_basis.sum())}")
    for column in (*FLOW_COLUMNS, *BALANCE_COLUMNS):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    output_rows: list[dict] = []
    for _, group in data.sort_values(
        ["symbol", "known_at", "report_period", "revision_id"]
    ).groupby("symbol", sort=False):
        known_snapshot: dict[pd.Timestamp, dict] = {}
        for row in group.to_dict("records"):
            revised_period = pd.Timestamp(row["report_period"]).normalize()
            known_snapshot[revised_period] = dict(row)
            current_period = max(known_snapshot)
            current_row = dict(known_snapshot[current_period])
            current_row.update({
                "known_at": row["known_at"],
                "effective_from": row["effective_from"],
                "source": row["source"],
                "source_document_id": row["source_document_id"],
                "revision_id": row["revision_id"],
                "downloaded_at": row["downloaded_at"],
                "revised_report_period": revised_period,
            })
            metrics = _snapshot_metrics(known_snapshot, current_period=current_period)
            output_rows.append({**current_row, **metrics})
    result = pd.DataFrame(output_rows)
    for column in REPORT_FACTOR_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan
    return result.sort_values(["symbol", "known_at", "report_period"]).reset_index(drop=True)


def append_daily_fundamental_factors(frame: pd.DataFrame) -> pd.DataFrame:
    """Add valuation and neutralized quality factors after PIT daily expansion."""
    if frame is None or frame.empty:
        return frame
    data = frame.copy()
    date_col = "date" if "date" in data.columns else "trade_date"
    symbol_col = "symbol" if "symbol" in data.columns else "stock_code"
    if date_col not in data.columns or symbol_col not in data.columns:
        raise ValueError("Daily fundamental factors require symbol/stock_code and date/trade_date")
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    market_cap = _num(data, "market_cap").where(lambda value: value > 0.0)
    equity = _num(data, "total_equity")
    earnings = _num(data, "net_profit_ttm")
    ocf = _num(data, "operating_cashflow_ttm")
    capex = _num(data, "capex_ttm")
    data["earnings_yield_ttm"] = earnings / market_cap
    data["book_to_price"] = equity / market_cap
    data["fcf_yield"] = (ocf - capex) / market_cap
    data["asset_growth_neg"] = -_num(data, "asset_growth")
    data["capex_growth_neg"] = -_num(data, "capex_growth")
    data["capex_to_assets_neg"] = -_num(data, "capex_to_assets")
    data["roe_ttm_ind_neutral"] = _industry_neutral(data, _num(data, "roe_ttm"), date_col)
    data["roa_ttm_ind_neutral"] = _industry_neutral(data, _num(data, "roa_ttm"), date_col)
    return data


def _snapshot_metrics(snapshot: dict[pd.Timestamp, dict], *, current_period: pd.Timestamp) -> dict:
    periods = sorted(period for period in snapshot if period <= current_period)
    single_quarters = {period: _single_quarter_values(snapshot, period) for period in periods}
    current = snapshot[current_period]
    last_four = periods[-4:]
    metrics: dict[str, float] = {}
    for column in FLOW_COLUMNS:
        values = [single_quarters[period].get(column, np.nan) for period in last_four]
        metrics[f"{column}_ttm"] = _sum_complete(values, required=4)
    prior_year_period = _quarter_shift(current_period, -4)
    prior_quarter_period = _quarter_shift(current_period, -1)
    revenue_yoy = _growth(current.get("revenue"), snapshot.get(prior_year_period, {}).get("revenue"))
    profit_yoy = _growth(current.get("net_profit"), snapshot.get(prior_year_period, {}).get("net_profit"))
    deducted_profit_yoy = _growth(
        current.get("deducted_net_profit"),
        snapshot.get(prior_year_period, {}).get("deducted_net_profit"),
    )
    prior_revenue_yoy = _period_growth(snapshot, prior_quarter_period, "revenue")
    prior_profit_yoy = _period_growth(snapshot, prior_quarter_period, "net_profit")
    metrics["revenue_yoy"] = revenue_yoy
    metrics["profit_yoy"] = profit_yoy
    metrics["deducted_profit_yoy"] = deducted_profit_yoy
    metrics["revenue_yoy_accel"] = _subtract(revenue_yoy, prior_revenue_yoy)
    metrics["profit_yoy_accel"] = _subtract(profit_yoy, prior_profit_yoy)
    yoy_history = [_period_growth(snapshot, period, "revenue") for period in periods[-8:]]
    valid_yoy = pd.Series(yoy_history, dtype=float).dropna()
    metrics["growth_consistency"] = float(valid_yoy.gt(0.0).mean()) if len(valid_yoy) >= 4 else np.nan
    metrics["growth_stability"] = -float(valid_yoy.std(ddof=1)) if len(valid_yoy) >= 4 else np.nan
    metrics["growth_surprise"] = (
        float(revenue_yoy - valid_yoy.iloc[:-1].mean())
        if np.isfinite(revenue_yoy) and len(valid_yoy) >= 5 else np.nan
    )
    metrics["revenue_profit_sync"] = (
        float(np.sign(revenue_yoy) == np.sign(profit_yoy))
        if np.isfinite(revenue_yoy) and np.isfinite(profit_yoy) else np.nan
    )
    assets = _finite(current.get("total_assets"))
    equity = _finite(current.get("total_equity"))
    prior_assets = _finite(snapshot.get(prior_year_period, {}).get("total_assets"))
    prior_equity = _finite(snapshot.get(prior_year_period, {}).get("total_equity"))
    avg_assets = _average_positive(assets, prior_assets)
    avg_equity = _average_positive(equity, prior_equity)
    metrics["roe_ttm"] = _divide(metrics["net_profit_ttm"], avg_equity)
    metrics["roa_ttm"] = _divide(metrics["net_profit_ttm"], avg_assets)
    metrics["gross_margin_ttm"] = _divide(metrics["gross_profit_ttm"], metrics["revenue_ttm"])
    metrics["operating_margin_ttm"] = _divide(metrics["operating_profit_ttm"], metrics["revenue_ttm"])
    metrics["asset_growth"] = _growth(assets, prior_assets)
    prior_capex_ttm = _ttm_flow(snapshot, prior_year_period, "capex")
    metrics["capex_growth"] = _growth(metrics["capex_ttm"], prior_capex_ttm)
    metrics["capex_to_assets"] = _divide(metrics["capex_ttm"], avg_assets)
    metrics["ocf_to_net_profit"] = _divide(metrics["operating_cashflow_ttm"], metrics["net_profit_ttm"])
    metrics["ocf_to_revenue"] = _divide(metrics["operating_cashflow_ttm"], metrics["revenue_ttm"])
    metrics["accruals_neg"] = _divide(
        -(metrics["net_profit_ttm"] - metrics["operating_cashflow_ttm"]),
        avg_assets,
    )
    metrics["cash_profit_quality"] = _divide(
        metrics["operating_cashflow_ttm"], metrics["deducted_net_profit_ttm"]
    )
    return metrics


def _single_quarter_values(snapshot: dict[pd.Timestamp, dict], period: pd.Timestamp) -> dict:
    current = snapshot[period]
    basis = str(current.get("period_value_basis", "")).lower()
    quarter = int((period.month - 1) // 3 + 1)
    prior_period = _quarter_shift(period, -1)
    prior = snapshot.get(prior_period, {}) if prior_period.year == period.year else {}
    values = {}
    for column in FLOW_COLUMNS:
        value = _finite(current.get(column))
        if basis == "quarter" or quarter == 1:
            values[column] = value
        else:
            prior_value = _finite(prior.get(column))
            values[column] = _subtract(value, prior_value)
    return values


def _ttm_flow(snapshot: dict[pd.Timestamp, dict], period: pd.Timestamp, column: str) -> float:
    periods = [_quarter_shift(period, offset) for offset in (-3, -2, -1, 0)]
    if any(item not in snapshot for item in periods):
        return np.nan
    return _sum_complete([_single_quarter_values(snapshot, item).get(column) for item in periods], required=4)


def _period_growth(snapshot: dict[pd.Timestamp, dict], period: pd.Timestamp, column: str) -> float:
    current = snapshot.get(period, {}).get(column)
    prior = snapshot.get(_quarter_shift(period, -4), {}).get(column)
    return _growth(current, prior)


def _industry_neutral(frame: pd.DataFrame, values: pd.Series, date_col: str) -> pd.Series:
    industry_col = "industry" if "industry" in frame.columns else None
    if industry_col is None:
        return values
    return values - values.groupby([frame[date_col], frame[industry_col]], sort=False).transform("median")


def _quarter_shift(period: pd.Timestamp, quarters: int) -> pd.Timestamp:
    return (pd.Timestamp(period).to_period("Q") + int(quarters)).end_time.normalize()


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _finite(value) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    return float(numeric) if pd.notna(numeric) and np.isfinite(float(numeric)) else np.nan


def _sum_complete(values, *, required: int) -> float:
    valid = [_finite(value) for value in values]
    return float(sum(valid)) if len(valid) == required and all(np.isfinite(value) for value in valid) else np.nan


def _growth(current, prior) -> float:
    current_value = _finite(current)
    prior_value = _finite(prior)
    if not np.isfinite(current_value) or not np.isfinite(prior_value) or abs(prior_value) < 1e-12:
        return np.nan
    return current_value / prior_value - 1.0


def _subtract(left, right) -> float:
    left_value = _finite(left)
    right_value = _finite(right)
    return left_value - right_value if np.isfinite(left_value) and np.isfinite(right_value) else np.nan


def _divide(numerator, denominator) -> float:
    numerator_value = _finite(numerator)
    denominator_value = _finite(denominator)
    if not np.isfinite(numerator_value) or not np.isfinite(denominator_value) or abs(denominator_value) < 1e-12:
        return np.nan
    return numerator_value / denominator_value


def _average_positive(current, prior) -> float:
    current_value = _finite(current)
    prior_value = _finite(prior)
    if not np.isfinite(current_value) or not np.isfinite(prior_value):
        return np.nan
    average = 0.5 * (current_value + prior_value)
    return average if average > 0.0 else np.nan
