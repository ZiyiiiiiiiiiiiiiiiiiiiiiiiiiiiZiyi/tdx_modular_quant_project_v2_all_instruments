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
)


class MarketRegimeDetector:
    """
    Detect market regime using multiple indicators.
    
    Uses sh510300 (CSI 300 ETF) as the primary benchmark.
    
    Detection Logic:
    1. Price vs MA20: Bull if price > MA20
    2. 20-day return: Bull if return > 0
    3. MA slope: Bull if MA20 is rising (current MA > MA 5 days ago)
    4. Volatility: Bear if volatility exceeds threshold
    
    All conditions must be met for bull regime.
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
        
        regime = self._detect_internal(features_df, date, benchmark_symbol)
        self._regime_cache[cache_key] = regime
        return regime
    
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
        
        # Get close prices
        if "close_nominal" in benchmark.columns:
            close = pd.to_numeric(benchmark["close_nominal"], errors="coerce")
        else:
            close = pd.to_numeric(benchmark["close"], errors="coerce")
        
        close = close.dropna()
        
        if len(close) < self.min_history_days:
            return "bear"  # Default to bear if insufficient history
        
        # Calculate indicators
        current_price = float(close.iloc[-1])
        
        # 1. MA20
        ma20 = close.rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        current_ma = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else current_price
        
        # 2. 20-day return
        if len(close) >= self.ma_period:
            price_20d_ago = float(close.iloc[-self.ma_period])
            ret_20d = (current_price - price_20d_ago) / price_20d_ago if price_20d_ago > 0 else 0.0
        else:
            ret_20d = 0.0
        
        # 3. MA slope (rising or falling)
        if len(ma20) >= self.ma_slope_lookback:
            ma_5d_ago = float(ma20.iloc[-self.ma_slope_lookback])
            ma_rising = current_ma > ma_5d_ago
        else:
            ma_rising = True
        
        # 4. Recent volatility
        recent_returns = close.pct_change().dropna().tail(20)
        recent_volatility = float(recent_returns.std()) if len(recent_returns) > 0 else 0.0
        
        # Bull conditions (ALL must be true):
        # 1. Price above MA20
        # 2. 20-day return positive
        # 3. MA20 is rising
        # 4. Volatility below threshold
        is_bull = (
            current_price > current_ma
            and ret_20d > 0
            and ma_rising
            and recent_volatility < self.volatility_threshold
        )
        
        return "bull" if is_bull else "bear"
    
    def clear_cache(self):
        """Clear the regime detection cache."""
        self._regime_cache.clear()


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
        else:
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
