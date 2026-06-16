"""Rules-based safety council for phase-one governance."""
from __future__ import annotations

import pandas as pd

from config import (
    SAFETY_CRISIS_DRAWDOWN,
    SAFETY_CRISIS_CONFIRM_DAYS,
    SAFETY_CRISIS_LIQUIDITY_STRESS,
    SAFETY_HIGH_DRAWDOWN,
    SAFETY_HIGH_CONFIRM_DAYS,
    SAFETY_HIGH_LIQUIDITY_STRESS,
    SAFETY_PROXY_MAX_LAG_DAYS,
    SAFETY_WARNING_DRAWDOWN,
    SAFETY_WARNING_CONFIRM_DAYS,
    SAFETY_WARNING_LIQUIDITY_STRESS,
)
from functions.decision_council.contracts import SafetyDecision


class RuleBasedSafetyAgent:
    """Emit deterministic exposure caps from benchmark and liquidity stress."""

    def __init__(self, proxy_symbol: str | None, *, proxy_mode: str = "strict"):
        if proxy_mode not in {"strict", "degraded_backtest"}:
            raise ValueError("proxy_mode must be 'strict' or 'degraded_backtest'")
        if proxy_mode == "strict" and proxy_symbol is None:
            raise ValueError("strict safety mode requires a benchmark proxy")
        self.proxy_symbol = proxy_symbol
        self.proxy_mode = proxy_mode

    def build_daily_signals(self, feature_df: pd.DataFrame) -> pd.DataFrame:
        data = feature_df.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["amount"] = pd.to_numeric(data["amount"], errors="coerce")
        trading = data.get("is_trading", pd.Series(True, index=data.index)).fillna(False).astype(bool)
        eligible = data.get("instrument_type", pd.Series("stock", index=data.index)).isin(["stock", "etf_fund"])
        median_amount = data.groupby("symbol")["amount"].transform(
            lambda values: values.rolling(20, min_periods=5).median()
        )
        data["liquidity_stressed"] = trading & eligible & (data["amount"] < median_amount * 0.5)
        denominator = (trading & eligible).groupby(data["date"]).sum().replace(0, pd.NA)
        stressed = data["liquidity_stressed"].groupby(data["date"]).sum()
        liquidity = (stressed / denominator).fillna(0.0).rename("market_liquidity_stress_ratio")

        result = liquidity.reset_index()
        result["benchmark_drawdown_5d"] = pd.NA
        result["risk_level_lag_days"] = 0
        if self.proxy_symbol is not None:
            proxy = data[data["symbol"].astype(str) == self.proxy_symbol][["date", "close"]].copy()
            proxy["close"] = pd.to_numeric(proxy["close"], errors="coerce")
            proxy = proxy.dropna().drop_duplicates("date").sort_values("date")
            rolling_peak = proxy["close"].rolling(5, min_periods=1).max()
            proxy["benchmark_drawdown_5d"] = (rolling_peak - proxy["close"]) / rolling_peak
            result = result.drop(columns=["benchmark_drawdown_5d"]).merge(proxy, on="date", how="left")
            lag_days = _lag_days(result["benchmark_drawdown_5d"])
            result["benchmark_drawdown_5d"] = result["benchmark_drawdown_5d"].ffill(limit=SAFETY_PROXY_MAX_LAG_DAYS)
            result["risk_level_lag_days"] = lag_days
        result["raw_risk_level"] = result.apply(self._risk_level, axis=1)
        result["trigger_source"] = result.apply(self._trigger_source, axis=1)
        result["risk_level"], result["trigger_streak_days"] = _confirmed_risk_levels(result["raw_risk_level"])
        result["exposure_cap"] = result["risk_level"].map(
            {"normal": 1.0, "warning": 0.7, "high": 0.3, "crisis": 0.0}
        )
        result["proxy_symbol"] = self.proxy_symbol
        result["proxy_mode"] = self.proxy_mode
        result["degraded"] = self.proxy_symbol is None
        return result

    def decide(self, row) -> SafetyDecision:
        return SafetyDecision(
            decision_date=pd.Timestamp(row["date"]),
            risk_level=str(row["risk_level"]),
            exposure_cap=float(row["exposure_cap"]),
            benchmark_drawdown_5d=_optional_float(row.get("benchmark_drawdown_5d")),
            market_liquidity_stress_ratio=float(row["market_liquidity_stress_ratio"]),
            proxy_symbol=self.proxy_symbol,
            proxy_mode=self.proxy_mode,
            risk_level_lag_days=int(row.get("risk_level_lag_days", 0)),
            degraded=bool(row.get("degraded", False)),
            raw_risk_level=str(row.get("raw_risk_level", row["risk_level"])),
            trigger_source=str(row.get("trigger_source", "normal")),
            trigger_streak_days=int(row.get("trigger_streak_days", 0)),
        )

    @staticmethod
    def safety_sell_flow_impact(planned_sell_notional: float, market_total_amount: float) -> float:
        return float(planned_sell_notional) / float(market_total_amount) if market_total_amount > 0 else 0.0

    def _risk_level(self, row) -> str:
        drawdown = _optional_float(row.get("benchmark_drawdown_5d"))
        stress = float(row["market_liquidity_stress_ratio"])
        if (drawdown is not None and drawdown >= SAFETY_CRISIS_DRAWDOWN) or stress >= SAFETY_CRISIS_LIQUIDITY_STRESS:
            return "crisis"
        if (drawdown is not None and drawdown >= SAFETY_HIGH_DRAWDOWN) or stress >= SAFETY_HIGH_LIQUIDITY_STRESS:
            return "high"
        if (drawdown is not None and drawdown >= SAFETY_WARNING_DRAWDOWN) or stress >= SAFETY_WARNING_LIQUIDITY_STRESS:
            return "warning"
        return "normal"

    def _trigger_source(self, row) -> str:
        drawdown = _optional_float(row.get("benchmark_drawdown_5d"))
        stress = float(row["market_liquidity_stress_ratio"])
        level = self._risk_level(row)
        if level == "normal":
            return "normal"
        drawdown_hit = False
        liquidity_hit = False
        if level == "warning":
            drawdown_hit = drawdown is not None and drawdown >= SAFETY_WARNING_DRAWDOWN
            liquidity_hit = stress >= SAFETY_WARNING_LIQUIDITY_STRESS
        elif level == "high":
            drawdown_hit = drawdown is not None and drawdown >= SAFETY_HIGH_DRAWDOWN
            liquidity_hit = stress >= SAFETY_HIGH_LIQUIDITY_STRESS
        elif level == "crisis":
            drawdown_hit = drawdown is not None and drawdown >= SAFETY_CRISIS_DRAWDOWN
            liquidity_hit = stress >= SAFETY_CRISIS_LIQUIDITY_STRESS
        if drawdown_hit and liquidity_hit:
            return "both"
        if drawdown_hit:
            return "drawdown_only"
        if liquidity_hit:
            return "liquidity_only"
        return "normal"


