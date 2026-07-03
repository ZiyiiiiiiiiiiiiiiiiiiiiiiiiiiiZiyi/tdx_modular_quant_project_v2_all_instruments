"""Large pre-screen candidate factor pool.

The factors in this module are research candidates only. They are generated for
IC/quantile/redundancy screening and are not wired into trading decisions unless
they later pass the governance admission process.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CandidateFactorSpec:
    factor_name: str
    raw_column: str
    module: str
    direction: str = "higher_better"
    neutralize_industry: bool = True
    neutralize_size: bool = True


CANDIDATE_FACTOR_SPECS: tuple[CandidateFactorSpec, ...] = (
    CandidateFactorSpec("candidate_size_float_cap_neg", "cand_size_float_cap_neg", "size"),
    CandidateFactorSpec("candidate_size_total_cap_neg", "cand_size_total_cap_neg", "size"),
    CandidateFactorSpec("candidate_size_float_cap_rank_small", "cand_size_float_cap_rank_small", "size"),
    CandidateFactorSpec("candidate_turnover_to_float_cap_20", "cand_turnover_to_float_cap_20", "liquidity"),
    CandidateFactorSpec("candidate_turnover_to_float_cap_60", "cand_turnover_to_float_cap_60", "liquidity"),
    CandidateFactorSpec("candidate_amount_rank_20", "cand_amount_rank_20", "liquidity"),
    CandidateFactorSpec("candidate_amount_rank_60", "cand_amount_rank_60", "liquidity"),
    CandidateFactorSpec("candidate_amount_stability_20", "cand_amount_stability_20", "liquidity"),
    CandidateFactorSpec("candidate_amount_stability_60", "cand_amount_stability_60", "liquidity"),
    CandidateFactorSpec("candidate_amihud_20_neg", "cand_amihud_20_neg", "liquidity"),
    CandidateFactorSpec("candidate_amihud_60_neg", "cand_amihud_60_neg", "liquidity"),
    CandidateFactorSpec("candidate_zero_volume_rate_20_neg", "cand_zero_volume_rate_20_neg", "liquidity"),
    CandidateFactorSpec("candidate_zero_volume_rate_60_neg", "cand_zero_volume_rate_60_neg", "liquidity"),
    CandidateFactorSpec("candidate_price_momentum_3", "cand_price_momentum_3", "momentum"),
    CandidateFactorSpec("candidate_price_momentum_5", "cand_price_momentum_5", "momentum"),
    CandidateFactorSpec("candidate_price_momentum_10", "cand_price_momentum_10", "momentum"),
    CandidateFactorSpec("candidate_price_momentum_20", "cand_price_momentum_20", "momentum"),
    CandidateFactorSpec("candidate_price_momentum_60", "cand_price_momentum_60", "momentum"),
    CandidateFactorSpec("candidate_price_momentum_120", "cand_price_momentum_120", "momentum"),
    CandidateFactorSpec("candidate_momentum_accel_5_20", "cand_momentum_accel_5_20", "momentum"),
    CandidateFactorSpec("candidate_momentum_accel_20_60", "cand_momentum_accel_20_60", "momentum"),
    CandidateFactorSpec("candidate_lowvol_momentum_20", "cand_lowvol_momentum_20", "momentum"),
    CandidateFactorSpec("candidate_lowvol_momentum_60", "cand_lowvol_momentum_60", "momentum"),
    CandidateFactorSpec("candidate_industry_relative_momentum_20", "cand_industry_relative_momentum_20", "neutral_residual"),
    CandidateFactorSpec("candidate_industry_relative_momentum_60", "cand_industry_relative_momentum_60", "neutral_residual"),
    CandidateFactorSpec("candidate_reversal_1", "cand_reversal_1", "reversal"),
    CandidateFactorSpec("candidate_reversal_3", "cand_reversal_3", "reversal"),
    CandidateFactorSpec("candidate_reversal_5", "cand_reversal_5", "reversal"),
    CandidateFactorSpec("candidate_reversal_10", "cand_reversal_10", "reversal"),
    CandidateFactorSpec("candidate_reversal_after_down_20", "cand_reversal_after_down_20", "reversal"),
    CandidateFactorSpec("candidate_close_to_ma5", "cand_close_to_ma5", "trend"),
    CandidateFactorSpec("candidate_close_to_ma10", "cand_close_to_ma10", "trend"),
    CandidateFactorSpec("candidate_close_to_ma20", "cand_close_to_ma20", "trend"),
    CandidateFactorSpec("candidate_close_to_ma60", "cand_close_to_ma60", "trend"),
    CandidateFactorSpec("candidate_ma5_ma20_gap", "cand_ma5_ma20_gap", "trend"),
    CandidateFactorSpec("candidate_ma10_ma60_gap", "cand_ma10_ma60_gap", "trend"),
    CandidateFactorSpec("candidate_ma20_ma120_gap", "cand_ma20_ma120_gap", "trend"),
    CandidateFactorSpec("candidate_price_position_20", "cand_price_position_20", "breakout"),
    CandidateFactorSpec("candidate_price_position_60", "cand_price_position_60", "breakout"),
    CandidateFactorSpec("candidate_price_position_120", "cand_price_position_120", "breakout"),
    CandidateFactorSpec("candidate_high_breakout_distance_20", "cand_high_breakout_distance_20", "breakout"),
    CandidateFactorSpec("candidate_high_breakout_distance_60", "cand_high_breakout_distance_60", "breakout"),
    CandidateFactorSpec("candidate_low_distance_20", "cand_low_distance_20", "reversal"),
    CandidateFactorSpec("candidate_low_distance_60", "cand_low_distance_60", "reversal"),
    CandidateFactorSpec("candidate_volatility_5_neg", "cand_volatility_5_neg", "volatility"),
    CandidateFactorSpec("candidate_volatility_10_neg", "cand_volatility_10_neg", "volatility"),
    CandidateFactorSpec("candidate_volatility_20_neg", "cand_volatility_20_neg", "volatility"),
    CandidateFactorSpec("candidate_volatility_60_neg", "cand_volatility_60_neg", "volatility"),
    CandidateFactorSpec("candidate_downside_volatility_20_neg", "cand_downside_volatility_20_neg", "volatility"),
    CandidateFactorSpec("candidate_downside_volatility_60_neg", "cand_downside_volatility_60_neg", "volatility"),
    CandidateFactorSpec("candidate_max_drawdown_20_neg", "cand_max_drawdown_20_neg", "risk"),
    CandidateFactorSpec("candidate_max_drawdown_60_neg", "cand_max_drawdown_60_neg", "risk"),
    CandidateFactorSpec("candidate_return_skew_20", "cand_return_skew_20", "higher_moment"),
    CandidateFactorSpec("candidate_return_skew_60", "cand_return_skew_60", "higher_moment"),
    CandidateFactorSpec("candidate_return_kurtosis_20_neg", "cand_return_kurtosis_20_neg", "higher_moment"),
    CandidateFactorSpec("candidate_return_kurtosis_60_neg", "cand_return_kurtosis_60_neg", "higher_moment"),
    CandidateFactorSpec("candidate_intraday_strength", "cand_intraday_strength", "kline"),
    CandidateFactorSpec("candidate_close_location", "cand_close_location", "kline"),
    CandidateFactorSpec("candidate_upper_shadow_neg", "cand_upper_shadow_neg", "kline"),
    CandidateFactorSpec("candidate_lower_shadow", "cand_lower_shadow", "kline"),
    CandidateFactorSpec("candidate_body_strength", "cand_body_strength", "kline"),
    CandidateFactorSpec("candidate_gap_strength", "cand_gap_strength", "kline"),
    CandidateFactorSpec("candidate_gap_reversal", "cand_gap_reversal", "kline"),
    CandidateFactorSpec("candidate_volume_price_trend_20", "cand_volume_price_trend_20", "volume_price"),
    CandidateFactorSpec("candidate_volume_price_trend_60", "cand_volume_price_trend_60", "volume_price"),
    CandidateFactorSpec("candidate_obv_momentum_20", "cand_obv_momentum_20", "volume_price"),
    CandidateFactorSpec("candidate_obv_momentum_60", "cand_obv_momentum_60", "volume_price"),
    CandidateFactorSpec("candidate_money_flow_20", "cand_money_flow_20", "volume_price"),
    CandidateFactorSpec("candidate_money_flow_60", "cand_money_flow_60", "volume_price"),
    CandidateFactorSpec("candidate_amount_shock_5", "cand_amount_shock_5", "volume_price"),
    CandidateFactorSpec("candidate_amount_shock_20", "cand_amount_shock_20", "volume_price"),
    CandidateFactorSpec("candidate_volume_shock_5", "cand_volume_shock_5", "volume_price"),
    CandidateFactorSpec("candidate_volume_shock_20", "cand_volume_shock_20", "volume_price"),
    CandidateFactorSpec("candidate_efficiency_ratio_20", "cand_efficiency_ratio_20", "trend_quality"),
    CandidateFactorSpec("candidate_efficiency_ratio_60", "cand_efficiency_ratio_60", "trend_quality"),
    CandidateFactorSpec("candidate_trend_slope_20", "cand_trend_slope_20", "trend_quality"),
    CandidateFactorSpec("candidate_trend_slope_60", "cand_trend_slope_60", "trend_quality"),
    CandidateFactorSpec("candidate_beta_to_market_60_neg", "cand_beta_to_market_60_neg", "risk"),
    CandidateFactorSpec("candidate_idiosyncratic_vol_60_neg", "cand_idiosyncratic_vol_60_neg", "risk"),
    CandidateFactorSpec("candidate_market_relative_strength_20", "cand_market_relative_strength_20", "relative_strength"),
    CandidateFactorSpec("candidate_market_relative_strength_60", "cand_market_relative_strength_60", "relative_strength"),
    CandidateFactorSpec("candidate_value_proxy_close_to_cap_neg", "cand_value_proxy_close_to_cap_neg", "value_proxy"),
    CandidateFactorSpec("candidate_quality_proxy_low_drawdown_lowvol", "cand_quality_proxy_low_drawdown_lowvol", "quality_proxy"),
    CandidateFactorSpec("candidate_growth_proxy_salesless_trend", "cand_growth_proxy_salesless_trend", "growth_proxy"),
    CandidateFactorSpec("candidate_composite_value_quality", "cand_composite_value_quality", "composite"),
    CandidateFactorSpec("candidate_composite_momentum_quality", "cand_composite_momentum_quality", "composite"),
    CandidateFactorSpec("candidate_composite_reversal_liquidity", "cand_composite_reversal_liquidity", "composite"),
)


ULTRA_GRID_FACTOR_TARGET_COUNT = 5200
MATRIX_FACTOR_TARGET_COUNT = 4800


def _ultra_base_signal_defs() -> list[dict]:
    defs: list[dict] = []
    for window in (1, 2, 3, 5, 10, 15, 20, 30, 40, 60, 90, 120, 180, 240):
        defs.append({"key": f"ret_{window}", "module": "grid_momentum"})
        defs.append({"key": f"rev_{window}", "module": "grid_reversal"})
    for window in (3, 5, 10, 20, 30, 60, 120, 180, 240):
        defs.append({"key": f"ma_gap_{window}", "module": "grid_trend"})
        defs.append({"key": f"price_pos_{window}", "module": "grid_breakout"})
    for window in (5, 10, 20, 30, 60, 90, 120, 180):
        defs.append({"key": f"vol_neg_{window}", "module": "grid_volatility"})
        defs.append({"key": f"downvol_neg_{window}", "module": "grid_volatility"})
        defs.append({"key": f"drawdown_neg_{window}", "module": "grid_risk"})
    for window in (3, 5, 10, 20, 30, 60, 90, 120):
        defs.append({"key": f"amount_shock_{window}", "module": "grid_volume_price"})
        defs.append({"key": f"volume_shock_{window}", "module": "grid_volume_price"})
        defs.append({"key": f"amihud_neg_{window}", "module": "grid_liquidity"})
        defs.append({"key": f"turnover_{window}", "module": "grid_liquidity"})
    for window in (3, 5, 10, 20, 30, 60):
        defs.append({"key": f"close_loc_mean_{window}", "module": "grid_kline"})
        defs.append({"key": f"body_mean_{window}", "module": "grid_kline"})
        defs.append({"key": f"lower_shadow_mean_{window}", "module": "grid_kline"})
        defs.append({"key": f"upper_shadow_neg_mean_{window}", "module": "grid_kline"})
        defs.append({"key": f"efficiency_{window}", "module": "grid_trend_quality"})
    defs.extend(
        [
            {"key": "size_float_neg", "module": "grid_size"},
            {"key": "size_total_neg", "module": "grid_size"},
            {"key": "value_proxy", "module": "grid_value_proxy"},
            {"key": "quality_proxy", "module": "grid_quality_proxy"},
            {"key": "macd_hist_12_26_9", "module": "macd"},
            {"key": "macd_cross_strength_12_26_9", "module": "macd"},
            {"key": "rsi_6_reversal", "module": "rsi_reversal"},
            {"key": "rsi_14_reversal", "module": "rsi_reversal"},
            {"key": "turtle_breakout_20", "module": "turtle_breakout"},
            {"key": "turtle_breakout_55", "module": "turtle_breakout"},
            {"key": "close_volume_ratio_20", "module": "close_volume_ratio"},
            {"key": "large_order_proxy_20", "module": "large_orders"},
            {"key": "low_noise_60", "module": "low_noise"},
            {"key": "barra_beta_60_neg", "module": "barra_beta"},
            {"key": "barra_size_neg", "module": "barra_size"},
            {"key": "barra_value_proxy", "module": "barra_value"},
            {"key": "valuation_pe_proxy_neg", "module": "valuation"},
            {"key": "valuation_pb_proxy_neg", "module": "valuation"},
            {"key": "profitability_proxy", "module": "profitability"},
            {"key": "growth_proxy", "module": "growth"},
            {"key": "cashflow_proxy", "module": "cashflow"},
            {"key": "earnings_surprise_proxy", "module": "earnings_surprise"},
            {"key": "analyst_update_proxy", "module": "analyst_update"},
            {"key": "sentiment_proxy", "module": "sentiment"},
            {"key": "supply_chain_proxy", "module": "supply_chain"},
            {"key": "social_heat_proxy", "module": "social"},
        ]
    )
    return defs


def _build_ultra_grid_recipes(target_count: int = ULTRA_GRID_FACTOR_TARGET_COUNT) -> list[dict]:
    base_defs = _ultra_base_signal_defs()
    recipes: list[dict] = []
    for base in base_defs:
        key = base["key"]
        recipes.append(
            {
                "kind": "base_rank",
                "a": key,
                "b": "",
                "raw_column": f"cand_grid_base_rank__{key}",
                "factor_name": f"candidate_grid_base_rank__{key}",
                "module": base["module"],
            }
        )
    pair_ops = (
        ("rank_mean", "grid_rank_blend"),
        ("rank_spread", "grid_rank_spread"),
        ("rank_product", "grid_rank_interaction"),
        ("rank_gate_hi", "grid_conditional"),
        ("rank_gate_lo", "grid_conditional"),
        ("rank_ratio", "grid_ratio"),
    )
    for i, left in enumerate(base_defs):
        for right in base_defs[i + 1 :]:
            for op, module in pair_ops:
                raw = f"cand_grid_{op}__{left['key']}__{right['key']}"
                recipes.append(
                    {
                        "kind": op,
                        "a": left["key"],
                        "b": right["key"],
                        "raw_column": raw,
                        "factor_name": raw.replace("cand_", "candidate_"),
                        "module": module,
                    }
                )
                if len(recipes) >= int(target_count):
                    return recipes
    return recipes


def _build_matrix_factor_recipes(target_count: int = MATRIX_FACTOR_TARGET_COUNT) -> list[dict]:
    base_defs = _ultra_base_signal_defs()
    recipes: list[dict] = []
    for base in base_defs:
        key = base["key"]
        recipes.append(
            {
                "kind": "base_rank",
                "a": key,
                "b": "",
                "raw_column": f"cand_matrix_base_rank__{key}",
                "factor_name": f"candidate_matrix_base_rank__{key}",
                "module": base["module"].removeprefix("grid_"),
            }
        )
    pair_ops = (
        ("rank_mean", "blend"),
        ("rank_spread", "spread"),
        ("rank_product", "interaction"),
        ("rank_gate_hi", "conditional"),
        ("rank_gate_lo", "conditional"),
    )
    for i, left in enumerate(base_defs):
        for right in base_defs[i + 1 :]:
            left_module = str(left["module"]).removeprefix("grid_")
            right_module = str(right["module"]).removeprefix("grid_")
            if left_module == right_module:
                continue
            module = f"{left_module}_{right_module}"
            for op, family in pair_ops:
                raw = f"cand_matrix_{op}__{left['key']}__{right['key']}"
                recipes.append(
                    {
                        "kind": op,
                        "a": left["key"],
                        "b": right["key"],
                        "raw_column": raw,
                        "factor_name": raw.replace("cand_", "candidate_"),
                        "module": f"{family}:{module}",
                    }
                )
                if len(recipes) >= int(target_count):
                    return recipes
    return recipes


BASE_CANDIDATE_FACTOR_SPECS = CANDIDATE_FACTOR_SPECS
ULTRA_GRID_FACTOR_RECIPES = tuple(_build_ultra_grid_recipes())
MATRIX_FACTOR_RECIPES = tuple(_build_matrix_factor_recipes())
ULTRA_GRID_FACTOR_SPECS = tuple(
    CandidateFactorSpec(
        recipe["factor_name"],
        recipe["raw_column"],
        recipe["module"],
        direction="higher_better",
    )
    for recipe in ULTRA_GRID_FACTOR_RECIPES
)
MATRIX_FACTOR_SPECS = tuple(
    CandidateFactorSpec(
        recipe["factor_name"],
        recipe["raw_column"],
        recipe["module"],
        direction="higher_better",
    )
    for recipe in MATRIX_FACTOR_RECIPES
)
CANDIDATE_FACTOR_SPECS = BASE_CANDIDATE_FACTOR_SPECS + ULTRA_GRID_FACTOR_SPECS + MATRIX_FACTOR_SPECS


def candidate_factor_columns() -> list[str]:
    return [spec.raw_column for spec in CANDIDATE_FACTOR_SPECS]


def base_candidate_factor_columns() -> list[str]:
    return [spec.raw_column for spec in BASE_CANDIDATE_FACTOR_SPECS]


def candidate_factor_registry_rows() -> list[dict]:
    return [
        {
            "factor_name": spec.factor_name,
            "module": spec.module,
            "source_file": "functions/factors/factor_candidate_pool.py",
            "raw_column": spec.raw_column,
            "direction": spec.direction,
            "neutralize_industry": spec.neutralize_industry,
            "neutralize_size": spec.neutralize_size,
            "candidate_pool": "pre_screen_candidate",
        }
        for spec in CANDIDATE_FACTOR_SPECS
    ]


def append_candidate_factors(
    df: pd.DataFrame,
    *,
    close_col: str = "close",
    include_columns: set[str] | list[str] | tuple[str, ...] | None = None,
    include_ultra_grid: bool = False,
) -> pd.DataFrame:
    """Append broad PIT-safe daily candidate factors."""
    if df is None or df.empty:
        return df
    include_set = set(include_columns) if include_columns is not None else None
    frame = df.copy(deep=False)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.sort_values(["symbol", "date"])
    grouped = frame.groupby("symbol", group_keys=False, sort=False)
    close = _num(frame.get(close_col, frame.get("close")))
    open_ = _num(frame.get(_price_col(close_col, "open"), frame.get("open")))
    high = _num(frame.get(_price_col(close_col, "high"), frame.get("high")))
    low = _num(frame.get(_price_col(close_col, "low"), frame.get("low")))
    amount = _num(frame.get("amount", pd.Series(np.nan, index=frame.index))).clip(lower=0.0)
    volume = _num(frame.get("volume", pd.Series(np.nan, index=frame.index))).clip(lower=0.0)
    ret_1 = _num(frame.get("ret_1", grouped[close_col].pct_change(fill_method=None) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)))

    for window in (3, 120):
        frame[f"_cand_ret_{window}"] = grouped[close_col].pct_change(window, fill_method=None) if close_col in frame.columns else np.nan
    for window in (5, 10, 20, 60, 120):
        ma_col = f"ma_{window}"
        if ma_col not in frame.columns and close_col in frame.columns:
            frame[ma_col] = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).mean())
    for window in (5, 20, 60):
        frame[f"_cand_amount_ma_{window}"] = grouped["amount"].transform(lambda s, w=window: s.rolling(w, min_periods=w).mean()) if "amount" in frame.columns else np.nan
        frame[f"_cand_volume_ma_{window}"] = grouped["volume"].transform(lambda s, w=window: s.rolling(w, min_periods=w).mean()) if "volume" in frame.columns else np.nan

    float_cap = _num(frame.get("stabilized_float_cap", frame.get("float_cap", pd.Series(np.nan, index=frame.index))))
    total_cap = _num(frame.get("stabilized_total_cap", frame.get("total_cap", pd.Series(np.nan, index=frame.index))))
    safe_float_cap = float_cap.where(float_cap > 0)
    safe_total_cap = total_cap.where(total_cap > 0)

    focused_simple_columns = {
        "cand_idiosyncratic_vol_60_neg",
        "cand_volatility_60_neg",
        "cand_volatility_20_neg",
    }
    if include_set is not None and include_set and all(
        column.startswith("cand_grid_") or column in focused_simple_columns
        for column in include_set
    ):
        generated: dict[str, pd.Series] = {}
        if "cand_volatility_20_neg" in include_set:
            generated["cand_volatility_20_neg"] = -_rolling_std(ret_1, frame, 20)
        if "cand_volatility_60_neg" in include_set:
            generated["cand_volatility_60_neg"] = -_rolling_std(ret_1, frame, 60)
        if "cand_idiosyncratic_vol_60_neg" in include_set:
            market_ret = ret_1.groupby(frame["date"], sort=False).transform("mean")
            beta60 = _rolling_beta(ret_1, market_ret, frame, 60)
            generated["cand_idiosyncratic_vol_60_neg"] = -_rolling_std(ret_1 - beta60 * market_ret, frame, 60)
        if generated:
            frame = pd.concat(
                [frame, pd.DataFrame({key: pd.to_numeric(value, errors="coerce").astype("float32") for key, value in generated.items()}, index=frame.index)],
                axis=1,
            )
        if include_ultra_grid:
            frame = _append_ultra_grid_factors(
                frame,
                close=close,
                open_=open_,
                high=high,
                low=low,
                amount=amount,
                volume=volume,
                ret_1=ret_1,
                float_cap=safe_float_cap,
                total_cap=safe_total_cap,
                close_col=close_col,
                include_columns=include_set,
            )
            frame = _append_matrix_factors(
                frame,
                close=close,
                open_=open_,
                high=high,
                low=low,
                amount=amount,
                volume=volume,
                ret_1=ret_1,
                float_cap=safe_float_cap,
                total_cap=safe_total_cap,
                close_col=close_col,
                include_columns=include_set,
            )
        temp_cols = [col for col in frame.columns if col.startswith("_cand_")]
        if temp_cols:
            frame = frame.drop(columns=temp_cols)
        return frame

    frame["cand_size_float_cap_neg"] = -np.log1p(safe_float_cap)
    frame["cand_size_total_cap_neg"] = -np.log1p(safe_total_cap)
    frame["cand_size_float_cap_rank_small"] = 1.0 - safe_float_cap.groupby(frame["date"], sort=False).rank(pct=True)

    turn_daily = amount / safe_float_cap
    frame["cand_turnover_to_float_cap_20"] = grouped_apply(turn_daily, frame, 20, "mean")
    frame["cand_turnover_to_float_cap_60"] = grouped_apply(turn_daily, frame, 60, "mean")
    frame["cand_amount_rank_20"] = _rank_by_date(frame["_cand_amount_ma_20"], frame["date"])
    frame["cand_amount_rank_60"] = _rank_by_date(frame["_cand_amount_ma_60"], frame["date"])
    frame["cand_amount_stability_20"] = -_rolling_cv(amount, frame, 20)
    frame["cand_amount_stability_60"] = -_rolling_cv(amount, frame, 60)
    amihud = ret_1.abs() / amount.replace(0.0, np.nan)
    frame["cand_amihud_20_neg"] = -grouped_apply(amihud, frame, 20, "mean")
    frame["cand_amihud_60_neg"] = -grouped_apply(amihud, frame, 60, "mean")
    zero_volume = volume.le(0.0).astype(float)
    frame["cand_zero_volume_rate_20_neg"] = -grouped_apply(zero_volume, frame, 20, "mean")
    frame["cand_zero_volume_rate_60_neg"] = -grouped_apply(zero_volume, frame, 60, "mean")

    frame["cand_price_momentum_3"] = frame["_cand_ret_3"]
    for window in (5, 10, 20, 60):
        frame[f"cand_price_momentum_{window}"] = _num(frame.get(f"ret_{window}"))
    frame["cand_price_momentum_120"] = frame["_cand_ret_120"]
    frame["cand_momentum_accel_5_20"] = _num(frame.get("ret_5")) - _num(frame.get("ret_20"))
    frame["cand_momentum_accel_20_60"] = _num(frame.get("ret_20")) - _num(frame.get("ret_60"))
    frame["cand_lowvol_momentum_20"] = _num(frame.get("ret_20")) / (_num(frame.get("volatility_20")).abs() + 1e-6)
    frame["cand_lowvol_momentum_60"] = _num(frame.get("ret_60")) / (_num(frame.get("volatility_60")).abs() + 1e-6)
    frame["cand_industry_relative_momentum_20"] = _industry_residual(frame, _num(frame.get("ret_20")))
    frame["cand_industry_relative_momentum_60"] = _industry_residual(frame, _num(frame.get("ret_60")))

    frame["cand_reversal_1"] = -_num(frame.get("ret_1"))
    frame["cand_reversal_3"] = -frame["_cand_ret_3"]
    frame["cand_reversal_5"] = -_num(frame.get("ret_5"))
    frame["cand_reversal_10"] = -_num(frame.get("ret_10"))
    frame["cand_reversal_after_down_20"] = (-_num(frame.get("ret_5"))).where(_num(frame.get("ret_20")) < 0.0)

    for window in (5, 10, 20, 60):
        frame[f"cand_close_to_ma{window}"] = close / _num(frame.get(f"ma_{window}")).replace(0.0, np.nan) - 1.0
    frame["cand_ma5_ma20_gap"] = _num(frame.get("ma_5")) / _num(frame.get("ma_20")).replace(0.0, np.nan) - 1.0
    frame["cand_ma10_ma60_gap"] = _num(frame.get("ma_10")) / _num(frame.get("ma_60")).replace(0.0, np.nan) - 1.0
    frame["cand_ma20_ma120_gap"] = _num(frame.get("ma_20")) / _num(frame.get("ma_120")).replace(0.0, np.nan) - 1.0

    for window in (20, 60, 120):
        rolling_high = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).max()) if close_col in frame.columns else np.nan
        rolling_low = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).min()) if close_col in frame.columns else np.nan
        frame[f"cand_price_position_{window}"] = (close - rolling_low) / (rolling_high - rolling_low).replace(0.0, np.nan)
        if window in (20, 60):
            frame[f"cand_high_breakout_distance_{window}"] = close / pd.Series(rolling_high, index=frame.index).replace(0.0, np.nan) - 1.0
            frame[f"cand_low_distance_{window}"] = close / pd.Series(rolling_low, index=frame.index).replace(0.0, np.nan) - 1.0

    for window in (5, 10, 20, 60):
        vol = _rolling_std(ret_1, frame, window)
        frame[f"cand_volatility_{window}_neg"] = -vol
    downside = ret_1.where(ret_1 < 0.0, 0.0)
    frame["cand_downside_volatility_20_neg"] = -_rolling_std(downside, frame, 20)
    frame["cand_downside_volatility_60_neg"] = -_rolling_std(downside, frame, 60)
    frame["cand_max_drawdown_20_neg"] = -_rolling_drawdown(close, frame, 20).abs()
    frame["cand_max_drawdown_60_neg"] = -_rolling_drawdown(close, frame, 60).abs()
    frame["cand_return_skew_20"] = _rolling_moment(ret_1, frame, 20, "skew")
    frame["cand_return_skew_60"] = _rolling_moment(ret_1, frame, 60, "skew")
    frame["cand_return_kurtosis_20_neg"] = -_rolling_moment(ret_1, frame, 20, "kurt")
    frame["cand_return_kurtosis_60_neg"] = -_rolling_moment(ret_1, frame, 60, "kurt")

    price_range = (high - low).replace(0.0, np.nan)
    frame["cand_intraday_strength"] = close / open_.replace(0.0, np.nan) - 1.0
    frame["cand_close_location"] = (close - low) / price_range
    frame["cand_upper_shadow_neg"] = -_num(frame.get("upper_shadow"))
    frame["cand_lower_shadow"] = _num(frame.get("lower_shadow"))
    frame["cand_body_strength"] = _num(frame.get("body_ratio")) * np.sign(close - open_)
    prev_close = grouped[close_col].shift(1) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
    gap = open_ / pd.to_numeric(prev_close, errors="coerce").replace(0.0, np.nan) - 1.0
    frame["cand_gap_strength"] = gap
    frame["cand_gap_reversal"] = -gap * np.sign(frame["cand_intraday_strength"])

    signed_amount = amount * np.sign(ret_1.fillna(0.0))
    typical_price = (high + low + close) / 3.0
    money_flow = typical_price * volume * np.sign((typical_price - grouped_apply(typical_price, frame, 1, "shift")).fillna(0.0))
    obv = signed_amount.groupby(frame["symbol"], sort=False).cumsum()
    for window in (20, 60):
        frame[f"cand_volume_price_trend_{window}"] = grouped_apply(signed_amount, frame, window, "sum") / grouped_apply(amount, frame, window, "sum").replace(0.0, np.nan)
        frame[f"cand_obv_momentum_{window}"] = obv / grouped_apply(obv.abs(), frame, window, "mean").replace(0.0, np.nan)
        frame[f"cand_money_flow_{window}"] = grouped_apply(money_flow, frame, window, "sum") / grouped_apply((typical_price * volume).abs(), frame, window, "sum").replace(0.0, np.nan)
    frame["cand_amount_shock_5"] = amount / _num(frame.get("_cand_amount_ma_5")).replace(0.0, np.nan) - 1.0
    frame["cand_amount_shock_20"] = amount / _num(frame.get("_cand_amount_ma_20")).replace(0.0, np.nan) - 1.0
    frame["cand_volume_shock_5"] = volume / _num(frame.get("_cand_volume_ma_5")).replace(0.0, np.nan) - 1.0
    frame["cand_volume_shock_20"] = volume / _num(frame.get("_cand_volume_ma_20")).replace(0.0, np.nan) - 1.0

    frame["cand_efficiency_ratio_20"] = _efficiency_ratio(close, frame, 20)
    frame["cand_efficiency_ratio_60"] = _efficiency_ratio(close, frame, 60)
    frame["cand_trend_slope_20"] = _num(frame.get("ret_20")) / 20.0
    frame["cand_trend_slope_60"] = _num(frame.get("ret_60")) / 60.0
    market_ret = ret_1.groupby(frame["date"], sort=False).transform("mean")
    beta60 = _rolling_beta(ret_1, market_ret, frame, 60)
    frame["cand_beta_to_market_60_neg"] = -beta60
    frame["cand_idiosyncratic_vol_60_neg"] = -_rolling_std(ret_1 - beta60 * market_ret, frame, 60)
    frame = frame.copy()
    frame["cand_market_relative_strength_20"] = _num(frame.get("ret_20")) - _num(frame.get("ret_20")).groupby(frame["date"], sort=False).transform("mean")
    frame["cand_market_relative_strength_60"] = _num(frame.get("ret_60")) - _num(frame.get("ret_60")).groupby(frame["date"], sort=False).transform("mean")

    frame["cand_value_proxy_close_to_cap_neg"] = -(close / safe_float_cap.replace(0.0, np.nan))
    frame["cand_quality_proxy_low_drawdown_lowvol"] = _rank_by_date(frame["cand_max_drawdown_60_neg"], frame["date"]) + _rank_by_date(frame["cand_volatility_60_neg"], frame["date"])
    frame["cand_growth_proxy_salesless_trend"] = _rank_by_date(frame["cand_ma20_ma120_gap"], frame["date"]) + _rank_by_date(frame["cand_efficiency_ratio_60"], frame["date"])
    frame["cand_composite_value_quality"] = _rank_by_date(frame["cand_value_proxy_close_to_cap_neg"], frame["date"]) + _rank_by_date(frame["cand_quality_proxy_low_drawdown_lowvol"], frame["date"])
    frame["cand_composite_momentum_quality"] = _rank_by_date(frame["cand_price_momentum_60"], frame["date"]) + _rank_by_date(frame["cand_quality_proxy_low_drawdown_lowvol"], frame["date"])
    frame["cand_composite_reversal_liquidity"] = _rank_by_date(frame["cand_reversal_5"], frame["date"]) + _rank_by_date(frame["cand_amihud_20_neg"], frame["date"])

    if include_ultra_grid:
        frame = _append_ultra_grid_factors(
            frame,
            close=close,
            open_=open_,
            high=high,
            low=low,
            amount=amount,
            volume=volume,
            ret_1=ret_1,
            float_cap=safe_float_cap,
            total_cap=safe_total_cap,
            close_col=close_col,
            include_columns=include_set,
        )
        frame = _append_matrix_factors(
            frame,
            close=close,
            open_=open_,
            high=high,
            low=low,
            amount=amount,
            volume=volume,
            ret_1=ret_1,
            float_cap=safe_float_cap,
            total_cap=safe_total_cap,
            close_col=close_col,
            include_columns=include_set,
        )

    temp_cols = [col for col in frame.columns if col.startswith("_cand_")]
    if temp_cols:
        frame = frame.drop(columns=temp_cols)
    return frame


def _append_matrix_factors(
    frame: pd.DataFrame,
    *,
    close: pd.Series,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    amount: pd.Series,
    volume: pd.Series,
    ret_1: pd.Series,
    float_cap: pd.Series,
    total_cap: pd.Series,
    close_col: str,
    include_columns: set[str] | None = None,
) -> pd.DataFrame:
    if not MATRIX_FACTOR_RECIPES:
        return frame
    recipes = [
        recipe for recipe in MATRIX_FACTOR_RECIPES
        if include_columns is None or recipe["raw_column"] in include_columns
    ]
    if not recipes:
        return frame
    required_signals = {recipe["a"] for recipe in recipes}
    required_signals.update(recipe["b"] for recipe in recipes if recipe.get("b"))
    base = _build_ultra_base_signals(
        frame,
        close=close,
        open_=open_,
        high=high,
        low=low,
        amount=amount,
        volume=volume,
        ret_1=ret_1,
        float_cap=float_cap,
        total_cap=total_cap,
        close_col=close_col,
        required_signals=required_signals,
    )
    generated: dict[str, pd.Series] = {}
    for recipe in recipes:
        a = base.get(recipe["a"])
        if a is None:
            continue
        ar = _rank_by_date(a, frame["date"]).astype("float32")
        kind = recipe["kind"]
        if kind == "base_rank":
            value = ar
        else:
            b = base.get(recipe["b"])
            if b is None:
                continue
            br = _rank_by_date(b, frame["date"]).astype("float32")
            if kind == "rank_mean":
                value = (ar + br) * 0.5
            elif kind == "rank_spread":
                value = ar - br
            elif kind == "rank_product":
                value = ar * br
            elif kind == "rank_gate_hi":
                value = ar.where(br >= 0.60, 0.0)
            elif kind == "rank_gate_lo":
                value = ar.where(br <= 0.40, 0.0)
            else:
                continue
        generated[recipe["raw_column"]] = pd.to_numeric(value, errors="coerce").astype("float32")
    if not generated:
        return frame
    return pd.concat([frame, pd.DataFrame(generated, index=frame.index)], axis=1)


def _append_ultra_grid_factors(
    frame: pd.DataFrame,
    *,
    close: pd.Series,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    amount: pd.Series,
    volume: pd.Series,
    ret_1: pd.Series,
    float_cap: pd.Series,
    total_cap: pd.Series,
    close_col: str,
    include_columns: set[str] | None = None,
) -> pd.DataFrame:
    if not ULTRA_GRID_FACTOR_RECIPES:
        return frame
    recipes = [
        recipe for recipe in ULTRA_GRID_FACTOR_RECIPES
        if include_columns is None or recipe["raw_column"] in include_columns
    ]
    if not recipes:
        return frame
    required_signals = {recipe["a"] for recipe in recipes}
    required_signals.update(recipe["b"] for recipe in recipes if recipe.get("b"))
    base = _build_ultra_base_signals(
        frame,
        close=close,
        open_=open_,
        high=high,
        low=low,
        amount=amount,
        volume=volume,
        ret_1=ret_1,
        float_cap=float_cap,
        total_cap=total_cap,
        close_col=close_col,
        required_signals=required_signals,
    )
    generated: dict[str, pd.Series] = {}
    for recipe in recipes:
        a = base.get(recipe["a"])
        if a is None:
            continue
        ar = _rank_by_date(a, frame["date"]).astype("float32")
        kind = recipe["kind"]
        if kind == "base_rank":
            value = ar
        else:
            b = base.get(recipe["b"])
            if b is None:
                continue
            br = _rank_by_date(b, frame["date"]).astype("float32")
            if kind == "rank_mean":
                value = (ar + br) * 0.5
            elif kind == "rank_spread":
                value = ar - br
            elif kind == "rank_product":
                value = ar * br
            elif kind == "rank_gate_hi":
                value = ar.where(br >= 0.60, 0.0)
            elif kind == "rank_gate_lo":
                value = ar.where(br <= 0.40, 0.0)
            elif kind == "rank_ratio":
                value = ar / (br + 0.05)
            else:
                continue
        generated[recipe["raw_column"]] = pd.to_numeric(value, errors="coerce").astype("float32")
    if not generated:
        return frame
    return pd.concat([frame, pd.DataFrame(generated, index=frame.index)], axis=1)


def _build_ultra_base_signals(
    frame: pd.DataFrame,
    *,
    close: pd.Series,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    amount: pd.Series,
    volume: pd.Series,
    ret_1: pd.Series,
    float_cap: pd.Series,
    total_cap: pd.Series,
    close_col: str,
    required_signals: set[str] | None = None,
) -> dict[str, pd.Series]:
    grouped = frame.groupby("symbol", group_keys=False, sort=False)
    signals: dict[str, pd.Series] = {}
    required = set(required_signals or ())
    for window in (1, 2, 3, 5, 10, 15, 20, 30, 40, 60, 90, 120, 180, 240):
        if required and f"ret_{window}" not in required and f"rev_{window}" not in required:
            continue
        if window == 1:
            ret = ret_1
        elif f"ret_{window}" in frame.columns:
            ret = _num(frame.get(f"ret_{window}"))
        elif close_col in frame.columns:
            ret = grouped[close_col].pct_change(window, fill_method=None)
        else:
            ret = pd.Series(np.nan, index=frame.index)
        if not required or f"ret_{window}" in required:
            signals[f"ret_{window}"] = ret
        if not required or f"rev_{window}" in required:
            signals[f"rev_{window}"] = -ret
    for window in (3, 5, 10, 20, 30, 60, 120, 180, 240):
        needed = {
            f"ma_gap_{window}",
            f"price_pos_{window}",
        }
        if required and not (needed & required):
            continue
        ma = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).mean()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        hi = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).max()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        lo = grouped[close_col].transform(lambda s, w=window: s.rolling(w, min_periods=w).min()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        if not required or f"ma_gap_{window}" in required:
            signals[f"ma_gap_{window}"] = close / pd.to_numeric(ma, errors="coerce").replace(0.0, np.nan) - 1.0
        if not required or f"price_pos_{window}" in required:
            signals[f"price_pos_{window}"] = (close - lo) / (hi - lo).replace(0.0, np.nan)
    downside = ret_1.where(ret_1 < 0.0, 0.0)
    for window in (5, 10, 20, 30, 60, 90, 120, 180):
        if not required or f"vol_neg_{window}" in required:
            signals[f"vol_neg_{window}"] = -_rolling_std(ret_1, frame, window)
        if not required or f"downvol_neg_{window}" in required:
            signals[f"downvol_neg_{window}"] = -_rolling_std(downside, frame, window)
        if not required or f"drawdown_neg_{window}" in required:
            signals[f"drawdown_neg_{window}"] = -_rolling_drawdown(close, frame, window).abs()
    amihud = ret_1.abs() / amount.replace(0.0, np.nan)
    turnover = amount / float_cap.replace(0.0, np.nan)
    for window in (3, 5, 10, 20, 30, 60, 90, 120):
        needs_amount = not required or f"amount_shock_{window}" in required
        needs_volume = not required or f"volume_shock_{window}" in required
        if needs_amount:
            amount_ma = grouped_apply(amount, frame, window, "mean")
            signals[f"amount_shock_{window}"] = amount / amount_ma.replace(0.0, np.nan) - 1.0
        if needs_volume:
            volume_ma = grouped_apply(volume, frame, window, "mean")
            signals[f"volume_shock_{window}"] = volume / volume_ma.replace(0.0, np.nan) - 1.0
        if not required or f"amihud_neg_{window}" in required:
            signals[f"amihud_neg_{window}"] = -grouped_apply(amihud, frame, window, "mean")
        if not required or f"turnover_{window}" in required:
            signals[f"turnover_{window}"] = grouped_apply(turnover, frame, window, "mean")
    price_range = (high - low).replace(0.0, np.nan)
    close_loc = (close - low) / price_range
    body = (close - open_) / price_range
    lower_shadow = (np.minimum(open_, close) - low) / price_range
    upper_shadow_neg = -((high - np.maximum(open_, close)) / price_range)
    for window in (3, 5, 10, 20, 30, 60):
        if not required or f"close_loc_mean_{window}" in required:
            signals[f"close_loc_mean_{window}"] = grouped_apply(close_loc, frame, window, "mean")
        if not required or f"body_mean_{window}" in required:
            signals[f"body_mean_{window}"] = grouped_apply(body, frame, window, "mean")
        if not required or f"lower_shadow_mean_{window}" in required:
            signals[f"lower_shadow_mean_{window}"] = grouped_apply(lower_shadow, frame, window, "mean")
        if not required or f"upper_shadow_neg_mean_{window}" in required:
            signals[f"upper_shadow_neg_mean_{window}"] = grouped_apply(upper_shadow_neg, frame, window, "mean")
        if not required or f"efficiency_{window}" in required:
            signals[f"efficiency_{window}"] = _efficiency_ratio(close, frame, window)
    if not required or "size_float_neg" in required:
        signals["size_float_neg"] = -np.log1p(float_cap)
    if not required or "size_total_neg" in required:
        signals["size_total_neg"] = -np.log1p(total_cap)
    if not required or "value_proxy" in required:
        signals["value_proxy"] = -(close / float_cap.replace(0.0, np.nan))
    if not required or "quality_proxy" in required:
        signals["quality_proxy"] = signals.get("drawdown_neg_60", pd.Series(np.nan, index=frame.index)) + signals.get("vol_neg_60", pd.Series(np.nan, index=frame.index))
    if not required or "macd_hist_12_26_9" in required or "macd_cross_strength_12_26_9" in required:
        ema12 = grouped[close_col].transform(lambda s: s.ewm(span=12, adjust=False, min_periods=12).mean()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        ema26 = grouped[close_col].transform(lambda s: s.ewm(span=26, adjust=False, min_periods=26).mean()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        dif = ema12 - ema26
        dea = dif.groupby(frame["symbol"], sort=False).transform(lambda s: s.ewm(span=9, adjust=False, min_periods=9).mean())
        macd_hist = dif - dea
        if not required or "macd_hist_12_26_9" in required:
            signals["macd_hist_12_26_9"] = macd_hist / close.replace(0.0, np.nan)
        if not required or "macd_cross_strength_12_26_9" in required:
            signals["macd_cross_strength_12_26_9"] = (macd_hist - macd_hist.groupby(frame["symbol"], sort=False).shift(1)) / close.replace(0.0, np.nan)
    for window in (6, 14):
        key = f"rsi_{window}_reversal"
        if required and key not in required:
            continue
        gain = ret_1.clip(lower=0.0)
        loss = (-ret_1.clip(upper=0.0)).replace(0.0, np.nan)
        avg_gain = grouped_apply(gain, frame, window, "mean")
        avg_loss = grouped_apply(loss, frame, window, "mean")
        rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss.replace(0.0, np.nan))
        signals[key] = (50.0 - rsi) / 50.0
    for window in (20, 55):
        key = f"turtle_breakout_{window}"
        if required and key not in required:
            continue
        high_roll = grouped[close_col].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=w).max()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        low_roll = grouped[close_col].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=w).min()) if close_col in frame.columns else pd.Series(np.nan, index=frame.index)
        signals[key] = (close - high_roll) / (high_roll - low_roll).replace(0.0, np.nan)
    if not required or "close_volume_ratio_20" in required:
        close_strength = ((close - low) / (high - low).replace(0.0, np.nan)).clip(0.0, 1.0)
        signals["close_volume_ratio_20"] = grouped_apply(volume * close_strength, frame, 20, "mean") / grouped_apply(volume, frame, 20, "mean").replace(0.0, np.nan)
    if not required or "large_order_proxy_20" in required:
        signed_turnover = amount * np.sign(ret_1.fillna(0.0))
        signals["large_order_proxy_20"] = grouped_apply(signed_turnover, frame, 20, "sum") / grouped_apply(amount, frame, 20, "sum").replace(0.0, np.nan)
    if not required or "low_noise_60" in required:
        trend_abs = _num(frame.get("ret_60", grouped[close_col].pct_change(60, fill_method=None) if close_col in frame.columns else pd.Series(np.nan, index=frame.index))).abs()
        noise = _rolling_std(ret_1, frame, 60).abs()
        signals["low_noise_60"] = trend_abs / (noise + 1e-6)
    if not required or "barra_beta_60_neg" in required:
        market_ret = ret_1.groupby(frame["date"], sort=False).transform("mean")
        signals["barra_beta_60_neg"] = -_rolling_beta(ret_1, market_ret, frame, 60)
    if not required or "barra_size_neg" in required:
        signals["barra_size_neg"] = -np.log1p(total_cap)
    if not required or "barra_value_proxy" in required:
        signals["barra_value_proxy"] = -(close / total_cap.replace(0.0, np.nan))
    if not required or "valuation_pe_proxy_neg" in required:
        pe = _num(frame.get("pe_ttm", frame.get("pe", pd.Series(np.nan, index=frame.index))))
        signals["valuation_pe_proxy_neg"] = -pe.where(pe > 0.0)
    if not required or "valuation_pb_proxy_neg" in required:
        pb = _num(frame.get("pb", frame.get("pb_lf", pd.Series(np.nan, index=frame.index))))
        signals["valuation_pb_proxy_neg"] = -pb.where(pb > 0.0)
    if not required or "profitability_proxy" in required:
        signals["profitability_proxy"] = _num(frame.get("roe", frame.get("gross_margin", pd.Series(np.nan, index=frame.index))))
    if not required or "growth_proxy" in required:
        signals["growth_proxy"] = _num(frame.get("revenue_yoy", frame.get("profit_yoy", pd.Series(np.nan, index=frame.index))))
    if not required or "cashflow_proxy" in required:
        free_cashflow = _num(frame.get("free_cashflow", frame.get("net_operate_cashflow", pd.Series(np.nan, index=frame.index))))
        signals["cashflow_proxy"] = free_cashflow / total_cap.replace(0.0, np.nan)
    if not required or "earnings_surprise_proxy" in required:
        signals["earnings_surprise_proxy"] = _num(frame.get("earnings_surprise", frame.get("profit_yoy", pd.Series(np.nan, index=frame.index))))
    if not required or "analyst_update_proxy" in required:
        signals["analyst_update_proxy"] = _num(frame.get("analyst_forecast_revision", frame.get("forecast_np_revision", pd.Series(np.nan, index=frame.index))))
    if not required or "sentiment_proxy" in required:
        signals["sentiment_proxy"] = _num(frame.get("news_sentiment", pd.Series(np.nan, index=frame.index)))
    if not required or "supply_chain_proxy" in required:
        signals["supply_chain_proxy"] = _num(frame.get("supply_chain_prosperity", pd.Series(np.nan, index=frame.index)))
    if not required or "social_heat_proxy" in required:
        signals["social_heat_proxy"] = _num(frame.get("social_discussion_heat", pd.Series(np.nan, index=frame.index)))
    return signals


def _price_col(close_col: str, prefix: str) -> str:
    suffix = str(close_col).removeprefix("close")
    return f"{prefix}{suffix}"


def _num(values) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(values, errors="coerce")


def _rank_by_date(values: pd.Series, dates: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").groupby(dates, sort=False).rank(pct=True)


def grouped_apply(values: pd.Series, frame: pd.DataFrame, window: int, op: str) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    grouped = series.groupby(frame["symbol"], sort=False)
    if op == "mean":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).mean())
    if op == "sum":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).sum())
    if op == "shift":
        return grouped.shift(window)
    raise ValueError(f"Unsupported grouped op: {op}")


def _rolling_std(values: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).std()
    )


def _rolling_cv(values: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    mean = series.groupby(frame["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())
    std = series.groupby(frame["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).std())
    return std / mean.abs().replace(0.0, np.nan)


def _rolling_drawdown(close: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    rolling_max = pd.to_numeric(close, errors="coerce").groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).max()
    )
    return pd.to_numeric(close, errors="coerce") / rolling_max.replace(0.0, np.nan) - 1.0


def _rolling_moment(values: pd.Series, frame: pd.DataFrame, window: int, kind: str) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    grouped = series.groupby(frame["symbol"], sort=False)
    if kind == "skew":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).skew())
    if kind == "kurt":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).kurt())
    raise ValueError(f"Unsupported moment: {kind}")


def _efficiency_ratio(close: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    price = pd.to_numeric(close, errors="coerce")
    change = price.groupby(frame["symbol"], sort=False).diff(window).abs()
    path = price.groupby(frame["symbol"], sort=False).transform(
        lambda s: s.diff().abs().rolling(window, min_periods=window).sum()
    )
    return change / path.replace(0.0, np.nan)


def _rolling_beta(y: pd.Series, x: pd.Series, frame: pd.DataFrame, window: int) -> pd.Series:
    yv = pd.to_numeric(y, errors="coerce")
    xv = pd.to_numeric(x, errors="coerce")
    mean_x = xv.groupby(frame["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())
    mean_y = yv.groupby(frame["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())
    cov = ((xv - mean_x) * (yv - mean_y)).groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).mean()
    )
    var = ((xv - mean_x) ** 2).groupby(frame["symbol"], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).mean()
    )
    return cov / var.replace(0.0, np.nan)


def _industry_residual(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    if "sector_parent" not in frame.columns:
        return series - series.groupby(frame["date"], sort=False).transform("mean")
    group_mean = series.groupby([frame["date"], frame["sector_parent"]], sort=False).transform("mean")
    return series - group_mean
