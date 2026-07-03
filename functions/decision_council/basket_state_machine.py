"""Basket-level state machine helpers for governance entries and replacement."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BasketStateConfig:
    min_basket_score: float = 0.10
    max_turnover_weight: float = 0.20
    replacement_score_gap: float = 0.05
    min_hold_days: int = 5
    max_single_loss: float = -0.06
    max_quality_decay: float = 0.20


def evaluate_basket_entry(basket: pd.DataFrame, *, config: BasketStateConfig | None = None) -> dict:
    config = config or BasketStateConfig()
    if basket is None or basket.empty:
        return {"basket_state": "blocked", "entry_allowed": False, "reason": "empty_basket"}
    score = float(pd.to_numeric(basket.get("basket_score"), errors="coerce").dropna().mean())
    module_count = int(pd.to_numeric(basket.get("basket_module_count"), errors="coerce").dropna().max() or 0)
    family_count = int(pd.to_numeric(basket.get("basket_family_count"), errors="coerce").dropna().max() or 0)
    if score < float(config.min_basket_score):
        return {"basket_state": "blocked", "entry_allowed": False, "reason": "basket_score_below_threshold"}
    if module_count < 3 or family_count < 3:
        return {"basket_state": "blocked", "entry_allowed": False, "reason": "insufficient_factor_diversity"}
    return {"basket_state": "building", "entry_allowed": True, "reason": "basket_entry_confirmed"}


def plan_basket_replacements(
    holdings: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    config: BasketStateConfig | None = None,
) -> pd.DataFrame:
    """Return replacement candidates while respecting hold time and turnover budget."""
    config = config or BasketStateConfig()
    if holdings is None or holdings.empty or candidates is None or candidates.empty:
        return pd.DataFrame(columns=["sell_symbol", "buy_symbol", "reason", "turnover_weight"])
    held = holdings.copy()
    cand = candidates.copy()
    held["holding_days"] = pd.to_numeric(held.get("holding_days"), errors="coerce").fillna(0).astype(int)
    held["unrealized_return"] = pd.to_numeric(held.get("unrealized_return"), errors="coerce").fillna(0.0)
    held["quality_decay"] = pd.to_numeric(held.get("quality_decay"), errors="coerce").fillna(0.0)
    cand["score"] = pd.to_numeric(cand.get("basket_score", cand.get("primary_score")), errors="coerce").fillna(0.0)
    rows = []
    spent = 0.0
    for _, bad in held.sort_values(["unrealized_return", "quality_decay"], ascending=[True, False]).iterrows():
        if int(bad["holding_days"]) < int(config.min_hold_days):
            continue
        bad_score = float(pd.to_numeric(bad.get("basket_score", bad.get("primary_score", 0.0)), errors="coerce") or 0.0)
        bad_weight = float(pd.to_numeric(bad.get("weight", 0.0), errors="coerce") or 0.0)
        if bad["unrealized_return"] > float(config.max_single_loss) and bad["quality_decay"] < float(config.max_quality_decay):
            continue
        better = cand[cand["score"] >= bad_score + float(config.replacement_score_gap)]
        if better.empty:
            continue
        if spent + bad_weight > float(config.max_turnover_weight):
            continue
        buy = better.sort_values(["score", "symbol"], ascending=[False, True]).iloc[0]
        rows.append(
            {
                "sell_symbol": str(bad.get("symbol")),
                "buy_symbol": str(buy.get("symbol")),
                "reason": "loss_or_quality_decay_replacement",
                "turnover_weight": bad_weight,
            }
        )
        spent += bad_weight
    return pd.DataFrame(rows)
