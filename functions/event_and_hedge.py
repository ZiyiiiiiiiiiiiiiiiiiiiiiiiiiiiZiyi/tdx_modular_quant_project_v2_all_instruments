"""Auditable event-driven and alpha-hedge helper contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


EVENT_SIGNAL_COLUMNS = [
    "date",
    "symbol",
    "event_type",
    "event_timestamp",
    "tradeable_timestamp",
    "signal_source_precision",
    "event_score",
    "source",
]


@dataclass(frozen=True)
class HedgeCost:
    borrow_cost_rate: float = 0.0
    futures_margin_rate: float = 0.0
    tracking_error_rate: float = 0.0
    slippage_rate: float = 0.0


class HedgeInstrumentProvider(ABC):
    @abstractmethod
    def get_hedge_cost(self, date) -> HedgeCost:
        """Return short/hedge costs for the requested date."""

    @abstractmethod
    def get_available_notional(self, date) -> float:
        """Return available hedge notional."""


class ResearchOnlyHedgeProvider(HedgeInstrumentProvider):
    """First-version alpha hedge provider: explicit research-only stub."""

    def get_hedge_cost(self, date) -> HedgeCost:
        return HedgeCost()

    def get_available_notional(self, date) -> float:
        return 0.0


def build_auditable_event_signals(
    *,
    corporate_actions: pd.DataFrame | None = None,
    index_constituents: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build event labels using only timestamped auditable sources."""
    frames = []
    if corporate_actions is not None and not corporate_actions.empty:
        actions = corporate_actions.copy()
        if "action_date" in actions.columns:
            actions["event_timestamp"] = pd.to_datetime(actions["action_date"], errors="coerce")
        else:
            actions["event_timestamp"] = pd.NaT
        actions["tradeable_timestamp"] = actions["event_timestamp"] + pd.offsets.BDay(1)
        actions["signal_source_precision"] = "unknown"
        actions["event_type"] = actions.get("action_type", "corporate_action")
        actions["event_score"] = 0.0
        actions["source"] = actions.get("source", "corporate_actions")
        frames.append(actions.rename(columns={"action_date": "date"})[EVENT_SIGNAL_COLUMNS])

    if index_constituents is not None and not index_constituents.empty:
        members = index_constituents.copy()
        members["event_timestamp"] = pd.to_datetime(
            members.get("announcement_date", members.get("effective_after_close_date")),
            errors="coerce",
        )
        members["date"] = pd.to_datetime(members.get("first_trade_date"), errors="coerce")
        members["tradeable_timestamp"] = members["date"] + pd.Timedelta(hours=9, minutes=30)
        members["signal_source_precision"] = "post_market"
        members["event_type"] = "index_inclusion"
        members["event_score"] = 0.0
        members["source"] = members.get("source", "index_constituents")
        frames.append(members[EVENT_SIGNAL_COLUMNS])

    if not frames:
        return pd.DataFrame(columns=EVENT_SIGNAL_COLUMNS)
    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["event_timestamp"] = pd.to_datetime(result["event_timestamp"], errors="coerce")
    result["tradeable_timestamp"] = pd.to_datetime(result["tradeable_timestamp"], errors="coerce")
    return result.dropna(subset=["symbol", "tradeable_timestamp"]).sort_values(["tradeable_timestamp", "symbol"])


def estimate_static_alpha_beta(daily_result: pd.DataFrame, benchmark_daily_return: pd.Series | pd.DataFrame) -> dict:
    """Estimate simple alpha/beta against a benchmark return series."""
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if isinstance(benchmark_daily_return, pd.DataFrame):
        bench = benchmark_daily_return.copy()
        bench["date"] = pd.to_datetime(bench["date"], errors="coerce")
        bench_col = "benchmark_return" if "benchmark_return" in bench.columns else "daily_return"
        merged = data.merge(bench[["date", bench_col]].rename(columns={bench_col: "benchmark_return"}), on="date", how="inner")
    else:
        bench = pd.Series(benchmark_daily_return).rename("benchmark_return")
        merged = data.join(bench, how="inner")
    if merged.empty:
        return {"alpha_daily": float("nan"), "beta": float("nan"), "excess_return": float("nan")}
    y = pd.to_numeric(merged["daily_return"], errors="coerce")
    x = pd.to_numeric(merged["benchmark_return"], errors="coerce")
    valid = y.notna() & x.notna()
    if valid.sum() < 2 or float(x[valid].var()) == 0.0:
        beta = float("nan")
        alpha = float("nan")
    else:
        beta = float(y[valid].cov(x[valid]) / x[valid].var())
        alpha = float(y[valid].mean() - beta * x[valid].mean())
    return {
        "alpha_daily": alpha,
        "beta": beta,
        "excess_return": float((y[valid] - x[valid]).sum()) if valid.any() else float("nan"),
    }
