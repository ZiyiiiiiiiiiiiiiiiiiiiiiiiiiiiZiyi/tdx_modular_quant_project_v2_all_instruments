# -*- coding: utf-8 -*-
"""
Market Regime Policy: Bull/Bear differentiated strategy management.

This module provides dynamic parameter adjustment based on market regime detection.
All strategy parameters (safety thresholds, Kelly sizing, signal filtering, etc.)
are differentiated between bull and bear markets.

Key Design Principles:
1. Conservative default: When regime is uncertain, default to bear market parameters
2. Smooth transitions: Use EMA smoothing to avoid whipsawing between regimes
3. Multiple confirmation: Require multiple signals to confirm regime change
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegimeParams:
    """Strategy parameters differentiated by market regime."""
    
    # Safety proxy thresholds
    safety_warning_drawdown: float
    safety_high_drawdown: float
    safety_crisis_drawdown: float
    safety_warning_confirm_days: int
    safety_high_confirm_days: int
    safety_crisis_confirm_days: int
    
    # Signal quality thresholds
    min_score_percentile: float
    
    # Kelly position sizing
    kelly_scale: float
    min_p_win: float
    severe_exit_kelly_score: float
    
    # Turnover control
    default_turnover_budget: float
    
    # Position limits
    max_positions: int
    max_position_weight: float
    max_sector_weight: float
    
    # Rebalancing
    rebalance_interval_days: int
    regime_name: str = "unknown"


# Bull market parameters: More aggressive, faster trading
BULL_PARAMS = RegimeParams(
    # Safety: More tolerant of drawdowns in bull markets
    safety_warning_drawdown=0.025,
    safety_high_drawdown=0.045,
    safety_crisis_drawdown=0.07,
    safety_warning_confirm_days=3,
    safety_high_confirm_days=3,
    safety_crisis_confirm_days=3,
    
    # Signal: Standard quality threshold
    min_score_percentile=0.75,
    
    # Kelly: Moderate aggression
    kelly_scale=0.45,
    min_p_win=0.50,
    severe_exit_kelly_score=0.02,
    
    # Turnover: Moderate turnover allowed
    default_turnover_budget=0.04,
    
    # Positions: More diversified
    max_positions=25,
    max_position_weight=0.08,
    max_sector_weight=0.30,
    
    # Rebalancing: Weekly
    rebalance_interval_days=5,
    regime_name="bull",
)

REBOUND_PARAMS = RegimeParams(
    safety_warning_drawdown=0.020,
    safety_high_drawdown=0.040,
    safety_crisis_drawdown=0.065,
    safety_warning_confirm_days=3,
    safety_high_confirm_days=3,
    safety_crisis_confirm_days=3,
    min_score_percentile=0.76,
    kelly_scale=0.42,
    min_p_win=0.51,
    severe_exit_kelly_score=0.018,
    default_turnover_budget=0.055,
    max_positions=25,
    max_position_weight=0.08,
    max_sector_weight=0.30,
    rebalance_interval_days=5,
    regime_name="rebound",
)

NEUTRAL_PARAMS = RegimeParams(
    safety_warning_drawdown=0.020,
    safety_high_drawdown=0.038,
    safety_crisis_drawdown=0.060,
    safety_warning_confirm_days=2,
    safety_high_confirm_days=2,
    safety_crisis_confirm_days=2,
    min_score_percentile=0.80,
    kelly_scale=0.38,
    min_p_win=0.52,
    severe_exit_kelly_score=0.017,
    default_turnover_budget=0.035,
    max_positions=20,
    max_position_weight=0.09,
    max_sector_weight=0.28,
    rebalance_interval_days=5,
    regime_name="neutral",
)

WEAK_PARAMS = RegimeParams(
    safety_warning_drawdown=0.016,
    safety_high_drawdown=0.032,
    safety_crisis_drawdown=0.052,
    safety_warning_confirm_days=2,
    safety_high_confirm_days=2,
    safety_crisis_confirm_days=2,
    min_score_percentile=0.85,
    kelly_scale=0.34,
    min_p_win=0.54,
    severe_exit_kelly_score=0.016,
    default_turnover_budget=0.025,
    max_positions=16,
    max_position_weight=0.10,
    max_sector_weight=0.25,
    rebalance_interval_days=10,
    regime_name="weak",
)

# Bear market parameters: More conservative, slower trading
BEAR_PARAMS = RegimeParams(
    # Safety: More sensitive to drawdowns in bear markets
    safety_warning_drawdown=0.015,
    safety_high_drawdown=0.03,
    safety_crisis_drawdown=0.05,
    safety_warning_confirm_days=2,
    safety_high_confirm_days=2,
    safety_crisis_confirm_days=2,
    
    # Signal: Higher quality threshold (top 15% only)
    min_score_percentile=0.85,
    
    # Kelly: Conservative sizing
    kelly_scale=0.35,
    min_p_win=0.55,
    severe_exit_kelly_score=0.015,
    
    # Turnover: Lower turnover
    default_turnover_budget=0.02,
    
    # Positions: More concentrated
    max_positions=15,
    max_position_weight=0.10,
    max_sector_weight=0.25,
    
    # Rebalancing: Monthly
    rebalance_interval_days=21,
    regime_name="bear",
)

CRISIS_PARAMS = RegimeParams(
    safety_warning_drawdown=0.012,
    safety_high_drawdown=0.025,
    safety_crisis_drawdown=0.045,
    safety_warning_confirm_days=1,
    safety_high_confirm_days=1,
    safety_crisis_confirm_days=1,
    min_score_percentile=0.90,
    kelly_scale=0.20,
    min_p_win=0.58,
    severe_exit_kelly_score=0.010,
    default_turnover_budget=0.010,
    max_positions=8,
    max_position_weight=0.08,
    max_sector_weight=0.20,
    rebalance_interval_days=21,
    regime_name="crisis",
)


class MarketRegimeDetector:
    """
    Detect market regime using multiple indicators.
    
    Uses sh510300 (CSI 300 ETF) as the primary benchmark.
    
    Detection uses benchmark trend, drawdown, volatility, and universe breadth.
    """
    
    def __init__(
        self,
        ma_period: int = 20,
        ma_slope_lookback: int = 5,
        volatility_threshold: float = 0.025,
        min_history_days: int = 30,
    ):
        self.ma_period = ma_period
        self.ma_slope_lookback = ma_slope_lookback
        self.volatility_threshold = volatility_threshold
        self.min_history_days = min_history_days
        self._regime_cache: dict[str, str] = {}
        self._precomputed_history: dict[str, pd.Series] = {}
        self._precomputed_diagnostics: dict[str, pd.DataFrame] = {}

    def detect(
        self,
        features_df: pd.DataFrame,
        date: pd.Timestamp,
        benchmark_symbol: str = "sh510300",
    ) -> str:
        """
        Detect market regime for a given date.
        
        Parameters
        ----------
        features_df : pd.DataFrame
            Feature dataframe with columns: date, symbol, close, close_nominal
        date : pd.Timestamp
            Date to detect regime for
        benchmark_symbol : str
            Symbol to use as market benchmark (default: sh510300)
        
        Returns
        -------
        str : "bull" or "bear"
        """
        cache_key = f"{benchmark_symbol}_{date.strftime('%Y%m%d')}"
        if cache_key in self._regime_cache:
            return self._regime_cache[cache_key]

        prepared = self._precomputed_history.get(str(benchmark_symbol))
        if prepared is not None and not prepared.empty:
            key = pd.Timestamp(date).normalize()
            regime = prepared.get(key)
            if isinstance(regime, str) and regime:
                self._regime_cache[cache_key] = regime
                return regime
        
        regime = self._detect_internal(features_df, date, benchmark_symbol)
        self._regime_cache[cache_key] = regime
        return regime

    def diagnostics(
        self,
        date: pd.Timestamp,
        benchmark_symbol: str = "sh510300",
    ) -> dict[str, Any]:
        """Return the as-of input contract used by :meth:`detect`.

        Missing benchmark observations or breadth are explicit.  They are not
        silently converted into a neutral breadth score or an observed market
        state.
        """
        frame = self._precomputed_diagnostics.get(str(benchmark_symbol))
        default = {
            "regime_input_valid": False,
            "regime_input_status": "history_not_prepared",
            "regime_benchmark_symbol": str(benchmark_symbol),
            "regime_benchmark_role": "safety_control_proxy",
            "regime_benchmark_observed": False,
            "regime_benchmark_lag_days": pd.NA,
            "regime_breadth_score": pd.NA,
            "regime_breadth_coverage": 0.0,
            "regime_as_of_date": pd.Timestamp(date),
        }
        if frame is None or frame.empty:
            return default
        key = pd.Timestamp(date).normalize()
        if key not in frame.index:
            default["regime_input_status"] = "date_not_prepared"
            return default
        row = frame.loc[key]
        result = default.copy()
        result.update(row.to_dict())
        result["regime_as_of_date"] = key
        return result

    def prepare_history(
        self,
        features_df: pd.DataFrame,
        benchmark_symbol: str = "sh510300",
    ) -> pd.Series:
        """Precompute regime labels for the full benchmark history once."""
        benchmark_symbol = str(benchmark_symbol)
        if benchmark_symbol in self._precomputed_history:
            return self._precomputed_history[benchmark_symbol]

        dates = pd.DatetimeIndex(
            pd.to_datetime(features_df["date"], errors="coerce")
            .dropna()
            .drop_duplicates()
            .sort_values()
        ).normalize()
        close_columns = [
            column for column in ("close_nominal", "close")
            if column in features_df.columns
        ]
        if not close_columns:
            raise ValueError("market regime history requires close or close_nominal")
        benchmark = features_df.loc[
            features_df["symbol"].astype(str) == benchmark_symbol,
            ["date", *close_columns],
        ].copy()
        breadth = _breadth_history(features_df)
        if benchmark.empty:
            series = pd.Series("unknown", index=dates, dtype="object")
            diagnostics = pd.DataFrame(index=dates)
            diagnostics["regime_input_valid"] = False
            diagnostics["regime_input_status"] = "benchmark_missing"
            diagnostics["regime_benchmark_symbol"] = benchmark_symbol
            diagnostics["regime_benchmark_role"] = "safety_control_proxy"
            diagnostics["regime_benchmark_observed"] = False
            diagnostics["regime_benchmark_lag_days"] = pd.NA
            diagnostics["regime_breadth_score"] = breadth.reindex(dates).get(
                "breadth_score", pd.Series(index=dates, dtype=float)
            )
            diagnostics["regime_breadth_coverage"] = breadth.reindex(dates).get(
                "breadth_coverage", pd.Series(0.0, index=dates)
            ).fillna(0.0)
            self._precomputed_history[benchmark_symbol] = series
            self._precomputed_diagnostics[benchmark_symbol] = diagnostics
            return series

        benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
        benchmark.sort_values("date", inplace=True)
        if "close_nominal" in benchmark.columns:
            close = pd.to_numeric(benchmark["close_nominal"], errors="coerce")
        else:
            close = pd.to_numeric(benchmark["close"], errors="coerce")
        prepared = pd.DataFrame(
            {
                "date": benchmark["date"].to_numpy(),
                "close": close.to_numpy(),
            }
        ).dropna(subset=["date"]).drop_duplicates("date", keep="last")
        if prepared.empty:
            series = pd.Series("unknown", index=dates, dtype="object")
            self._precomputed_history[benchmark_symbol] = series
            diagnostics = pd.DataFrame(index=dates)
            diagnostics["regime_input_valid"] = False
            diagnostics["regime_input_status"] = "benchmark_price_missing"
            diagnostics["regime_benchmark_symbol"] = benchmark_symbol
            diagnostics["regime_benchmark_role"] = "safety_control_proxy"
            diagnostics["regime_benchmark_observed"] = False
            diagnostics["regime_benchmark_lag_days"] = pd.NA
            diagnostics["regime_breadth_score"] = pd.NA
            diagnostics["regime_breadth_coverage"] = 0.0
            self._precomputed_diagnostics[benchmark_symbol] = diagnostics
            return series

        prepared["date"] = pd.to_datetime(prepared["date"]).dt.normalize()
        prepared = prepared.set_index("date").reindex(dates)
        prepared.index.name = "date"
        prepared["benchmark_observed"] = prepared["close"].notna()
        # Metrics use only observations available by the current date.  A
        # missing same-day proxy is not silently treated as a valid state.
        observed_close = prepared["close"].dropna()
        metric = pd.DataFrame(index=observed_close.index)
        metric["close"] = observed_close
        metric["ma20"] = observed_close.rolling(window=20, min_periods=20).mean()
        metric["ma60"] = observed_close.rolling(window=60, min_periods=40).mean()
        metric["ma120"] = observed_close.rolling(window=120, min_periods=80).mean()
        metric["ret_20d"] = observed_close / observed_close.shift(self.ma_period - 1) - 1.0
        metric["ret_60d"] = observed_close / observed_close.shift(60) - 1.0
        metric["ret_5d"] = observed_close / observed_close.shift(5) - 1.0
        metric["ma_prev"] = metric["ma20"].shift(self.ma_slope_lookback - 1)
        metric["recent_volatility"] = observed_close.pct_change().rolling(window=20, min_periods=1).std()
        metric["underwater"] = observed_close / observed_close.cummax() - 1.0
        metric["history_count"] = np.arange(1, len(metric) + 1, dtype=float)
        prepared = prepared.drop(columns=["close"]).join(metric, how="left")
        prepared = prepared.join(breadth, how="left")
        prepared["breadth_coverage"] = pd.to_numeric(
            prepared.get("breadth_coverage"), errors="coerce"
        ).fillna(0.0)
        prepared["input_valid"] = (
            prepared["benchmark_observed"]
            & prepared["history_count"].ge(float(self.min_history_days))
            & pd.to_numeric(prepared.get("breadth_score"), errors="coerce").notna()
            & prepared["breadth_coverage"].gt(0.0)
        )
        raw_regimes = []
        for _, row in prepared.iterrows():
            if not bool(row.get("input_valid", False)):
                raw_regimes.append("unknown")
            else:
                raw_regimes.append(
                    self._classify_market_row(
                        row,
                        breadth_score=float(row["breadth_score"]),
                    )
                )
        prepared["regime"] = _apply_hysteresis_preserving_unknown(
            raw_regimes,
            confirm_days=3,
        )
        series = pd.Series(prepared["regime"].to_numpy(), index=dates, dtype="object")
        diagnostics = pd.DataFrame(index=dates)
        diagnostics["regime_input_valid"] = prepared["input_valid"].astype(bool)
        diagnostics["regime_input_status"] = np.select(
            [
                ~prepared["benchmark_observed"],
                prepared["history_count"].fillna(0.0).lt(float(self.min_history_days)),
                pd.to_numeric(prepared.get("breadth_score"), errors="coerce").isna(),
                prepared["breadth_coverage"].le(0.0),
            ],
            [
                "benchmark_missing_for_date",
                "insufficient_benchmark_history",
                "breadth_missing_for_date",
                "breadth_zero_coverage",
            ],
            default="valid",
        )
        diagnostics["regime_benchmark_symbol"] = benchmark_symbol
        diagnostics["regime_benchmark_role"] = "safety_control_proxy"
        diagnostics["regime_benchmark_observed"] = prepared["benchmark_observed"].astype(bool)
        diagnostics["regime_benchmark_lag_days"] = np.where(
            prepared["benchmark_observed"], 0, np.nan
        )
        diagnostics["regime_breadth_score"] = pd.to_numeric(
            prepared.get("breadth_score"), errors="coerce"
        )
        diagnostics["regime_breadth_coverage"] = prepared["breadth_coverage"]
        diagnostics["regime_raw_label"] = raw_regimes
        diagnostics["regime_confirmed_label"] = series
        self._precomputed_history[benchmark_symbol] = series
        self._precomputed_diagnostics[benchmark_symbol] = diagnostics
        return series
    
    def _detect_internal(
        self,
        features_df: pd.DataFrame,
        date: pd.Timestamp,
        benchmark_symbol: str,
    ) -> str:
        """Internal detection logic."""
        # Filter benchmark data up to current date
        mask = (
            (features_df["symbol"].astype(str) == benchmark_symbol)
            & (features_df["date"] <= pd.Timestamp(date))
        )
        benchmark = features_df.loc[mask].copy()
        
        if benchmark.empty:
            return "bear"  # Default to bear if no data
        
        benchmark = benchmark.sort_values("date")
        exact_date = pd.Timestamp(date).normalize()
        observed_dates = pd.to_datetime(benchmark["date"], errors="coerce").dt.normalize()
        if not observed_dates.eq(exact_date).any():
            return "unknown"
        
        # Get close prices
        if "close_nominal" in benchmark.columns:
            close = pd.to_numeric(benchmark["close_nominal"], errors="coerce")
        else:
            close = pd.to_numeric(benchmark["close"], errors="coerce")
        
        close = close.dropna()
        
        if len(close) < self.min_history_days:
            return "bear"  # Default to bear if insufficient history
        
        current_price = float(close.iloc[-1])
        ma20 = close.rolling(window=20, min_periods=20).mean()
        ma60 = close.rolling(window=60, min_periods=40).mean()
        ma120 = close.rolling(window=120, min_periods=80).mean()
        current_ma = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else current_price
        current_ma60 = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else current_price
        current_ma120 = float(ma120.iloc[-1]) if not pd.isna(ma120.iloc[-1]) else current_price
        ret_20d = current_price / float(close.iloc[-20]) - 1.0 if len(close) >= 20 and float(close.iloc[-20]) > 0 else 0.0
        ret_60d = current_price / float(close.iloc[-60]) - 1.0 if len(close) >= 60 and float(close.iloc[-60]) > 0 else 0.0
        ret_5d = current_price / float(close.iloc[-5]) - 1.0 if len(close) >= 5 and float(close.iloc[-5]) > 0 else 0.0
        if len(ma20) >= self.ma_slope_lookback:
            ma_5d_ago = float(ma20.iloc[-self.ma_slope_lookback])
        else:
            ma_5d_ago = current_ma
        recent_returns = close.pct_change().dropna().tail(20)
        recent_volatility = float(recent_returns.std()) if len(recent_returns) > 0 else 0.0
        underwater = current_price / float(close.cummax().iloc[-1]) - 1.0 if float(close.cummax().iloc[-1]) > 0 else 0.0
        daily = features_df.loc[features_df["date"].eq(pd.Timestamp(date))]
        breadth_score = _breadth_score(daily)
        if pd.isna(breadth_score):
            return "unknown"
        row = pd.Series(
            {
                "close": current_price,
                "ma20": current_ma,
                "ma60": current_ma60,
                "ma120": current_ma120,
                "ma_prev": ma_5d_ago,
                "ret_20d": ret_20d,
                "ret_60d": ret_60d,
                "ret_5d": ret_5d,
                "recent_volatility": recent_volatility,
                "underwater": underwater,
                "history_count": len(close),
            }
        )
        return self._classify_market_row(row, breadth_score=breadth_score)

    def _classify_market_row(self, row: pd.Series, *, breadth_score: float) -> str:
        if float(row.get("history_count", 0.0)) < float(self.min_history_days):
            return "bear"
        price = float(row.get("close", 0.0))
        ma20 = float(row.get("ma20", price))
        ma60 = float(row.get("ma60", price))
        ma120 = float(row.get("ma120", price))
        ret20 = float(row.get("ret_20d", 0.0) or 0.0)
        ret60 = float(row.get("ret_60d", 0.0) or 0.0)
        ret5 = float(row.get("ret_5d", 0.0) or 0.0)
        ma_rising = ma20 > float(row.get("ma_prev", ma20))
        vol = float(row.get("recent_volatility", 0.0) or 0.0)
        underwater = float(row.get("underwater", 0.0) or 0.0)
        if pd.isna(breadth_score):
            raise ValueError("market regime classification requires observed PIT breadth")
        breadth = float(breadth_score)
        if underwater <= -0.25 or vol >= self.volatility_threshold * 1.8:
            return "crisis"
        if price > ma20 > ma60 and ret20 > 0.02 and ret60 > 0.0 and ma_rising and breadth >= 0.55:
            return "bull"
        # Rebound needs short-term follow-through and healthier breadth. A loose
        # rebound label encouraged buys in failed bounces.
        if price > ma20 and ret20 > 0.03 and ret5 > -0.005 and ma_rising and underwater > -0.20 and breadth >= 0.52 and ret60 > -0.12:
            return "rebound"
        if price > ma20 and ret20 > 0.0 and breadth >= 0.45:
            return "neutral"
        if price > ma120 and ret20 > -0.03 and breadth >= 0.35:
            return "weak"
        return "bear"
    
    def clear_cache(self):
        """Clear the regime detection cache."""
        self._regime_cache.clear()
        self._precomputed_history.clear()
        self._precomputed_diagnostics.clear()


class MarketRegimePolicy:
    """
    Market regime-based policy manager.
    
    Provides differentiated strategy parameters based on detected market regime.
    Uses smoothing to avoid rapid parameter changes.
    """
    
    def __init__(
        self,
        bull_params: RegimeParams | None = None,
        bear_params: RegimeParams | None = None,
        detector: MarketRegimeDetector | None = None,
    ):
        self.bull_params = bull_params or BULL_PARAMS
        self.bear_params = bear_params or BEAR_PARAMS
        self.rebound_params = REBOUND_PARAMS
        self.neutral_params = NEUTRAL_PARAMS
        self.weak_params = WEAK_PARAMS
        self.crisis_params = CRISIS_PARAMS
        self.detector = detector or MarketRegimeDetector()
        self._regime_history: list[tuple[pd.Timestamp, str]] = []
    
    def get_params(
        self,
        features_df: pd.DataFrame,
        date: pd.Timestamp,
        benchmark_symbol: str = "sh510300",
    ) -> RegimeParams:
        """
        Get strategy parameters for the current date.
        
        Parameters
        ----------
        features_df : pd.DataFrame
            Feature dataframe
        date : pd.Timestamp
            Current date
        benchmark_symbol : str
            Benchmark symbol for regime detection
        
        Returns
        -------
        RegimeParams : Parameters for the detected regime
        """
        regime = self.detector.detect(features_df, date, benchmark_symbol)
        self._regime_history.append((pd.Timestamp(date), regime))
        
        if regime == "bull":
            return self.bull_params
        if regime == "rebound":
            return self.rebound_params
        if regime == "neutral":
            return self.neutral_params
        if regime == "weak":
            return self.weak_params
        if regime == "crisis":
            return self.crisis_params
        return self.bear_params
    
    def get_current_regime(self) -> str:
        """Get the most recently detected regime."""
        if not self._regime_history:
            return "bear"
        return self._regime_history[-1][1]
    
    def get_regime_history(self) -> list[tuple[pd.Timestamp, str]]:
        """Get the full regime detection history."""
        return self._regime_history.copy()
    
    def get_params_dict(
        self,
        features_df: pd.DataFrame,
        date: pd.Timestamp,
        benchmark_symbol: str = "sh510300",
    ) -> dict[str, Any]:
        """
        Get strategy parameters as a dictionary.
        
        Returns
        -------
        dict : All parameters with their values
        """
        params = self.get_params(features_df, date, benchmark_symbol)
        return {
            "regime": self.get_current_regime(),
            **self.detector.diagnostics(date, benchmark_symbol),
            "safety_warning_drawdown": params.safety_warning_drawdown,
            "safety_high_drawdown": params.safety_high_drawdown,
            "safety_crisis_drawdown": params.safety_crisis_drawdown,
            "safety_warning_confirm_days": params.safety_warning_confirm_days,
            "safety_high_confirm_days": params.safety_high_confirm_days,
            "safety_crisis_confirm_days": params.safety_crisis_confirm_days,
            "min_score_percentile": params.min_score_percentile,
            "kelly_scale": params.kelly_scale,
            "min_p_win": params.min_p_win,
            "severe_exit_kelly_score": params.severe_exit_kelly_score,
            "default_turnover_budget": params.default_turnover_budget,
            "max_positions": params.max_positions,
            "max_position_weight": params.max_position_weight,
            "max_sector_weight": params.max_sector_weight,
            "rebalance_interval_days": params.rebalance_interval_days,
        }


def _breadth_score(daily: pd.DataFrame) -> float:
    if daily is None or daily.empty:
        return float("nan")
    scores = []
    if "ret_20" in daily.columns:
        ret20 = pd.to_numeric(daily["ret_20"], errors="coerce").dropna()
        if not ret20.empty:
            scores.append(float((ret20 > 0.0).mean()))
    if "close_to_ma20" in daily.columns:
        close_to_ma20 = pd.to_numeric(daily["close_to_ma20"], errors="coerce").dropna()
        if not close_to_ma20.empty:
            scores.append(float((close_to_ma20 > 0.0).mean()))
    if not scores:
        return float("nan")
    return float(np.mean(scores))


def _breadth_history(features_df: pd.DataFrame) -> pd.DataFrame:
    """Build same-day PIT breadth and coverage without future filling."""
    columns = ["date"]
    for column in ("ret_20", "close_to_ma20", "instrument_type", "is_trading"):
        if column in features_df.columns:
            columns.append(column)
    data = features_df.loc[:, columns].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data = data.dropna(subset=["date"])
    if "instrument_type" in data.columns:
        data = data[data["instrument_type"].astype(str).eq("stock")]
    if "is_trading" in data.columns:
        data = data[data["is_trading"].fillna(False).astype(bool)]
    rows = []
    for date, group in data.groupby("date", sort=True):
        score = _breadth_score(group)
        available = pd.Series(False, index=group.index)
        for column in ("ret_20", "close_to_ma20"):
            if column in group.columns:
                available |= pd.to_numeric(group[column], errors="coerce").notna()
        rows.append(
            {
                "date": pd.Timestamp(date),
                "breadth_score": score,
                "breadth_coverage": float(available.mean()) if len(group) else 0.0,
                "breadth_member_count": int(available.sum()),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["breadth_score", "breadth_coverage", "breadth_member_count"],
            index=pd.DatetimeIndex([], name="date"),
        )
    return pd.DataFrame(rows).set_index("date")


def _apply_hysteresis_preserving_unknown(
    regimes: pd.Series | list[str],
    *,
    confirm_days: int = 3,
) -> list[str]:
    """Confirm valid labels while preserving invalid dates as ``unknown``."""
    confirmed = None
    streak_value = None
    streak = 0
    output = []
    for raw in list(regimes):
        value = str(raw or "unknown")
        if value == "unknown":
            output.append("unknown")
            streak_value = None
            streak = 0
            continue
        if value == streak_value:
            streak += 1
        else:
            streak_value = value
            streak = 1
        if confirmed is None or streak >= max(int(confirm_days), 1):
            confirmed = value
        output.append(str(confirmed or value))
    return output


def _apply_hysteresis(regimes: pd.Series | list[str], *, confirm_days: int = 3) -> list[str]:
    values = list(regimes)
    if not values:
        return []
    confirmed = values[0]
    streak_value = values[0]
    streak = 0
    output = []
    for value in values:
        if value == streak_value:
            streak += 1
        else:
            streak_value = value
            streak = 1
        if streak >= int(confirm_days):
            confirmed = streak_value
        output.append(confirmed)
    return output
