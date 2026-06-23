"""Rules-based safety council for phase-one governance."""
from __future__ import annotations

import pandas as pd

from config import (
    SAFETY_CRISIS_CONFIRM_DAYS,
    SAFETY_CRISIS_DRAWDOWN,
    SAFETY_CRISIS_EXIT_DAYS,
    SAFETY_CRISIS_EXPOSURE_CAP,
    SAFETY_CRISIS_LIQUIDITY_STRESS,
    SAFETY_HARD_FREEZE_EXPOSURE_CAP,
    SAFETY_HIGH_CONFIRM_DAYS,
    SAFETY_HIGH_DRAWDOWN,
    SAFETY_HIGH_EXIT_DAYS,
    SAFETY_HIGH_EXPOSURE_CAP,
    SAFETY_HIGH_LIQUIDITY_STRESS,
    SAFETY_PROXY_MAX_LAG_DAYS,
    SAFETY_STRUCTURAL_BEAR_BUDGET,
    SAFETY_STRUCTURAL_BEAR_UNDERWATER,
    SAFETY_STRUCTURAL_NEUTRAL_BUDGET,
    SAFETY_STRUCTURAL_NEUTRAL_UNDERWATER,
    SAFETY_STRUCTURAL_WEAK_BUDGET,
    SAFETY_STRUCTURAL_WEAK_UNDERWATER,
    SAFETY_WARNING_CONFIRM_DAYS,
    SAFETY_WARNING_DRAWDOWN,
    SAFETY_WARNING_EXIT_DAYS,
    SAFETY_WARNING_EXPOSURE_CAP,
    SAFETY_WARNING_LIQUIDITY_STRESS,
)
from functions.decision_council.contracts import SafetyDecision


