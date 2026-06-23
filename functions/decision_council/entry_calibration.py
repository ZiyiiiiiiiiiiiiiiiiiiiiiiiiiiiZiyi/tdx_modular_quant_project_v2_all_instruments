"""Rolling, non-ML calibration for governance entry probabilities.

The calibrator only uses candidate observations whose forward horizon has
already matured inside the backtest loop. It is intentionally simple and
auditable: bucketed empirical win rates and payoff estimates, with conservative
fallbacks when there is not enough history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import pandas as pd


CALIBRATION_FEATURE_COLUMNS = (
    "alpha_percentile",
    "expected_return_5d",
    "aggregate_confidence",
    "volatility_20",
    "entry_orderflow_confirm_count",
    "entry_quality_score",
)


@dataclass
class RollingEntryCalibrator:
    min_bucket_samples: int = 30
    min_global_samples: int = 80
    max_history_rows: int = 80_000
    cost_buffer: float = 0.0015
    pending_rows: list[dict] = field(default_factory=list)
    history_rows: list[dict] = field(default_factory=list)
    _history_version: int = 0
    _stats_cache: dict[int, dict] = field(default_factory=dict)

    def mature(self, *, day_index: int, price_frame: pd.DataFrame) -> int:
        """Move pending candidate snapshots into history once their horizon is observable."""
        if not self.pending_rows:
            return 0
        if price_frame is None or price_frame.empty or "symbol" not in price_frame.columns:
            return 0
        close_col = "close_nominal" if "close_nominal" in price_frame.columns else "close"
        if close_col not in price_frame.columns:
            return 0
        prices = (
            price_frame[["symbol", close_col]]
            .dropna()
            .drop_duplicates("symbol", keep="last")
            .set_index("symbol")[close_col]
        )
        matured: list[dict] = []
        remaining: list[dict] = []
        for row in self.pending_rows:
            if int(row["maturity_index"]) > int(day_index):
                remaining.append(row)
                continue
            symbol = str(row["symbol"])
            if symbol not in prices.index:
                remaining.append(row)
                continue
            entry_price = float(row.get("entry_price", 0.0) or 0.0)
            exit_price = float(pd.to_numeric(pd.Series([prices.loc[symbol]]), errors="coerce").fillna(0.0).iloc[0])
            if entry_price <= 0.0 or exit_price <= 0.0:
                continue
            outcome = dict(row)
            outcome["exit_day_index"] = int(day_index)
            outcome["exit_price"] = exit_price
            outcome["forward_return"] = exit_price / entry_price - 1.0
            outcome["win"] = bool(outcome["forward_return"] > 0.0)
            matured.append(outcome)
        self.pending_rows = remaining
        if matured:
            self.history_rows.extend(matured)
            if len(self.history_rows) > self.max_history_rows:
                self.history_rows = self.history_rows[-self.max_history_rows :]
            self._history_version += 1
            self._stats_cache.clear()
        return len(matured)

    def schedule_candidates(
        self,
        candidates: pd.DataFrame,
        *,
        day_index: int,
        horizon_days: int,
        regime_name: str,
    ) -> None:
        """Store today's candidate features for future calibration outcomes."""
        if candidates is None or candidates.empty:
            return
        close_col = "close_nominal" if "close_nominal" in candidates.columns else "close"
        if close_col not in candidates.columns:
            return
        data = candidates.copy()
        data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
        data = data.dropna(subset=["symbol", close_col])
        if data.empty:
            return
        for _, row in data.iterrows():
            entry_price = float(row[close_col])
            if entry_price <= 0.0:
                continue
            payload = {
                "symbol": str(row["symbol"]),
                "entry_day_index": int(day_index),
                "maturity_index": int(day_index) + int(horizon_days),
                "horizon_days": int(horizon_days),
                "entry_price": entry_price,
                "regime_bucket": _regime_bucket(regime_name),
                "alpha_bucket": _alpha_bucket(row.get("alpha_percentile", 0.5)),
                "flow_bucket": _flow_bucket(row.get("entry_orderflow_confirm_count", 0)),
            }
            for column in CALIBRATION_FEATURE_COLUMNS:
                payload[column] = _safe_float(row.get(column), 0.0)
            self.pending_rows.append(payload)

    def score_candidates(
        self,
        candidates: pd.DataFrame,
        *,
        regime_name: str,
        horizon_days: int,
    ) -> pd.DataFrame:
        """Attach calibrated probability and expected-edge fields to candidates."""
        data = candidates.copy()
        if data.empty:
            return data
        stats_bundle = self._stats_bundle(int(horizon_days))
        scored = data.reset_index(drop=True)
        scored["_alpha_bucket"] = scored["alpha_percentile"].map(_alpha_bucket) if "alpha_percentile" in scored.columns else "p00_50"
        scored["_flow_bucket"] = scored.get("entry_orderflow_confirm_count", pd.Series(0, index=scored.index)).map(_flow_bucket)
        scored["_regime_bucket"] = _regime_bucket(regime_name)

        fallback = _fallback_frame(scored, horizon_days=horizon_days, cost_buffer=self.cost_buffer)
        exact = _lookup_stats(
            scored,
            stats_bundle.get("exact", pd.DataFrame()),
            key_columns=["_alpha_bucket", "_flow_bucket", "_regime_bucket"],
        )
        alpha_only = _lookup_stats(
            scored,
            stats_bundle.get("alpha", pd.DataFrame()),
            key_columns=["_alpha_bucket"],
        )
        global_stats = stats_bundle.get("global")
        for column in ("sample_count", "p_win", "p_win_lower", "avg_win", "avg_loss"):
            exact[column] = pd.to_numeric(exact[column], errors="coerce")
            alpha_only[column] = pd.to_numeric(alpha_only[column], errors="coerce")
            scored[column] = exact[column].where(exact["sample_count"] >= self.min_bucket_samples, alpha_only[column])
            if global_stats is not None:
                scored[column] = scored[column].where(scored["sample_count"] >= self.min_bucket_samples, global_stats[column])
            scored[column] = pd.to_numeric(scored[column], errors="coerce").fillna(fallback[column])

        edge = (
            scored["p_win"].astype(float) * scored["avg_win"].astype(float)
            - (1.0 - scored["p_win"].astype(float)) * scored["avg_loss"].astype(float)
            - self.cost_buffer
        )
        conservative_edge = (
            scored["p_win_lower"].astype(float) * scored["avg_win"].astype(float)
            - (1.0 - scored["p_win_lower"].astype(float)) * scored["avg_loss"].astype(float)
            - self.cost_buffer
        )
        volatility = pd.to_numeric(scored.get("volatility_20", pd.Series(0.02, index=scored.index)), errors="coerce").fillna(0.02).clip(lower=0.005)
        scored[f"p_win_{horizon_days}d_calibrated"] = scored["p_win"].astype(float)
        scored[f"p_win_{horizon_days}d_wilson_lower"] = scored["p_win_lower"].astype(float)
        scored[f"avg_win_{horizon_days}d_by_bucket"] = scored["avg_win"].astype(float)
        scored[f"avg_loss_{horizon_days}d_by_bucket"] = scored["avg_loss"].astype(float)
        scored[f"expected_edge_{horizon_days}d"] = edge.astype(float)
        scored[f"conservative_expected_edge_{horizon_days}d"] = conservative_edge.astype(float)
        scored[f"edge_to_risk_{horizon_days}d"] = (edge / volatility).astype(float)
        scored[f"conservative_edge_to_risk_{horizon_days}d"] = (conservative_edge / volatility).astype(float)
        scored[f"entry_calibration_sample_count_{horizon_days}d"] = scored["sample_count"].fillna(0).astype(int)
        scored[f"entry_calibration_trust_{horizon_days}d"] = (
            scored["sample_count"].astype(float) / max(float(self.min_global_samples), 1.0)
        ).clip(0.0, 1.0)
        scored = scored.drop(columns=["_alpha_bucket", "_flow_bucket", "_regime_bucket", "sample_count", "p_win", "p_win_lower", "avg_win", "avg_loss"])
        return scored

    def _stats_bundle(self, horizon_days: int) -> dict:
        cached = self._stats_cache.get(int(horizon_days))
        if cached is not None and cached.get("version") == self._history_version:
            return cached
        history = pd.DataFrame(self.history_rows)
        if history.empty or "horizon_days" not in history.columns:
            bundle = {"version": self._history_version, "exact": pd.DataFrame(), "alpha": pd.DataFrame(), "global": None}
            self._stats_cache[int(horizon_days)] = bundle
            return bundle
        history = history[history["horizon_days"].astype(int).eq(int(horizon_days))].copy()
        if history.empty:
            bundle = {"version": self._history_version, "exact": pd.DataFrame(), "alpha": pd.DataFrame(), "global": None}
            self._stats_cache[int(horizon_days)] = bundle
            return bundle
        exact = _group_stats(history, ["alpha_bucket", "flow_bucket", "regime_bucket"])
        alpha = _group_stats(history, ["alpha_bucket"])
        global_stats = _empirical_stats(history, min_samples=self.min_global_samples)
        bundle = {
            "version": self._history_version,
            "exact": exact.rename(columns={
                "alpha_bucket": "_alpha_bucket",
                "flow_bucket": "_flow_bucket",
                "regime_bucket": "_regime_bucket",
            }),
            "alpha": alpha.rename(columns={"alpha_bucket": "_alpha_bucket"}),
            "global": global_stats,
        }
        self._stats_cache[int(horizon_days)] = bundle
        return bundle


