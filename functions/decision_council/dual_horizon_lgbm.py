"""Two-horizon LightGBM controller: short entry rank and medium hold value."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.monthly_lgbm_hybrid import OnlineMonthlyLGBMController


class DualHorizonMonthlyLGBMController:
    """Keeps entry and hold objectives separate while sharing the same PIT contract."""

    def __init__(
        self,
        *,
        maximum_ml_weight: float,
        benchmark_symbol: str,
        round_trip_cost_rate: float,
        short_horizon_days: int = 5,
        medium_horizon_days: int = 20,
        validation_date_count: int = 20,
        minimum_training_date_count: int = 45,
        allow_pit_restricted_features: bool = False,
        treatment_top_k: int = 5,
        model_params=None,
    ) -> None:
        shared = dict(
            maximum_ml_weight=maximum_ml_weight,
            benchmark_symbol=benchmark_symbol,
            validation_date_count=validation_date_count,
            minimum_training_date_count=max(minimum_training_date_count, validation_date_count + medium_horizon_days + 1),
            round_trip_cost_rate=round_trip_cost_rate,
            allow_pit_restricted_features=allow_pit_restricted_features,
            treatment_top_k=treatment_top_k,
            model_params=model_params,
        )
        self.short = OnlineMonthlyLGBMController(
            horizon_days=short_horizon_days, include_hold_support=False, **shared
        )
        self.medium = OnlineMonthlyLGBMController(
            horizon_days=medium_horizon_days, include_hold_support=True, **shared
        )

    def process_day(self, candidates: pd.DataFrame, *, as_of_date, price_history: pd.DataFrame):
        short_scored, short_audit = self.short.process_day(
            candidates, as_of_date=as_of_date, price_history=price_history
        )
        medium_scored, medium_audit = self.medium.process_day(
            candidates, as_of_date=as_of_date, price_history=price_history
        )
        horizon = self.medium.horizon_days
        columns = [
            column for column in medium_scored.columns
            if column.startswith(f"expected_edge_{horizon}d")
            or column.startswith(f"conservative_expected_edge_{horizon}d")
        ]
        for column in columns:
            short_scored[column] = medium_scored[column].reindex(short_scored.index)
        medium_authorized = float(pd.to_numeric(pd.Series([medium_audit.get("ml_weight", 0.0)]), errors="coerce").fillna(0.0).iloc[0]) > 0.0
        short_scored["ml_medium_value_authorized"] = bool(medium_authorized)
        short_scored["replacement_value_preferred_horizon_days"] = 20 if medium_authorized else pd.NA
        short_scored["replacement_value_authority"] = (
            "medium_ml_treatment_lcb_positive" if medium_authorized else "medium_ml_paper_only"
        )
        short_scored["hold_lgbm_rank_percentile"] = medium_scored.get(
            "monthly_lgbm_rank_percentile", pd.Series(float("nan"), index=medium_scored.index)
        ).reindex(short_scored.index)
        short_scored["hold_lgbm_model_month"] = medium_scored.get(
            "monthly_lgbm_model_month", pd.Series("", index=medium_scored.index)
        ).reindex(short_scored.index)
        audit = dict(short_audit)
        audit["dual_horizon_contract"] = "short_entry_rank_plus_medium_hold_value_v1"
        for key, value in medium_audit.items():
            if key != "date":
                audit[f"medium_{key}"] = value
        return short_scored, audit

    @staticmethod
    def _combine(short: pd.DataFrame, medium: pd.DataFrame) -> pd.DataFrame:
        frames = []
        for name, frame in (("short_entry", short), ("medium_hold", medium)):
            if frame is not None and not frame.empty:
                copy = frame.copy()
                copy["model_purpose"] = name
                frames.append(copy)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def training_attempt_frame(self):
        return self._combine(self.short.training_attempt_frame(), self.medium.training_attempt_frame())

    def feature_diagnostic_frame(self):
        return self._combine(self.short.feature_diagnostic_frame(), self.medium.feature_diagnostic_frame())

    def iteration_metric_frame(self):
        return self._combine(self.short.iteration_metric_frame(), self.medium.iteration_metric_frame())

    def nested_candidate_frame(self):
        return self._combine(self.short.nested_candidate_frame(), self.medium.nested_candidate_frame())

    def treatment_candidate_frame(self):
        return self.short.treatment_candidate_frame()

    def treatment_daily_frame(self):
        return self.short.treatment_daily_frame()

    def treatment_effect_frame(self, price_history):
        return self.short.treatment_effect_frame(price_history)
