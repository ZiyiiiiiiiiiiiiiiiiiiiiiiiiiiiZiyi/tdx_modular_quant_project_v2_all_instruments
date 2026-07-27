"""PIT-safe rolling continuous role reliability for experimental v3.1."""
from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd


MAINLINE_V31_RELIABILITY = "mainline_v3_reliability_weighted"
V31_RELIABILITY_CONTRACT = "v31_rolling_matured_role_reliability_v2"

ROLE_COLUMNS = (
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_risk_safety_score",
    "cabinet_liquidity_health_score",
    "cabinet_hold_support_score",
)
# Compatibility export: these are semantic priors, not frozen learned authority.
ROLE_AUTHORITY = {column: 1.0 / len(ROLE_COLUMNS) for column in ROLE_COLUMNS}


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(float(value) / sqrt(2.0)))


def attach_reliability_weighted_score(
    candidates: pd.DataFrame,
    *,
    as_of_date=None,
    role_weights: dict[str, float] | None = None,
    reliability_blend: float = 0.0,
    reliability_status: str = "fallback_insufficient_matured_history",
    calibration_window: str = "none",
) -> pd.DataFrame:
    """Blend Cabinet Native with a coverage-aware role score; never creates a veto."""
    if candidates is None or candidates.empty:
        return candidates
    missing = sorted(set(ROLE_COLUMNS) - set(candidates.columns))
    if missing:
        raise ValueError(f"v3.1 reliability scoring is missing role columns: {missing}")
    data = candidates.copy()
    native = pd.to_numeric(data["cabinet_native_final_score"], errors="coerce")
    weights = dict(role_weights or ROLE_AUTHORITY)
    weights = {column: max(float(weights.get(column, 0.0)), 0.0) for column in ROLE_COLUMNS}
    total_weight = sum(weights.values())
    if total_weight <= 0.0:
        weights = dict(ROLE_AUTHORITY)
        total_weight = 1.0
    weights = {column: value / total_weight for column, value in weights.items()}
    numerator = pd.Series(0.0, index=data.index)
    denominator = pd.Series(0.0, index=data.index)
    active_count = pd.Series(0, index=data.index, dtype=int)
    for column, authority in weights.items():
        values = pd.to_numeric(data[column], errors="coerce")
        coverage = pd.to_numeric(
            data.get(f"{column}_coverage", pd.Series(0.0, index=data.index)), errors="coerce"
        ).fillna(0.0).clip(0.0, 1.0)
        effective = authority * coverage
        numerator += values.fillna(0.5) * effective
        denominator += effective
        active_count += effective.gt(0.0).astype(int)
        name = column.removeprefix("cabinet_").removesuffix("_score")
        data[f"v31_authority__{name}"] = authority
    role_score = numerator / denominator.replace(0.0, np.nan)
    blend = float(np.clip(reliability_blend, 0.0, 1.0))
    data["v31_role_reliability_score"] = role_score
    data["v31_reliability_score"] = ((1.0 - blend) * native + blend * role_score).clip(0.0, 1.0)
    native_coverage = pd.to_numeric(
        data.get("cabinet_entry_score_coverage", data.get("cabinet_strict_entry_score_coverage", 0.0)),
        errors="coerce",
    ).fillna(0.0).clip(0.0, 1.0)
    data["v31_reliability_score_coverage"] = ((1.0 - blend) * native_coverage + blend * denominator).clip(0.0, 1.0)
    data["v31_active_role_count"] = active_count
    data["v31_reliability_blend"] = blend
    data["v31_strict_entry_paper_only"] = False
    data["v31_reliability_contract"] = V31_RELIABILITY_CONTRACT
    data["v31_calibration_window"] = calibration_window
    data["v31_score_formula"] = "(1-blend)*cabinet_native + blend*coverage_weighted_role_score"
    data["v31_score_authority"] = "all_roles_continuous_non_veto"
    data["v31_temporal_status"] = reliability_status
    return data


