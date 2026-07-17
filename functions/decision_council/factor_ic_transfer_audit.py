"""Measure whether cabinet factor IC transfers into the exact run universe."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = (5, 10, 20)


def build_factor_ic_transfer_audit(
    alpha_proposals: pd.DataFrame,
    audit_prices: pd.DataFrame,
    *,
    factor_source_spec=None,
    candidate_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = _columns()
    if alpha_proposals is None or alpha_proposals.empty or audit_prices is None or audit_prices.empty:
        return pd.DataFrame(columns=columns)
    required = {"decision_date", "symbol", "model_name", "predicted_return_5d"}
    if not required.issubset(alpha_proposals.columns):
        return pd.DataFrame(columns=columns)

    proposals = alpha_proposals[list(required)].copy()
    proposals["decision_date"] = pd.to_datetime(proposals["decision_date"], errors="coerce")
    proposals["symbol"] = proposals["symbol"].astype(str)
    proposals["model_name"] = proposals["model_name"].astype(str)
    proposals["predicted_return_5d"] = pd.to_numeric(proposals["predicted_return_5d"], errors="coerce")
    proposals = proposals.dropna(subset=["decision_date", "symbol", "model_name", "predicted_return_5d"])
    if candidate_universe is not None and not candidate_universe.empty:
        date_column = "signal_date" if "signal_date" in candidate_universe.columns else "decision_date"
        if {date_column, "symbol"}.issubset(candidate_universe.columns):
            eligible = candidate_universe[[date_column, "symbol"]].copy()
            eligible = eligible.rename(columns={date_column: "decision_date"})
            eligible["decision_date"] = pd.to_datetime(eligible["decision_date"], errors="coerce")
            eligible["symbol"] = eligible["symbol"].astype(str)
            eligible = eligible.dropna().drop_duplicates()
            proposals = proposals.merge(eligible, on=["decision_date", "symbol"], how="inner")
    if proposals.empty:
        return pd.DataFrame(columns=columns)

    prices = audit_prices[["date", "symbol", "close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna().sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
    for horizon in HORIZONS:
        prices[f"forward_return_{horizon}d"] = (
            prices.groupby("symbol", sort=False)["close"].shift(-horizon) / prices["close"] - 1.0
        )
    outcomes = prices.rename(columns={"date": "decision_date"})[
        ["decision_date", "symbol"] + [f"forward_return_{h}d" for h in HORIZONS]
    ]
    data = proposals.merge(outcomes, on=["decision_date", "symbol"], how="left", validate="many_to_one")
    historical = _historical_metrics(factor_source_spec)
    role_map = dict(getattr(factor_source_spec, "role_map", None) or {})
    module_map = dict(getattr(factor_source_spec, "module_map", None) or {})
    family_map = dict(getattr(factor_source_spec, "family_map", None) or {})
    direction_map = dict(getattr(factor_source_spec, "direction_map", None) or {})
    horizon_map = dict(getattr(factor_source_spec, "horizon_map", None) or {})

    rows = []
    for model_name, model_data in data.groupby("model_name", sort=True):
        history = historical.get(str(model_name), {})
        for horizon in HORIZONS:
            outcome = f"forward_return_{horizon}d"
            daily_ic = []
            top5_returns = []
            top5_spreads = []
            observed_rows = 0
            for _, group in model_data[["decision_date", "predicted_return_5d", outcome]].dropna().groupby("decision_date"):
                if len(group) < 3 or group["predicted_return_5d"].nunique() < 2:
                    continue
                observed_rows += len(group)
                daily_ic.append(group["predicted_return_5d"].corr(group[outcome], method="spearman"))
                ranked = group.sort_values("predicted_return_5d", ascending=False)
                top_return = float(ranked.head(5)[outcome].mean())
                top5_returns.append(top_return)
                top5_spreads.append(top_return - float(group[outcome].mean()))
            ic = pd.Series(daily_ic, dtype=float).dropna()
            spread = pd.Series(top5_spreads, dtype=float).dropna()
            top_return = pd.Series(top5_returns, dtype=float).dropna()
            mean_ic = float(ic.mean()) if not ic.empty else np.nan
            std_ic = float(ic.std(ddof=1)) if len(ic) > 1 else np.nan
            historical_ic = pd.to_numeric(pd.Series([history.get("best_rank_ic_mean")]), errors="coerce").iloc[0]
            rows.append({
                "model_name": str(model_name),
                "raw_column": history.get("raw_column", ""),
                "role": role_map.get(str(model_name), history.get("role", "")),
                "module": module_map.get(str(model_name), history.get("module", "")),
                "family": family_map.get(str(model_name), history.get("family", "")),
                "direction": direction_map.get(str(model_name), history.get("direction", "higher_better")),
                "registered_best_horizon_days": horizon_map.get(str(model_name), history.get("best_horizon_days", 0)),
                "historical_best_rank_ic_mean": historical_ic,
                "historical_best_ic_ir": history.get("best_ic_ir", np.nan),
                "horizon_days": int(horizon),
                "observed_days": int(len(ic)),
                "observed_rows": int(observed_rows),
                "mean_daily_rank_ic": mean_ic,
                "std_daily_rank_ic": std_ic,
                "ic_ir": mean_ic / std_ic if pd.notna(std_ic) and std_ic > 0 else np.nan,
                "positive_ic_day_ratio": float(ic.gt(0.0).mean()) if not ic.empty else np.nan,
                "mean_top5_return": float(top_return.mean()) if not top_return.empty else np.nan,
                "mean_top5_spread_vs_model_universe": float(spread.mean()) if not spread.empty else np.nan,
                "positive_top5_spread_day_ratio": float(spread.gt(0.0).mean()) if not spread.empty else np.nan,
                "historical_current_sign_agreement": (
                    bool(float(historical_ic) * mean_ic > 0.0)
                    if pd.notna(historical_ic) and pd.notna(mean_ic) and float(historical_ic) != 0.0 and mean_ic != 0.0
                    else pd.NA
                ),
                "audit_status": "observed" if not ic.empty else "missing_outcomes",
            })
    return pd.DataFrame(rows, columns=columns)


def _historical_metrics(spec) -> dict[str, dict]:
    path = str(getattr(spec, "factor_cabinet_path", "") or "")
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return {
        str(row.get("factor_name", "")): dict(row)
        for row in payload.get("factors", [])
        if str(row.get("factor_name", ""))
    }


def _columns() -> list[str]:
    return [
        "model_name", "raw_column", "role", "module", "family", "direction",
        "registered_best_horizon_days", "historical_best_rank_ic_mean", "historical_best_ic_ir",
        "horizon_days", "observed_days", "observed_rows", "mean_daily_rank_ic",
        "std_daily_rank_ic", "ic_ir", "positive_ic_day_ratio", "mean_top5_return",
        "mean_top5_spread_vs_model_universe", "positive_top5_spread_day_ratio",
        "historical_current_sign_agreement", "audit_status",
    ]
