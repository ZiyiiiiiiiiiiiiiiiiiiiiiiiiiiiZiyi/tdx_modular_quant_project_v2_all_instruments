"""Exploratory governance account helpers with explicit audit boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import (
    CORPORATE_ACTIONS_PARQUET,
    GOVERNANCE_STALE_PRICE_HAIRCUT_DAYS,
    GOVERNANCE_STALE_PRICE_HAIRCUT_RATIO,
)
from functions.execution.corporate_action_ledger import build_corporate_action_ledger


@dataclass(frozen=True)
class PriceMark:
    symbol: str
    price: float
    price_date: pd.Timestamp
    stale_days: int
    valuation_source: str
    stale_haircut_ratio: float


class LastKnownPriceLedger:
    """Carry forward the last observable nominal close instead of inventing zero prices."""

    def __init__(
        self,
        *,
        stale_haircut_days: int = GOVERNANCE_STALE_PRICE_HAIRCUT_DAYS,
        stale_haircut_ratio: float = GOVERNANCE_STALE_PRICE_HAIRCUT_RATIO,
    ):
        self.stale_haircut_days = int(stale_haircut_days)
        self.stale_haircut_ratio = float(stale_haircut_ratio)
        self._marks: dict[str, tuple[float, pd.Timestamp]] = {}

    def update(self, daily_quotes: pd.DataFrame, *, as_of) -> None:
        if daily_quotes.empty:
            return
        quote_date = pd.Timestamp(as_of)
        for row in daily_quotes[["symbol", "close_nominal"]].itertuples(index=False):
            price = pd.to_numeric(pd.Series([row.close_nominal]), errors="coerce").iloc[0]
            if pd.notna(price) and float(price) > 0:
                self._marks[str(row.symbol)] = (float(price), quote_date)

    def mark(self, symbol: str, *, as_of) -> PriceMark | None:
        stored = self._marks.get(str(symbol))
        if stored is None:
            return None
        price, price_date = stored
        stale_days = max(len(pd.bdate_range(price_date, pd.Timestamp(as_of))) - 1, 0)
        haircut = self.stale_haircut_ratio if stale_days > self.stale_haircut_days else 0.0
        return PriceMark(
            symbol=str(symbol),
            price=float(price),
            price_date=price_date,
            stale_days=int(stale_days),
            valuation_source="observed_close" if stale_days == 0 else "last_known_close",
            stale_haircut_ratio=float(haircut),
        )


class ExploratoryCorporateActionProcessor:
    """Apply available action-date events while disclosing incomplete PIT timestamps."""

    def __init__(self, actions: pd.DataFrame | None = None):
        self.ledger = build_corporate_action_ledger(actions if actions is not None else pd.DataFrame())
        self.applied_keys: set[tuple] = set()
        self.audit_rows: list[dict] = []

    @classmethod
    def from_default_artifact(cls):
        path = Path(CORPORATE_ACTIONS_PARQUET)
        actions = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        return cls(actions)

    def apply(self, *, as_of, positions: dict, cash: float) -> tuple[float, dict]:
        action_date = pd.Timestamp(as_of)
        if self.ledger.empty:
            return float(cash), {"cash_delta": 0.0, "stock_dividend_shares": 0.0, "events": 0}
        events = self.ledger[self.ledger["ex_date"] == action_date]
        cash_delta = 0.0
        stock_shares = 0.0
        applied = 0
        for index, event in events.iterrows():
            symbol = str(event["symbol"])
            position = positions.get(symbol)
            if position is None or float(position.shares) <= 0:
                continue
            key = (int(index), symbol, action_date)
            if key in self.applied_keys:
                continue
            shares_before = float(position.shares)
            dividend = float(event["cash_dividend"]) if pd.notna(event["cash_dividend"]) else 0.0
            stock_ratio = float(event["stock_dividend_ratio"]) if pd.notna(event["stock_dividend_ratio"]) else 0.0
            event_cash = shares_before * dividend
            added_shares = float(int(shares_before * stock_ratio))
            if added_shares > 0:
                position.shares += added_shares
            cash_delta += event_cash
            stock_shares += added_shares
            applied += 1
            self.applied_keys.add(key)
            self.audit_rows.append(
                {
                    "date": action_date,
                    "symbol": symbol,
                    "action_type": event["action_type"],
                    "cash_dividend_per_share": dividend,
                    "cash_delta": event_cash,
                    "stock_dividend_ratio": stock_ratio,
                    "stock_dividend_shares": added_shares,
                    "pit_complete": bool(event["pit_complete"]),
                    "accounting_mode": "exploratory_action_date_fallback",
                }
            )
        return float(cash) + cash_delta, {
            "cash_delta": cash_delta,
            "stock_dividend_shares": stock_shares,
            "events": applied,
        }

    def audit_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.audit_rows)
