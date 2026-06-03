"""Shadow portfolio contract for isolated model attribution."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from functions.decision_council.accounting import calculate_five_day_reward


@dataclass(frozen=True)
class ShadowPortfolioConfig:
    top_n: int = 20
    minimum_holding_days: int = 5
    daily_turnover_budget: float = 0.20


class ShadowPortfolioLedger:
    """Store model-isolated NAV observations using the shared reward contract."""

    def __init__(self, model_name: str, config: ShadowPortfolioConfig | None = None):
        self.model_name = str(model_name)
        self.config = config or ShadowPortfolioConfig()
        self.rows = []

    def append(self, *, date, nominal_nav: float, liquidatable_nav: float, executed_turnover: float):
        self.rows.append(
            {
                "model_name": self.model_name,
                "date": pd.Timestamp(date),
                "nominal_nav": float(nominal_nav),
                "liquidatable_nav": float(liquidatable_nav),
                "executed_turnover": float(executed_turnover),
            }
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def mature_reward(self, horizon_days: int = 5) -> dict:
        data = self.frame().sort_values("date")
        if len(data) < horizon_days + 1:
            raise ValueError("Shadow portfolio reward has not matured")
        window = data.iloc[-(horizon_days + 1):]
        reward = calculate_five_day_reward(
            window["liquidatable_nav"],
            executed_turnover_5d=float(window["executed_turnover"].iloc[1:].sum()),
        )
        return {"model_name": self.model_name, **reward}