class RuleBasedSafetyAgent:
    """Emit deterministic exposure caps from benchmark shock and liquidity stress."""

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
        for column in (
            "benchmark_drawdown_5d",
            "benchmark_drawdown_20d",
            "benchmark_return_5d",
            "benchmark_return_20d",
            "benchmark_underwater_from_peak",
        ):
            result[column] = pd.NA
        result["risk_level_lag_days"] = 0

        if self.proxy_symbol is not None:
            proxy_columns = ["date", "symbol"]
            if "close_nominal" in data.columns:
                proxy_columns.append("close_nominal")
            proxy_columns.append("close")
            proxy = data[data["symbol"].astype(str) == self.proxy_symbol][proxy_columns].copy()
            price_column = "close_nominal" if "close_nominal" in proxy.columns else "close"
            proxy["proxy_close"] = pd.to_numeric(proxy[price_column], errors="coerce")
            proxy = proxy.dropna(subset=["proxy_close"]).drop_duplicates("date").sort_values("date")
            proxy["rolling_peak_5d"] = proxy["proxy_close"].rolling(5, min_periods=1).max()
            proxy["rolling_peak_20d"] = proxy["proxy_close"].rolling(20, min_periods=5).max()
            proxy["benchmark_drawdown_5d"] = (
                (proxy["rolling_peak_5d"] - proxy["proxy_close"]) / proxy["rolling_peak_5d"]
            )
            proxy["benchmark_drawdown_20d"] = (
                (proxy["rolling_peak_20d"] - proxy["proxy_close"]) / proxy["rolling_peak_20d"]
            )
            proxy["benchmark_return_5d"] = proxy["proxy_close"] / proxy["proxy_close"].shift(5) - 1.0
            proxy["benchmark_return_20d"] = proxy["proxy_close"] / proxy["proxy_close"].shift(20) - 1.0
            running_peak = proxy["proxy_close"].cummax()
            proxy["benchmark_underwater_from_peak"] = (
                (running_peak - proxy["proxy_close"]) / running_peak
            )
            keep_columns = [
                "date",
                "benchmark_drawdown_5d",
                "benchmark_drawdown_20d",
                "benchmark_return_5d",
                "benchmark_return_20d",
                "benchmark_underwater_from_peak",
            ]
            result = result.drop(
                columns=[
                    "benchmark_drawdown_5d",
                    "benchmark_drawdown_20d",
                    "benchmark_return_5d",
                    "benchmark_return_20d",
                    "benchmark_underwater_from_peak",
                ]
            ).merge(proxy[keep_columns], on="date", how="left")
            lag_days = _lag_days(result["benchmark_drawdown_5d"])
            for column in (
                "benchmark_drawdown_5d",
                "benchmark_drawdown_20d",
                "benchmark_return_5d",
                "benchmark_return_20d",
                "benchmark_underwater_from_peak",
            ):
                result[column] = result[column].ffill(limit=SAFETY_PROXY_MAX_LAG_DAYS)
            result["risk_level_lag_days"] = lag_days

        result["structural_regime_level"] = result.apply(self._structural_regime_level, axis=1)
        result["regime_exposure_budget"] = result["structural_regime_level"].map(
            {
                "bull": 1.0,
                "neutral": SAFETY_STRUCTURAL_NEUTRAL_BUDGET,
                "weak": SAFETY_STRUCTURAL_WEAK_BUDGET,
                "bear": SAFETY_STRUCTURAL_BEAR_BUDGET,
            }
        ).fillna(1.0)
        result["raw_risk_level"] = result.apply(self._risk_level, axis=1)
        result["trigger_source"] = result.apply(self._trigger_source, axis=1)
        result["risk_level"], result["trigger_streak_days"] = _confirmed_risk_levels(result["raw_risk_level"])
        result["safety_exposure_cap"] = result["risk_level"].map(
            {
                "normal": 1.0,
                "warning": SAFETY_WARNING_EXPOSURE_CAP,
                "high": SAFETY_HIGH_EXPOSURE_CAP,
                "crisis": SAFETY_CRISIS_EXPOSURE_CAP,
            }
        ).fillna(1.0)
        result["hard_freeze_active"] = result.apply(self._hard_freeze_active, axis=1)
        result["exposure_cap"] = result.apply(self._final_exposure_cap, axis=1)
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
            benchmark_drawdown_20d=_optional_float(row.get("benchmark_drawdown_20d")),
            benchmark_return_5d=_optional_float(row.get("benchmark_return_5d")),
            benchmark_return_20d=_optional_float(row.get("benchmark_return_20d")),
            benchmark_underwater_from_peak=_optional_float(row.get("benchmark_underwater_from_peak")),
            structural_regime_level=str(row.get("structural_regime_level", "bull")),
            regime_exposure_budget=float(row.get("regime_exposure_budget", 1.0)),
            safety_exposure_cap=float(row.get("safety_exposure_cap", row.get("exposure_cap", 1.0))),
            hard_freeze_active=bool(row.get("hard_freeze_active", False)),
        )

    @staticmethod
    def safety_sell_flow_impact(planned_sell_notional: float, market_total_amount: float) -> float:
        return float(planned_sell_notional) / float(market_total_amount) if market_total_amount > 0 else 0.0

    def _risk_level(self, row) -> str:
        drawdown_5d = _optional_float(row.get("benchmark_drawdown_5d"))
        return_5d = _optional_float(row.get("benchmark_return_5d"))
        stress = float(row["market_liquidity_stress_ratio"])
        benchmark_shock = _benchmark_shock_score(drawdown_5d, return_5d)
        if benchmark_shock >= SAFETY_CRISIS_DRAWDOWN or stress >= SAFETY_CRISIS_LIQUIDITY_STRESS:
            return "crisis"
        if benchmark_shock >= SAFETY_HIGH_DRAWDOWN or stress >= SAFETY_HIGH_LIQUIDITY_STRESS:
            return "high"
        if benchmark_shock >= SAFETY_WARNING_DRAWDOWN or stress >= SAFETY_WARNING_LIQUIDITY_STRESS:
            return "warning"
        return "normal"

    def _trigger_source(self, row) -> str:
        drawdown_5d = _optional_float(row.get("benchmark_drawdown_5d"))
        return_5d = _optional_float(row.get("benchmark_return_5d"))
        stress = float(row["market_liquidity_stress_ratio"])
        level = self._risk_level(row)
        if level == "normal":
            return "normal"
        drawdown_hit = False
        liquidity_hit = False
        benchmark_shock = _benchmark_shock_score(drawdown_5d, return_5d)
        if level == "warning":
            drawdown_hit = benchmark_shock >= SAFETY_WARNING_DRAWDOWN
            liquidity_hit = stress >= SAFETY_WARNING_LIQUIDITY_STRESS
        elif level == "high":
            drawdown_hit = benchmark_shock >= SAFETY_HIGH_DRAWDOWN
            liquidity_hit = stress >= SAFETY_HIGH_LIQUIDITY_STRESS
        elif level == "crisis":
            drawdown_hit = benchmark_shock >= SAFETY_CRISIS_DRAWDOWN
            liquidity_hit = stress >= SAFETY_CRISIS_LIQUIDITY_STRESS
        if drawdown_hit and liquidity_hit:
            return "both"
        if drawdown_hit:
            return "drawdown_only"
        if liquidity_hit:
            return "liquidity_only"
        return "normal"

    @staticmethod
    def _structural_regime_level(row) -> str:
        underwater = _optional_float(row.get("benchmark_underwater_from_peak"))
        return_20d = _optional_float(row.get("benchmark_return_20d"))
        if underwater is None:
            return "bull"
        if underwater >= SAFETY_STRUCTURAL_BEAR_UNDERWATER or (return_20d is not None and return_20d <= -0.10):
            return "bear"
        if underwater >= SAFETY_STRUCTURAL_WEAK_UNDERWATER or (return_20d is not None and return_20d <= -0.05):
            return "weak"
        if underwater >= SAFETY_STRUCTURAL_NEUTRAL_UNDERWATER or (return_20d is not None and return_20d < 0.0):
            return "neutral"
        return "bull"

    @staticmethod
    def _hard_freeze_active(row) -> bool:
        drawdown_5d = _optional_float(row.get("benchmark_drawdown_5d"))
        return_5d = _optional_float(row.get("benchmark_return_5d"))
        stress = float(row.get("market_liquidity_stress_ratio", 0.0) or 0.0)
        benchmark_shock = _benchmark_shock_score(drawdown_5d, return_5d)
        return (
            benchmark_shock >= SAFETY_CRISIS_DRAWDOWN
            and stress >= SAFETY_CRISIS_LIQUIDITY_STRESS
        )

    @staticmethod
    def _final_exposure_cap(row) -> float:
        if bool(row.get("hard_freeze_active", False)):
            return float(SAFETY_HARD_FREEZE_EXPOSURE_CAP)
        safety_cap = float(row.get("safety_exposure_cap", 1.0) or 1.0)
        regime_budget = float(row.get("regime_exposure_budget", 1.0) or 1.0)
        return max(min(safety_cap, regime_budget), 0.0)


