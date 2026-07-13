"""Fast per-alpha shadow portfolios.

The main governance runner is intentionally rich and auditable, but using a
full runner for every alpha multiplies runtime by the number of factors. This
module keeps the necessary shadow function: standalone factor NAV, exposure,
activity, and five-day reward for reputation updates.
"""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_DEFAULT_TOP_N, GOVERNANCE_INITIAL_CASH
from functions.decision_council.accounting import calculate_five_day_reward
from functions.decision_council.proposals import build_daily_candidates


class FastShadowPortfolioRunner:
    def __init__(
        self,
        features: pd.DataFrame,
        *,
        model_name: str,
        safety_signals: pd.DataFrame,
        daily_feature_indices: dict,
        initial_cash: float = GOVERNANCE_INITIAL_CASH,
        target_index_codes: tuple[str, ...] = (),
        universe_mode: str = "index_pool_strict",
        require_constituents: bool = True,
        allow_fallback: bool = False,
        allowed_instrument_types: tuple[str, ...] = ("stock",),
        enable_quality_filters: bool = True,
        top_n: int = GOVERNANCE_DEFAULT_TOP_N,
        runtime_context=None,
    ):
        self.features = features
        self.model_name = str(model_name)
        self.safety_signals = safety_signals
        self.daily_feature_indices = daily_feature_indices
        self.cash = float(initial_cash)
        self.initial_cash = float(initial_cash)
        self.positions: dict[str, float] = {}
        self.exposure_rows: list[dict] = []
        self._turnover_rows: list[float] = []
        self._target_index_codes = tuple(target_index_codes)
        self._universe_mode = str(universe_mode)
        self._require_constituents = bool(require_constituents)
        self._allow_fallback = bool(allow_fallback)
        self._allowed_instrument_types = tuple(allowed_instrument_types)
        self._enable_quality_filters = bool(enable_quality_filters)
        self._top_n = int(top_n)
        self._runtime_context = runtime_context

    def step(self, date, day_index: int):
        date = pd.Timestamp(date)
        daily = self._daily_frame(date)
        if daily.empty:
            self._record(date, nominal_nav=self.cash, invested_value=0.0, turnover=0.0)
            return self._mature_reward()
        close = pd.to_numeric(daily.set_index("symbol")["close_nominal"], errors="coerce")
        nav_before = self.cash + sum(float(shares) * float(close.get(symbol, 0.0) or 0.0) for symbol, shares in self.positions.items())
        target_exposure = self._target_exposure(date)
        candidates, _ = build_daily_candidates(
            daily,
            reputation_weights={self.model_name: 1.0},
            holding_days={symbol: 1 for symbol in self.positions},
            candidate_limit=max(self._top_n, 20),
            model_names=(self.model_name,),
            allowed_instrument_types=self._allowed_instrument_types,
            target_index_codes=self._target_index_codes,
            universe_mode=self._universe_mode,
            require_constituents=self._require_constituents,
            allow_fallback=self._allow_fallback,
            enable_quality_filters=self._enable_quality_filters,
            runtime_context=self._runtime_context,
        )
        selected = candidates.head(self._top_n).copy()
        target_values = {}
        if not selected.empty and nav_before > 0 and target_exposure > 0:
            selected["volatility_20"] = pd.to_numeric(selected.get("volatility_20"), errors="coerce").fillna(0.02).clip(lower=0.005)
            inv_vol = 1.0 / selected["volatility_20"]
            weights = inv_vol / inv_vol.sum() * float(target_exposure)
            for symbol, weight in zip(selected["symbol"].astype(str), weights):
                price = float(close.get(symbol, 0.0) or 0.0)
                if price > 0:
                    target_values[symbol] = float(weight) * nav_before
        turnover = self._rebalance_to_values(target_values, close, nav_before)
        invested_value = sum(float(shares) * float(close.get(symbol, 0.0) or 0.0) for symbol, shares in self.positions.items())
        nominal_nav = self.cash + invested_value
        self._record(date, nominal_nav=nominal_nav, invested_value=invested_value, turnover=turnover)
        return self._mature_reward()

    def _daily_frame(self, date: pd.Timestamp) -> pd.DataFrame:
        indexer = self.daily_feature_indices.get(pd.Timestamp(date))
        if indexer is None:
            return self.features.iloc[0:0].copy()
        return self.features.iloc[indexer].copy()

    def _target_exposure(self, date: pd.Timestamp) -> float:
        if date not in self.safety_signals.index:
            return 0.50
        row = self.safety_signals.loc[date]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        safety_cap = _safe_float(row.get("exposure_cap", 1.0), 1.0)
        regime = str(row.get("structural_regime_level", "neutral")).lower()
        base = {
            "crisis": 0.20,
            "bear": 0.40,
            "weak": 0.50,
            "neutral": 0.75,
            "rebound": 0.90,
            "bull": 1.00,
        }.get(regime, 0.50)
        return float(min(safety_cap, base))

    def _rebalance_to_values(self, target_values: dict[str, float], close: pd.Series, nav: float) -> float:
        current_symbols = set(self.positions)
        target_symbols = set(target_values)
        turnover_notional = 0.0
        for symbol in sorted(current_symbols | target_symbols):
            price = float(close.get(symbol, 0.0) or 0.0)
            if price <= 0:
                continue
            current_value = float(self.positions.get(symbol, 0.0)) * price
            target_value = float(target_values.get(symbol, 0.0))
            delta_value = target_value - current_value
            if abs(delta_value) <= max(nav * 0.0005, 100.0):
                continue
            shares_delta = delta_value / price
            if shares_delta > 0:
                buy_value = min(delta_value, self.cash)
                if buy_value <= 0:
                    continue
                shares_delta = buy_value / price
                self.cash -= buy_value
                self.positions[symbol] = float(self.positions.get(symbol, 0.0)) + shares_delta
                turnover_notional += buy_value
            else:
                sell_shares = min(abs(shares_delta), float(self.positions.get(symbol, 0.0)))
                if sell_shares <= 0:
                    continue
                sell_value = sell_shares * price
                self.cash += sell_value
                remaining = float(self.positions.get(symbol, 0.0)) - sell_shares
                if remaining <= 1e-9:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = remaining
                turnover_notional += sell_value
        return float(turnover_notional / max(nav, 1e-12))

    def _record(self, date, *, nominal_nav: float, invested_value: float, turnover: float) -> None:
        self._turnover_rows.append(float(turnover))
        self.exposure_rows.append(
            {
                "date": pd.Timestamp(date),
                "nominal_nav": float(nominal_nav),
                "liquidatable_nav": float(nominal_nav),
                "actual_exposure": float(invested_value) / max(float(nominal_nav), 1e-12),
                "holding_count": int(len(self.positions)),
                "executed_turnover": float(turnover),
            }
        )

    def _mature_reward(self, horizon_days: int = 5):
        if len(self.exposure_rows) < int(horizon_days) + 1:
            return None
        window = pd.DataFrame(self.exposure_rows[-(int(horizon_days) + 1):])
        reward = calculate_five_day_reward(
            window["liquidatable_nav"],
            executed_turnover_5d=float(window["executed_turnover"].iloc[1:].sum()),
        )
        return {"model_name": self.model_name, **reward}


def _safe_float(value, default: float) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])