def _optional_float(value) -> float | None:
    return None if pd.isna(value) else float(value)


def _lag_days(series: pd.Series) -> pd.Series:
    lag = []
    current = 0
    for value in series:
        current = current + 1 if pd.isna(value) else 0
        lag.append(current)
    return pd.Series(lag, index=series.index, dtype=int)


def _confirmed_risk_levels(raw_levels: pd.Series) -> tuple[pd.Series, pd.Series]:
    order = {"normal": 0, "warning": 1, "high": 2, "crisis": 3}
    reverse = {value: key for key, value in order.items()}
    confirms = {
        1: int(SAFETY_WARNING_CONFIRM_DAYS),
        2: int(SAFETY_HIGH_CONFIRM_DAYS),
        3: int(SAFETY_CRISIS_CONFIRM_DAYS),
    }
    confirmed = []
    streaks = []
    consecutive = {1: 0, 2: 0, 3: 0}
    for raw_level in raw_levels.fillna("normal").astype(str):
        score = order.get(raw_level, 0)
        for threshold in (1, 2, 3):
            consecutive[threshold] = consecutive[threshold] + 1 if score >= threshold else 0
        confirmed_score = 0
        confirmed_streak = 0
        for threshold in (3, 2, 1):
            if consecutive[threshold] >= confirms[threshold]:
                confirmed_score = threshold
                confirmed_streak = consecutive[threshold]
                break
        confirmed.append(reverse[confirmed_score])
        streaks.append(confirmed_streak)
    return pd.Series(confirmed, index=raw_levels.index), pd.Series(streaks, index=raw_levels.index, dtype=int)
