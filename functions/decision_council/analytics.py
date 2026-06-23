"""Governance attribution metrics beyond headline NAV."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


VALID_INVESTED_EXPOSURE_FLOOR = 0.05
TOP_STRENGTH_BENCHMARK_FRACTION = 0.30
TOP_STRENGTH_BENCHMARK_ID = "top_strength_30pct_equal_weight"


def build_governance_attribution(
    *,
    daily_result: pd.DataFrame,
    feature_data: pd.DataFrame,
    benchmark_symbol: str | None,
    factor_weight_ledger: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add benchmark, invested-capital, exposure-adjusted, and factor-state metrics."""
    if daily_result is None or daily_result.empty:
        return pd.DataFrame()
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for column in ["nominal_nav", "liquidatable_nav", "cash", "invested_value", "target_exposure", "actual_exposure"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    if "actual_exposure" not in data.columns:
        data["actual_exposure"] = data["invested_value"] / data["nominal_nav"].replace(0.0, np.nan)
    data["actual_exposure"] = data["actual_exposure"].fillna(0.0).clip(lower=0.0)

    initial_nav = _first_positive(data["liquidatable_nav"])
    data["account_net_value"] = data["liquidatable_nav"] / initial_nav if initial_nav > 0 else np.nan
    data["account_daily_return"] = data["account_net_value"].pct_change(fill_method=None).fillna(0.0)
    data["account_drawdown"] = data["account_net_value"] / data["account_net_value"].cummax() - 1.0

    exposure = data["actual_exposure"].replace(0.0, np.nan)
    data["exposure_adjusted_daily_return"] = (data["account_daily_return"] / exposure).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    data["invested_capital_net_value"] = (1.0 + data["exposure_adjusted_daily_return"]).cumprod()
    data["invested_capital_drawdown"] = (
        data["invested_capital_net_value"] / data["invested_capital_net_value"].cummax() - 1.0
    )
    valid_exposure = data["actual_exposure"] >= float(VALID_INVESTED_EXPOSURE_FLOOR)
    data["valid_invested_capital_daily_return"] = np.where(
        valid_exposure,
        data["exposure_adjusted_daily_return"],
        0.0,
    )
    data["valid_invested_capital_net_value"] = (1.0 + data["valid_invested_capital_daily_return"]).cumprod()
    data["valid_invested_capital_drawdown"] = (
        data["valid_invested_capital_net_value"] / data["valid_invested_capital_net_value"].cummax() - 1.0
    )
    data["valid_invested_capital_observed"] = valid_exposure.astype(bool)
    # Approximation used for online diagnostics; exact holding-level return needs fill-level cash-flow attribution.
    data["holding_portfolio_daily_return"] = data["valid_invested_capital_daily_return"]
    data["holding_portfolio_net_value"] = data["valid_invested_capital_net_value"]
    data["cash_drag_daily_return"] = data["exposure_adjusted_daily_return"] - data["account_daily_return"]
    data["valid_cash_drag_daily_return"] = data["valid_invested_capital_daily_return"] - data["account_daily_return"]
    data["cash_drag_net_value"] = (1.0 + data["cash_drag_daily_return"]).cumprod()
    data["valid_cash_drag_net_value"] = (1.0 + data["valid_cash_drag_daily_return"]).cumprod()

    benchmark = _benchmark_series(feature_data, benchmark_symbol)
    data = data.merge(benchmark, on="date", how="left")
    data["benchmark_net_value"] = data["benchmark_net_value"].ffill()
    benchmark_initial = _first_positive(data["benchmark_net_value"])
    if benchmark_initial > 0:
        data["benchmark_net_value"] = data["benchmark_net_value"] / benchmark_initial
    data["benchmark_daily_return"] = data["benchmark_net_value"].pct_change(fill_method=None).fillna(0.0)
    data["excess_daily_return"] = data["account_daily_return"] - data["benchmark_daily_return"]
    data["excess_net_value"] = (1.0 + data["excess_daily_return"]).cumprod()
    data["invested_excess_daily_return"] = data["exposure_adjusted_daily_return"] - data["benchmark_daily_return"]
    data["invested_excess_net_value"] = (1.0 + data["invested_excess_daily_return"]).cumprod()
    data["valid_invested_excess_daily_return"] = data["valid_invested_capital_daily_return"] - data["benchmark_daily_return"]
    data["valid_invested_excess_net_value"] = (1.0 + data["valid_invested_excess_daily_return"]).cumprod()
    data["holding_portfolio_excess_daily_return"] = data["holding_portfolio_daily_return"] - data["benchmark_daily_return"]
    data["holding_portfolio_excess_net_value"] = (1.0 + data["holding_portfolio_excess_daily_return"]).cumprod()

    beta, upside_capture, downside_capture = _benchmark_capture_stats(
        account_return=data["account_daily_return"],
        benchmark_return=data["benchmark_daily_return"],
    )
    data["benchmark_beta_full_period"] = beta
    data["upside_capture_full_period"] = upside_capture
    data["downside_capture_full_period"] = downside_capture

    data["holding_count_bucket"] = pd.cut(
        pd.to_numeric(data.get("holding_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0),
        bins=[-0.1, 0.1, 3, 8, 15, math.inf],
        labels=["zero", "1-3", "4-8", "9-15", "16+"],
    ).astype(str)
    data["exposure_bucket"] = pd.cut(
        data["actual_exposure"].fillna(0.0),
        bins=[-0.001, 0.10, 0.25, 0.50, 0.75, math.inf],
        labels=["0-10%", "10-25%", "25-50%", "50-75%", "75%+"],
    ).astype(str)

    factor_state = build_factor_state_ledger(factor_weight_ledger)
    if not factor_state.empty:
        data = data.merge(factor_state, on="date", how="left")
    else:
        data["factor_entropy"] = np.nan
        data["factor_hhi"] = np.nan
        data["factor_top1_share"] = np.nan
        data["factor_top3_share"] = np.nan
        data["dominant_factor"] = ""
        data["dominant_factor_module"] = ""
    data["factor_entropy_bucket"] = pd.cut(
        pd.to_numeric(data["factor_entropy"], errors="coerce"),
        bins=[-0.001, 0.45, 0.70, 0.88, 1.001],
        labels=["concentrated", "tilted", "diversified", "flat/noisy"],
    ).astype(str)
    return data


def build_bucket_attribution(attribution: pd.DataFrame) -> pd.DataFrame:
    """Summarize whether exposure, holding count, and factor concentration explain returns."""
    if attribution is None or attribution.empty:
        return pd.DataFrame()
    rows = []
    for dimension in ["holding_count_bucket", "exposure_bucket", "factor_entropy_bucket", "dominant_factor_module"]:
        if dimension not in attribution.columns:
            continue
        for bucket, group in attribution.groupby(dimension, dropna=False):
            if group.empty:
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "bucket": str(bucket),
                    "days": int(len(group)),
                    "avg_actual_exposure": _safe_mean(group.get("actual_exposure")),
                    "account_total_return": _compound(group.get("account_daily_return")),
                    "invested_capital_total_return": _compound(group.get("exposure_adjusted_daily_return")),
                    "valid_invested_capital_total_return": _compound(group.get("valid_invested_capital_daily_return")),
                    "holding_portfolio_total_return": _compound(group.get("holding_portfolio_daily_return")),
                    "benchmark_total_return": _compound(group.get("benchmark_daily_return")),
                    "excess_total_return": _compound(group.get("excess_daily_return")),
                    "invested_excess_total_return": _compound(group.get("invested_excess_daily_return")),
                    "valid_invested_excess_total_return": _compound(group.get("valid_invested_excess_daily_return")),
                    "holding_portfolio_excess_total_return": _compound(group.get("holding_portfolio_excess_daily_return")),
                    "account_win_rate": _win_rate(group.get("account_daily_return")),
                    "excess_win_rate": _win_rate(group.get("excess_daily_return")),
                    "valid_invested_observed_days": int(pd.Series(group.get("valid_invested_capital_observed", [])).fillna(False).astype(bool).sum()),
                    "avg_factor_entropy": _safe_mean(group.get("factor_entropy")),
                    "avg_factor_top1_share": _safe_mean(group.get("factor_top1_share")),
                }
            )
    return pd.DataFrame(rows)


def build_factor_state_ledger(factor_weight_ledger: pd.DataFrame | None) -> pd.DataFrame:
    if factor_weight_ledger is None or factor_weight_ledger.empty:
        return pd.DataFrame()
    data = factor_weight_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["weight_share"] = pd.to_numeric(data["weight_share"], errors="coerce").clip(lower=0.0)
    data = data.dropna(subset=["date", "model_name", "weight_share"])
    if data.empty:
        return pd.DataFrame()
    rows = []
    for date, group in data.groupby("date", sort=True):
        shares = group["weight_share"].to_numpy(dtype=float)
        total = float(np.nansum(shares))
        if total <= 0:
            continue
        shares = shares / total
        positive = shares[shares > 0]
        entropy = -float(np.sum(positive * np.log(positive))) / math.log(len(shares)) if len(shares) > 1 else 0.0
        sorted_group = group.assign(_share=shares).sort_values("_share", ascending=False)
        top = sorted_group.iloc[0]
        rows.append(
            {
                "date": pd.Timestamp(date),
                "factor_entropy": entropy,
                "factor_hhi": float(np.sum(np.square(shares))),
                "factor_top1_share": float(sorted_group["_share"].iloc[0]),
                "factor_top3_share": float(sorted_group["_share"].head(3).sum()),
                "dominant_factor": str(top["model_name"]),
                "dominant_factor_module": str(top.get("factor_module", "unknown")),
            }
        )
    return pd.DataFrame(rows)


def factor_module(model_name: str) -> str:
    name = str(model_name).lower()
    if "orderflow" in name or "volume" in name or "close_strength" in name:
        return "flow_close"
    if "limit" in name or "event" in name or "holiday" in name:
        return "event_limit"
    if "momentum" in name or "macd" in name or "breakout" in name or "ma_" in name:
        return "trend"
    if "reversal" in name or "decline" in name or "oversold" in name or "pullback" in name:
        return "reversal_pullback"
    if "lowvol" in name or "low_vol" in name:
        return "defensive"
    if "grid" in name:
        return "range_grid"
    return "other"


def build_top_strength_benchmark_series(
    feature_data: pd.DataFrame,
    *,
    top_fraction: float = TOP_STRENGTH_BENCHMARK_FRACTION,
) -> pd.DataFrame:
    """Build a PIT synthetic benchmark from prior-day top-strength stocks.

    The benchmark return on T+1 is the equal-weight return of stocks ranked in
    the top fraction by strength at T. It is intentionally harder than a broad
    mean/median universe benchmark and avoids same-day return lookahead.
    """
    columns = ["date", "benchmark_net_value", "benchmark_daily_return", "benchmark_member_count", "benchmark_id"]
    if feature_data is None or feature_data.empty:
        return pd.DataFrame(columns=columns)
    close_col = "close_nominal" if "close_nominal" in feature_data.columns else "close"
    if close_col not in feature_data.columns:
        return pd.DataFrame(columns=columns)
    strength_columns = [
        column
        for column in [
            "ret_20",
            "close_to_ma20",
            "score_eod_close_strength",
            "score_price_volume_breakout",
            "amount_ratio_20",
        ]
        if column in feature_data.columns
    ]
    if not strength_columns:
        return pd.DataFrame(columns=columns)

    required = ["date", "symbol", close_col] + strength_columns
    data = feature_data[required].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    for column in strength_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["date", "symbol", close_col]).sort_values(["date", "symbol"])
    if data.empty:
        return pd.DataFrame(columns=columns)

    data["_strength_score"] = _cross_sectional_strength_score(data, strength_columns)
    close_pivot = data.pivot_table(index="date", columns="symbol", values=close_col, aggfunc="last").sort_index()
    strength_pivot = data.pivot_table(index="date", columns="symbol", values="_strength_score", aggfunc="last").reindex(close_pivot.index)
    if len(close_pivot.index) < 2:
        return pd.DataFrame(columns=columns)

    rows = [
        {
            "date": pd.Timestamp(close_pivot.index[0]),
            "benchmark_daily_return": 0.0,
            "benchmark_member_count": 0,
        }
    ]
    top_fraction = float(np.clip(top_fraction, 0.01, 1.0))
    for idx in range(len(close_pivot.index) - 1):
        current_date = close_pivot.index[idx]
        next_date = close_pivot.index[idx + 1]
        scores = pd.to_numeric(strength_pivot.loc[current_date], errors="coerce")
        next_returns = close_pivot.iloc[idx + 1] / close_pivot.iloc[idx] - 1.0
        candidates = pd.DataFrame({"score": scores, "return": next_returns}).replace([np.inf, -np.inf], np.nan).dropna()
        if candidates.empty:
            daily_return = 0.0
            member_count = 0
        else:
            member_count = max(1, int(math.ceil(len(candidates) * top_fraction)))
            top = candidates.sort_values("score", ascending=False).head(member_count)
            daily_return = float(pd.to_numeric(top["return"], errors="coerce").dropna().mean()) if not top.empty else 0.0
        rows.append(
            {
                "date": pd.Timestamp(next_date),
                "benchmark_daily_return": daily_return,
                "benchmark_member_count": int(member_count),
            }
        )

    result = pd.DataFrame(rows).sort_values("date")
    result["benchmark_daily_return"] = pd.to_numeric(result["benchmark_daily_return"], errors="coerce").fillna(0.0)
    result["benchmark_net_value"] = (1.0 + result["benchmark_daily_return"]).cumprod()
    result["benchmark_id"] = TOP_STRENGTH_BENCHMARK_ID
    return result[columns]