def _benchmark_shock_score(drawdown_5d: float | None, return_5d: float | None) -> float:
    scores = []
    if drawdown_5d is not None:
        scores.append(max(float(drawdown_5d), 0.0))
    if return_5d is not None:
        scores.append(max(-float(return_5d), 0.0))
    return max(scores) if scores else 0.0


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
    enter_confirms = {
        1: int(SAFETY_WARNING_CONFIRM_DAYS),
        2: int(SAFETY_HIGH_CONFIRM_DAYS),
        3: int(SAFETY_CRISIS_CONFIRM_DAYS),
    }
    exit_confirms = {
        1: int(SAFETY_WARNING_EXIT_DAYS),
        2: int(SAFETY_HIGH_EXIT_DAYS),
        3: int(SAFETY_CRISIS_EXIT_DAYS),
    }

    confirmed = []
    streaks = []
    consecutive = {1: 0, 2: 0, 3: 0}
    exit_streaks = {1: 0, 2: 0, 3: 0}
    state = 0

    for raw_level in raw_levels.fillna("normal").astype(str):
        score = order.get(raw_level, 0)
        for threshold in (1, 2, 3):
            consecutive[threshold] = consecutive[threshold] + 1 if score >= threshold else 0

        # Escalation always has priority when higher-severity conditions persist.
        for threshold in (3, 2, 1):
            if threshold > state and consecutive[threshold] >= enter_confirms[threshold]:
                state = threshold
                break

        for threshold in (1, 2, 3):
            if threshold <= score:
                exit_streaks[threshold] = 0
            else:
                exit_streaks[threshold] += 1

        if state > 0 and exit_streaks[state] >= exit_confirms[state]:
            if state == 3:
                state = 2 if score >= 2 else 1 if score >= 1 else 0
            elif state == 2:
                state = 1 if score >= 1 else 0
            else:
                state = 0

        confirmed.append(reverse[state])
        streaks.append(consecutive[state] if state > 0 else 0)

    return pd.Series(confirmed, index=raw_levels.index), pd.Series(streaks, index=raw_levels.index, dtype=int)
