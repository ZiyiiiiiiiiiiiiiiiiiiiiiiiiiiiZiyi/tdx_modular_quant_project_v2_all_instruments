"""Cross-sectional reputation mapping for governance voters."""
from __future__ import annotations

import math

import pandas as pd

from config import (
    GOVERNANCE_REPUTATION_HALF_LIFE,
    GOVERNANCE_REPUTATION_MAX_STEP_RATIO,
    GOVERNANCE_REPUTATION_MAX_WEIGHT,
    GOVERNANCE_REPUTATION_MIN_WEIGHT,
    GOVERNANCE_REPUTATION_SENSITIVITY,
    GOVERNANCE_REPUTATION_UPDATE_DAYS,
    GOVERNANCE_REPUTATION_WARMUP_DAYS,
)


class ReputationLedger:
    def __init__(self, model_names):
        self.state = pd.DataFrame(
            {
                "model_name": list(model_names),
                "score_ema": 0.0,
                "candidate_weight": 1.0,
                "active_reputation_weight": 1.0,
                "activity_ema": 0.0,
                "coverage_ema": 0.0,
                "avg_exposure_ema": 0.0,
                "zero_exposure_penalty": 1.0,
                "coverage_penalty": 1.0,
                "opportunity_adjusted_reward": 0.0,
            }
        )
        self.history = []

    def record_rewards(
        self,
        rewards: dict[str, float],
        *,
        as_of,
        trading_day_index: int,
        model_activity: dict[str, dict] | None = None,
    ) -> pd.DataFrame:
        previous_active = self.state["active_reputation_weight"].astype(float).copy()
        alpha = 1.0 - math.exp(math.log(0.5) / GOVERNANCE_REPUTATION_HALF_LIFE)
        activity = model_activity or {}
        has_activity_payload = bool(activity)
        for index, row in self.state.iterrows():
            model_name = str(row["model_name"])
            info = activity.get(model_name, {})
            exposure = max(float(info.get("actual_exposure", 0.0) or 0.0), 0.0)
            holding_count = max(float(info.get("holding_count", 0.0) or 0.0), 0.0)
            active_flag = 1.0 if (not has_activity_payload or (exposure >= 0.05 and holding_count > 0)) else 0.0
            coverage_flag = 1.0 if (not has_activity_payload or holding_count > 0 or model_name in rewards) else 0.0
            reward = float(rewards.get(model_name, 0.0))
            adjusted_reward = reward * max(active_flag, 0.25 * coverage_flag)
            clipped = min(max(reward, -0.10), 0.10)
            clipped_adjusted = min(max(adjusted_reward, -0.10), 0.10)
            self.state.at[index, "score_ema"] = (1 - alpha) * float(row["score_ema"]) + alpha * clipped_adjusted
            self.state.at[index, "activity_ema"] = (1 - alpha) * float(row.get("activity_ema", 0.0)) + alpha * active_flag
            self.state.at[index, "coverage_ema"] = (1 - alpha) * float(row.get("coverage_ema", 0.0)) + alpha * coverage_flag
            self.state.at[index, "avg_exposure_ema"] = (1 - alpha) * float(row.get("avg_exposure_ema", 0.0)) + alpha * exposure
            self.state.at[index, "opportunity_adjusted_reward"] = adjusted_reward
        self._map_candidate_weights()
        if trading_day_index >= GOVERNANCE_REPUTATION_WARMUP_DAYS and trading_day_index % GOVERNANCE_REPUTATION_UPDATE_DAYS == 0:
            self._activate_candidate_weights()
        elif trading_day_index < GOVERNANCE_REPUTATION_WARMUP_DAYS:
            self.state["active_reputation_weight"] = 1.0
        snapshot = self.state.copy()
        snapshot["date"] = pd.Timestamp(as_of)
        snapshot["trading_day_index"] = int(trading_day_index)
        snapshot["raw_reward"] = snapshot["model_name"].map(rewards).fillna(0.0)
        snapshot["clipped_reward"] = snapshot["raw_reward"].clip(-0.10, 0.10)
        snapshot["shadow_actual_exposure"] = snapshot["model_name"].map(
            lambda name: float((activity.get(str(name), {}) or {}).get("actual_exposure", 0.0) or 0.0)
        )
        snapshot["shadow_holding_count"] = snapshot["model_name"].map(
            lambda name: float((activity.get(str(name), {}) or {}).get("holding_count", 0.0) or 0.0)
        )
        snapshot["active_weight_drift"] = snapshot["active_reputation_weight"].astype(float) - previous_active.to_numpy()
        snapshot["hit_min_weight"] = snapshot["candidate_weight"].astype(float) <= GOVERNANCE_REPUTATION_MIN_WEIGHT + 1e-12
        snapshot["hit_max_weight"] = snapshot["candidate_weight"].astype(float) >= GOVERNANCE_REPUTATION_MAX_WEIGHT - 1e-12
        snapshot["cross_section_score_std"] = float(snapshot["score_ema"].astype(float).std(ddof=0))
        snapshot["model_weight_distinction"] = float(
            snapshot["active_reputation_weight"].astype(float).max()
            - snapshot["active_reputation_weight"].astype(float).min()
        )
        self.history.append(snapshot)
        return snapshot

    def weights(self) -> dict[str, float]:
        return dict(zip(self.state["model_name"], self.state["active_reputation_weight"]))

    def history_frame(self) -> pd.DataFrame:
        return pd.concat(self.history, ignore_index=True) if self.history else pd.DataFrame()

    def _map_candidate_weights(self):
        scores = self.state["score_ema"].astype(float)
        std = float(scores.std(ddof=0))
        if std < 1e-12:
            self.state["z_score_model"] = 0.0
            self.state["candidate_weight"] = 1.0
            self._apply_activity_penalties()
            return
        z = (scores - float(scores.mean())) / std
        self.state["z_score_model"] = z
        raw_weight = (1.0 + GOVERNANCE_REPUTATION_SENSITIVITY * z).clip(
            GOVERNANCE_REPUTATION_MIN_WEIGHT,
            GOVERNANCE_REPUTATION_MAX_WEIGHT,
        )
        self.state["candidate_weight"] = raw_weight
        self._apply_activity_penalties()

    def _apply_activity_penalties(self):
        activity = self.state["activity_ema"].astype(float).clip(0.0, 1.0)
        coverage = self.state["coverage_ema"].astype(float).clip(0.0, 1.0)
        avg_exposure = self.state["avg_exposure_ema"].astype(float).clip(lower=0.0)
        zero_penalty = (0.35 + 0.65 * activity).clip(0.35, 1.0)
        coverage_penalty = (0.50 + 0.50 * coverage).clip(0.50, 1.0)
        low_exposure_cap = pd.Series(1.0, index=self.state.index, dtype=float)
        low_exposure_cap = low_exposure_cap.mask(avg_exposure < 0.01, 1.0)
        low_exposure_cap = low_exposure_cap.mask((avg_exposure >= 0.01) & (avg_exposure < 0.05), 1.5)
        penalized = self.state["candidate_weight"].astype(float) * zero_penalty * coverage_penalty
        penalized = penalized.clip(upper=low_exposure_cap)
        self.state["zero_exposure_penalty"] = zero_penalty
        self.state["coverage_penalty"] = coverage_penalty
        self.state["candidate_weight"] = penalized.clip(
            GOVERNANCE_REPUTATION_MIN_WEIGHT,
            GOVERNANCE_REPUTATION_MAX_WEIGHT,
        )

    def _activate_candidate_weights(self):
        old = self.state["active_reputation_weight"].astype(float)
        lower = old * (1.0 - GOVERNANCE_REPUTATION_MAX_STEP_RATIO)
        upper = old * (1.0 + GOVERNANCE_REPUTATION_MAX_STEP_RATIO)
        self.state["active_reputation_weight"] = self.state["candidate_weight"].clip(lower=lower, upper=upper)
