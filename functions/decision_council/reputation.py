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
            }
        )
        self.history = []

    def record_rewards(self, rewards: dict[str, float], *, as_of, trading_day_index: int) -> pd.DataFrame:
        previous_active = self.state["active_reputation_weight"].astype(float).copy()
        alpha = 1.0 - math.exp(math.log(0.5) / GOVERNANCE_REPUTATION_HALF_LIFE)
        for index, row in self.state.iterrows():
            reward = float(rewards.get(row["model_name"], 0.0))
            clipped = min(max(reward, -0.10), 0.10)
            self.state.at[index, "score_ema"] = (1 - alpha) * float(row["score_ema"]) + alpha * clipped
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
            return
        z = (scores - float(scores.mean())) / std
        self.state["z_score_model"] = z
        self.state["candidate_weight"] = (1.0 + GOVERNANCE_REPUTATION_SENSITIVITY * z).clip(
            GOVERNANCE_REPUTATION_MIN_WEIGHT,
            GOVERNANCE_REPUTATION_MAX_WEIGHT,
        )

    def _activate_candidate_weights(self):
        old = self.state["active_reputation_weight"].astype(float)
        lower = old * (1.0 - GOVERNANCE_REPUTATION_MAX_STEP_RATIO)
        upper = old * (1.0 + GOVERNANCE_REPUTATION_MAX_STEP_RATIO)
        self.state["active_reputation_weight"] = self.state["candidate_weight"].clip(lower=lower, upper=upper)