def _cross_sectional_strength_score(data: pd.DataFrame, strength_columns: list[str]) -> pd.Series:
    ranked = []
    for column in strength_columns:
        values = pd.to_numeric(data[column], errors="coerce")
        if column == "volatility_20":
            values = -values
        ranked.append(values.groupby(data["date"]).rank(pct=True, method="average"))
    if not ranked:
        return pd.Series(np.nan, index=data.index)
    return pd.concat(ranked, axis=1).mean(axis=1, skipna=True)


def _benchmark_series(feature_data: pd.DataFrame, benchmark_symbol: str | None) -> pd.DataFrame:
    top_strength = build_top_strength_benchmark_series(feature_data)
    if not top_strength.empty:
        return top_strength
    if feature_data is None or feature_data.empty or not benchmark_symbol:
        return pd.DataFrame(columns=["date", "benchmark_net_value", "benchmark_daily_return"])
    data = feature_data.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    close_col = "close_nominal" if "close_nominal" in data.columns else "close"
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    data = data[(data["symbol"].astype(str) == str(benchmark_symbol))].dropna(subset=["date", close_col]).sort_values("date")
    if data.empty:
        return pd.DataFrame(columns=["date", "benchmark_net_value", "benchmark_daily_return"])
    initial = _first_positive(data[close_col])
    data["benchmark_net_value"] = data[close_col] / initial if initial > 0 else np.nan
    data["benchmark_daily_return"] = data["benchmark_net_value"].pct_change(fill_method=None).fillna(0.0)
    return data[["date", "benchmark_net_value", "benchmark_daily_return"]]