class RollingRoleReliabilityController:
    """Expanding/rolling monthly estimator using only labels matured by decision time."""

    def __init__(
        self,
        *,
        benchmark_symbol: str,
        horizon_days: int = 10,
        minimum_dates: int = 60,
        rolling_dates: int = 252,
        round_trip_cost_rate: float = 0.0,
    ) -> None:
        self.benchmark_symbol = str(benchmark_symbol)
        self.horizon_days = max(int(horizon_days), 1)
        self.minimum_dates = max(int(minimum_dates), self.horizon_days + 5)
        self.rolling_dates = max(int(rolling_dates), self.minimum_dates)
        self.round_trip_cost_rate = max(float(round_trip_cost_rate), 0.0)
        self.history_frames: list[pd.DataFrame] = []
        self.role_weights = dict(ROLE_AUTHORITY)
        self.reliability_blend = 0.0
        self.status = "fallback_insufficient_matured_history"
        self.calibration_window = "none"
        self.last_update_month = ""
        self.audit_rows: list[dict] = []
        self._last_observed_date: pd.Timestamp | None = None

    def score_only(self, candidates: pd.DataFrame, *, as_of_date) -> pd.DataFrame:
        return attach_reliability_weighted_score(
            candidates, as_of_date=as_of_date, role_weights=self.role_weights,
            reliability_blend=self.reliability_blend, reliability_status=self.status,
            calibration_window=self.calibration_window,
        )

    def process_day(self, candidates: pd.DataFrame, *, as_of_date, price_history: pd.DataFrame) -> pd.DataFrame:
        as_of = pd.Timestamp(as_of_date).normalize()
        month = as_of.strftime("%Y-%m")
        if month != self.last_update_month:
            self._update(as_of, price_history)
            self.last_update_month = month
        scored = self.score_only(candidates, as_of_date=as_of)
        self._observe(candidates, as_of)
        return scored

    def _observe(self, candidates: pd.DataFrame, as_of: pd.Timestamp) -> None:
        if candidates is None or candidates.empty or self._last_observed_date == as_of:
            return
        columns = [column for column in ("symbol", "cabinet_native_final_score", *ROLE_COLUMNS) if column in candidates]
        snapshot = candidates.loc[:, columns].copy()
        snapshot["date"] = as_of
        self.history_frames.append(snapshot)
        self._last_observed_date = as_of

    def _update(self, as_of: pd.Timestamp, price_history: pd.DataFrame) -> None:
        base_audit = {"as_of": as_of, "training_month": as_of.strftime("%Y-%m")}
        if not self.history_frames:
            self.audit_rows.append({
                **base_audit, "status": self.status, "matured_dates": 0,
                "reliability_blend": self.reliability_blend,
                "calibration_window": self.calibration_window,
            })
            return
        from functions.decision_council.monthly_lgbm_hybrid import build_excess_return_labels

        history = pd.concat(self.history_frames, ignore_index=True)
        prices = price_history.copy()
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        prices = prices[prices["date"].le(as_of)]
        benchmark_columns = [column for column in ("date", "close", "open_nominal", "open") if column in prices]
        benchmark = prices[prices["symbol"].astype(str).eq(self.benchmark_symbol)][benchmark_columns]
        stocks = prices[~prices["symbol"].astype(str).eq(self.benchmark_symbol)]
        if benchmark.empty or stocks.empty:
            self.status = "fallback_benchmark_unavailable"
            self.reliability_blend = 0.0
            self.audit_rows.append({
                **base_audit, "status": self.status, "matured_dates": 0,
                "reliability_blend": self.reliability_blend,
                "calibration_window": self.calibration_window,
            })
            return
        labels = build_excess_return_labels(
            stocks, horizon_days=self.horizon_days, benchmark_prices=benchmark,
            round_trip_cost_rate=self.round_trip_cost_rate,
        )
        merged = history.merge(
            labels[["date", "symbol", "label_maturity_date", "future_excess_log_return_net"]],
            on=["date", "symbol"], how="inner",
        )
        merged = merged[pd.to_datetime(merged["label_maturity_date"]).le(as_of)]
        dates = pd.Index(sorted(merged["date"].dropna().unique()))
        if len(dates) > self.rolling_dates:
            dates = dates[-self.rolling_dates:]
            merged = merged[merged["date"].isin(dates)]
        if len(dates) < self.minimum_dates:
            self.status = "fallback_insufficient_matured_history"
            self.reliability_blend = 0.0
            self.audit_rows.append({
                **base_audit, "status": self.status, "matured_dates": len(dates),
                "reliability_blend": self.reliability_blend,
                "calibration_window": self.calibration_window,
            })
            return
        role_rows = []
        evidences = []
        for column in ROLE_COLUMNS:
            daily_ic = merged.groupby("date", sort=False).apply(
                lambda group: group[column].corr(group["future_excess_log_return_net"], method="spearman"),
                include_groups=False,
            ).dropna()
            mean = float(daily_ic.mean()) if not daily_ic.empty else 0.0
            se = float(daily_ic.std(ddof=1) / np.sqrt(len(daily_ic))) if len(daily_ic) > 1 else float("inf")
            probability_positive = _normal_cdf(mean / se) if np.isfinite(se) and se > 0 else float(mean > 0)
            evidence = float(np.clip(2.0 * (probability_positive - 0.5), -1.0, 1.0))
            evidences.append(evidence)
            role_rows.append((column, mean, se, probability_positive, evidence, len(daily_ic)))
        utilities = np.asarray(evidences, dtype=float)
        utilities -= np.nanmax(utilities)
        raw_weights = np.exp(utilities)
        raw_weights /= raw_weights.sum()
        self.role_weights = dict(zip(ROLE_COLUMNS, raw_weights.astype(float)))
        sample_shrinkage = float(len(dates) / (len(dates) + self.minimum_dates))
        evidence_confidence = float(max(np.max(evidences), 0.0))
        self.reliability_blend = float(np.clip(sample_shrinkage * evidence_confidence, 0.0, 1.0))
        self.status = "rolling_matured_reliability_active" if self.reliability_blend > 0 else "fallback_no_positive_role_evidence"
        self.calibration_window = f"{pd.Timestamp(dates[0]).date()}_to_{pd.Timestamp(dates[-1]).date()}"
        audit = {
            **base_audit, "status": self.status, "matured_dates": len(dates),
            "calibration_window": self.calibration_window, "reliability_blend": self.reliability_blend,
            "sample_shrinkage": sample_shrinkage, "maximum_role_evidence": evidence_confidence,
        }
        for column, mean, se, probability, evidence, count in role_rows:
            name = column.removeprefix("cabinet_").removesuffix("_score")
            audit[f"{name}__rank_ic_mean"] = mean
            audit[f"{name}__rank_ic_se"] = se
            audit[f"{name}__probability_positive"] = probability
            audit[f"{name}__evidence"] = evidence
            audit[f"{name}__weight"] = self.role_weights[column]
            audit[f"{name}__date_count"] = count
        self.audit_rows.append(audit)

    def audit_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.audit_rows)
