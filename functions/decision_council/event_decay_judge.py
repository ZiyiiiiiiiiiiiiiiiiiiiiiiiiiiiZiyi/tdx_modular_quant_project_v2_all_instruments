"""Event decay judge for structured event factors."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


EVENT_HORIZONS = (1, 3, 5, 10, 20)


def run_event_decay_judge(
    event_features: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    output_dir: str | Path,
    min_event_count: int = 100,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary = build_event_decay_summary(event_features, prices, min_event_count=min_event_count)
    summary.to_csv(output / "event_judge_summary.csv", index=False, encoding="utf-8-sig")
    summary[summary["decision"].eq("promote_candidate")].to_csv(output / "event_admitted.csv", index=False, encoding="utf-8-sig")
    summary[summary["decision"].eq("watchlist")].to_csv(output / "event_watchlist.csv", index=False, encoding="utf-8-sig")
    summary[summary["decision"].eq("reject_or_rework")].to_csv(output / "event_rejected.csv", index=False, encoding="utf-8-sig")
    (output / "event_decay_report.md").write_text(_render_event_report(summary), encoding="utf-8")
    return {
        "event_judge_summary": output / "event_judge_summary.csv",
        "event_admitted": output / "event_admitted.csv",
        "event_watchlist": output / "event_watchlist.csv",
        "event_rejected": output / "event_rejected.csv",
        "event_decay_report": output / "event_decay_report.md",
    }


def build_event_decay_summary(event_features: pd.DataFrame, prices: pd.DataFrame, *, min_event_count: int = 100) -> pd.DataFrame:
    if event_features is None or event_features.empty:
        return pd.DataFrame(columns=_columns())
    close_col = "close_nominal" if prices is not None and "close_nominal" in prices.columns else "close"
    if prices is None or prices.empty or close_col not in prices.columns:
        raise ValueError("Event decay judge requires prices with close or close_nominal")
    px = prices.copy()
    symbol_col = "stock_code" if "stock_code" in px.columns else "symbol"
    px["stock_code"] = px[symbol_col].astype(str)
    px["trade_date"] = pd.to_datetime(px.get("trade_date", px.get("date")), errors="coerce")
    px[close_col] = pd.to_numeric(px[close_col], errors="coerce")
    for horizon in EVENT_HORIZONS:
        px[f"return_{horizon}d"] = px.groupby("stock_code", sort=False)[close_col].shift(-horizon) / px[close_col] - 1.0
    market = px.groupby("trade_date")[[f"return_{h}d" for h in EVENT_HORIZONS]].mean().add_prefix("market_").reset_index()
    data = event_features.copy()
    data["stock_code"] = data["stock_code"].astype(str)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.merge(px[["stock_code", "trade_date", *[f"return_{h}d" for h in EVENT_HORIZONS]]], on=["stock_code", "trade_date"], how="left")
    data = data.merge(market, on="trade_date", how="left")
    factor_cols = [col for col in event_features.columns if col not in {"stock_code", "trade_date"}]
    rows = []
    for factor in factor_cols:
        active = data[pd.to_numeric(data[factor], errors="coerce").fillna(0.0).abs() > 0.0].copy()
        if active.empty:
            rows.append(_row(factor, 0, np.nan, np.nan, np.nan, "reject_or_rework", "no_events"))
            continue
        horizon_rows = []
        for horizon in EVENT_HORIZONS:
            excess = pd.to_numeric(active[f"return_{horizon}d"], errors="coerce") - pd.to_numeric(active[f"market_return_{horizon}d"], errors="coerce")
            horizon_rows.append(
                {
                    "horizon_days": horizon,
                    "event_count": int(excess.notna().sum()),
                    "avg_excess_return": float(excess.mean()) if excess.notna().any() else np.nan,
                    "median_excess_return": float(excess.median()) if excess.notna().any() else np.nan,
                    "win_rate": float((excess.dropna() > 0.0).mean()) if excess.notna().any() else np.nan,
                    "max_adverse_return": float(excess.min()) if excess.notna().any() else np.nan,
                }
            )
        best = pd.DataFrame(horizon_rows).sort_values(["avg_excess_return", "win_rate"], ascending=[False, False]).iloc[0]
        decision = "promote_candidate" if best["event_count"] >= min_event_count and best["win_rate"] >= 0.53 and best["avg_excess_return"] >= 0.002 else "watchlist" if best["event_count"] >= max(20, min_event_count // 3) else "reject_or_rework"
        reason = "event_decay_pass" if decision == "promote_candidate" else "insufficient_event_strength_or_count"
        rows.append(_row(factor, best["event_count"], best["avg_excess_return"], best["win_rate"], best["max_adverse_return"], decision, reason, best["horizon_days"]))
    return pd.DataFrame(rows, columns=_columns())


def _row(factor, count, avg, win, adverse, decision, reason, horizon=pd.NA):
    return {
        "factor_name": factor,
        "best_horizon_days": horizon,
        "event_count": count,
        "avg_excess_return": avg,
        "median_excess_return": pd.NA,
        "win_rate": win,
        "max_adverse_return": adverse,
        "decision": decision,
        "reason": reason,
    }


def _columns():
    return ["factor_name", "best_horizon_days", "event_count", "avg_excess_return", "median_excess_return", "win_rate", "max_adverse_return", "decision", "reason"]


def _render_event_report(summary: pd.DataFrame) -> str:
    counts = summary["decision"].value_counts().to_dict() if summary is not None and not summary.empty else {}
    return "# Event Decay Judge Report\n\n" + f"Decision counts: {counts}\n"