def _first_positive(series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values > 0]
    return float(values.iloc[0]) if not values.empty else 1.0


def _safe_mean(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float(values.mean()) if not values.empty else 0.0


def _compound(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float((1.0 + values).prod() - 1.0) if not values.empty else 0.0


def _win_rate(series) -> float:
    values = pd.to_numeric(series if series is not None else pd.Series(dtype=float), errors="coerce").dropna()
    return float((values > 0).mean()) if not values.empty else 0.0


def _benchmark_capture_stats(*, account_return: pd.Series, benchmark_return: pd.Series) -> tuple[float, float, float]:
    account = pd.to_numeric(account_return, errors="coerce")
    benchmark = pd.to_numeric(benchmark_return, errors="coerce")
    aligned = pd.DataFrame({"account": account, "benchmark": benchmark}).dropna()
    if aligned.empty:
        return 0.0, 0.0, 0.0
    variance = float(aligned["benchmark"].var(ddof=0))
    beta = float(aligned["account"].cov(aligned["benchmark"]) / variance) if variance > 1e-12 else 0.0
    up = aligned[aligned["benchmark"] > 0.0]
    down = aligned[aligned["benchmark"] < 0.0]
    upside = float(up["account"].mean() / up["benchmark"].mean()) if not up.empty and abs(float(up["benchmark"].mean())) > 1e-12 else 0.0
    downside = float(down["account"].mean() / down["benchmark"].mean()) if not down.empty and abs(float(down["benchmark"].mean())) > 1e-12 else 0.0
    return beta, upside, downside