def _empirical_stats(frame: pd.DataFrame, *, min_samples: int) -> dict | None:
    if frame is None or frame.empty or len(frame) < int(min_samples):
        return None
    returns = pd.to_numeric(frame["forward_return"], errors="coerce").dropna()
    if len(returns) < int(min_samples):
        return None
    wins = returns[returns > 0.0]
    losses = returns[returns <= 0.0]
    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = abs(float(losses.mean())) if not losses.empty else 0.0
    return {
        "sample_count": int(len(returns)),
        "p_win": float((returns > 0.0).mean()),
        "p_win_lower": _wilson_lower(int((returns > 0.0).sum()), int(len(returns))),
        "avg_win": max(avg_win, 0.002),
        "avg_loss": max(avg_loss, 0.002),
    }


def _group_stats(frame: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    output_columns = list(key_columns) + ["sample_count", "p_win", "p_win_lower", "avg_win", "avg_loss"]
    if frame is None or frame.empty or "forward_return" not in frame.columns:
        return pd.DataFrame(columns=output_columns)
    data = frame.copy()
    data["forward_return"] = pd.to_numeric(data["forward_return"], errors="coerce")
    data = data.dropna(subset=["forward_return"])
    if data.empty:
        return pd.DataFrame(columns=output_columns)

    grouped = data.groupby(key_columns, dropna=False)["forward_return"]
    result = grouped.agg(
        sample_count="count",
        p_win=lambda values: float((values > 0.0).mean()),
        p_win_lower=lambda values: _wilson_lower(int((values > 0.0).sum()), int(len(values))),
        avg_win=lambda values: max(float(values[values > 0.0].mean()) if (values > 0.0).any() else 0.0, 0.002),
        avg_loss=lambda values: max(abs(float(values[values <= 0.0].mean())) if (values <= 0.0).any() else 0.0, 0.002),
    ).reset_index()
    result["sample_count"] = pd.to_numeric(result["sample_count"], errors="coerce").fillna(0).astype(int)
    return result[output_columns]


def _lookup_stats(scored: pd.DataFrame, table: pd.DataFrame, *, key_columns: list[str]) -> pd.DataFrame:
    stat_columns = ["sample_count", "p_win", "p_win_lower", "avg_win", "avg_loss"]
    empty = pd.DataFrame({column: pd.NA for column in stat_columns}, index=scored.index)
    if table is None or table.empty:
        return empty
    missing = [column for column in key_columns + stat_columns if column not in table.columns]
    if missing:
        return empty
    left = scored[key_columns].reset_index(drop=True)
    merged = left.merge(table[key_columns + stat_columns], on=key_columns, how="left")
    merged.index = scored.index
    return merged[stat_columns]


def _fallback_frame(scored: pd.DataFrame, *, horizon_days: int, cost_buffer: float) -> pd.DataFrame:
    index = scored.index
    alpha = (
        pd.to_numeric(scored.get("alpha_percentile", pd.Series(0.5, index=index)), errors="coerce")
        .fillna(0.5)
        .clip(0.0, 1.0)
    )
    expected = (
        pd.to_numeric(scored.get("expected_return_5d", pd.Series(0.0, index=index)), errors="coerce")
        .fillna(0.0)
    )
    confidence = (
        pd.to_numeric(scored.get("aggregate_confidence", pd.Series(0.5, index=index)), errors="coerce")
        .fillna(0.5)
        .clip(0.0, 1.0)
    )
    flow = (
        pd.to_numeric(scored.get("entry_orderflow_confirm_count", pd.Series(0.0, index=index)), errors="coerce")
        .fillna(0.0)
        .clip(0.0, 4.0)
        / 4.0
    )
    expected_scaled = (expected / 0.03).clip(-1.0, 1.0)
    p_win = (
        0.47
        + 0.10 * (alpha - 0.5)
        + 0.05 * expected_scaled
        + 0.03 * (confidence - 0.5)
        + 0.03 * (flow - 0.5)
    ).clip(0.35, 0.65)
    p_win_lower = (p_win - 0.08).clip(0.30, 0.58)
    scale = max(float(horizon_days) / 5.0, 1.0)
    avg_win = (0.018 * scale + expected.clip(lower=0.0) * 0.50).clip(lower=0.002)
    avg_loss = (0.016 * scale + (-expected.clip(upper=0.0)) * 0.50 + float(cost_buffer)).clip(lower=0.002)
    return pd.DataFrame(
        {
            "sample_count": 0,
            "p_win": p_win.astype(float),
            "p_win_lower": p_win_lower.astype(float),
            "avg_win": avg_win.astype(float),
            "avg_loss": avg_loss.astype(float),
        },
        index=index,
    )


def _fallback_stats(row, *, horizon_days: int, cost_buffer: float) -> dict:
    alpha = _safe_float(row.get("alpha_percentile"), 0.5)
    expected = _safe_float(row.get("expected_return_5d"), 0.0)
    confidence = _safe_float(row.get("aggregate_confidence"), 0.5)
    flow = min(max(_safe_float(row.get("entry_orderflow_confirm_count"), 0.0) / 4.0, 0.0), 1.0)
    p_win = (
        0.47
        + 0.10 * (alpha - 0.5)
        + 0.05 * max(min(expected / 0.03, 1.0), -1.0)
        + 0.03 * (confidence - 0.5)
        + 0.03 * (flow - 0.5)
    )
    scale = max(float(horizon_days) / 5.0, 1.0)
    return {
        "sample_count": 0,
        "p_win": float(min(max(p_win, 0.35), 0.65)),
        "p_win_lower": float(min(max(p_win - 0.08, 0.30), 0.58)),
        "avg_win": float(0.018 * scale + max(expected, 0.0) * 0.50),
        "avg_loss": float(0.016 * scale + abs(min(expected, 0.0)) * 0.50 + cost_buffer),
    }


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = float(wins) / float(n)
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return max(0.0, float((centre - margin) / denom))


def _alpha_bucket(value) -> str:
    numeric = min(max(_safe_float(value, 0.5), 0.0), 1.0)
    if numeric >= 0.90:
        return "p90_100"
    if numeric >= 0.80:
        return "p80_90"
    if numeric >= 0.65:
        return "p65_80"
    if numeric >= 0.50:
        return "p50_65"
    return "p00_50"


def _flow_bucket(value) -> str:
    numeric = int(_safe_float(value, 0.0))
    if numeric >= 3:
        return "flow3p"
    if numeric >= 1:
        return "flow1_2"
    return "flow0"


def _regime_bucket(regime_name: str) -> str:
    regime = str(regime_name).lower()
    if regime in {"bull", "rebound"}:
        return "risk_on"
    if regime in {"neutral", "weak"}:
        return "neutral_weak"
    return "risk_off"


def _safe_float(value, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])
