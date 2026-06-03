"""Replaceable second-stage safety and contextual-bandit policies."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


def fit_isotonic_calibration_table(raw_probabilities, outcomes) -> pd.DataFrame:
    """Fit a dependency-free monotonic probability table on a frozen validation set."""
    raw = pd.to_numeric(pd.Series(list(raw_probabilities)), errors="coerce").reset_index(drop=True)
    observed = pd.to_numeric(pd.Series(list(outcomes)), errors="coerce").reset_index(drop=True)
    if len(raw) != len(observed):
        raise ValueError("Calibration probabilities and outcomes must have equal length")
    data = pd.DataFrame(
        {
            "raw_probability": raw,
            "outcome": observed,
        }
    ).dropna()
    if data.empty:
        raise ValueError("Calibration validation set is empty")
    if not data["raw_probability"].between(0.0, 1.0).all():
        raise ValueError("Raw probabilities must be in [0, 1]")
    if not data["outcome"].isin([0.0, 1.0]).all():
        raise ValueError("Calibration outcomes must be binary")

    grouped = (
        data.groupby("raw_probability", as_index=False)
        .agg(successes=("outcome", "sum"), count=("outcome", "size"))
        .sort_values("raw_probability")
    )
    blocks = []
    for row in grouped.itertuples(index=False):
        blocks.append(
            {
                "min_raw": float(row.raw_probability),
                "max_raw": float(row.raw_probability),
                "successes": float(row.successes),
                "count": int(row.count),
            }
        )
        while len(blocks) >= 2 and _block_rate(blocks[-2]) > _block_rate(blocks[-1]):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                {
                    "min_raw": left["min_raw"],
                    "max_raw": right["max_raw"],
                    "successes": left["successes"] + right["successes"],
                    "count": left["count"] + right["count"],
                }
            )
    rows = []
    for block in blocks:
        rows.append(
            {
                "raw_probability": block["min_raw"],
                "calibrated_probability": _block_rate(block),
                "validation_rows": block["count"],
            }
        )
        if block["max_raw"] != block["min_raw"]:
            rows.append(
                {
                    "raw_probability": block["max_raw"],
                    "calibrated_probability": _block_rate(block),
                    "validation_rows": block["count"],
                }
            )
    table = pd.DataFrame(rows).drop_duplicates("raw_probability", keep="last")
    return table.sort_values("raw_probability").reset_index(drop=True)


class ModelBasedSafetyAgent:
    """Apply a frozen monotonic calibration table to raw crash probabilities."""

    def __init__(self, calibration_table: pd.DataFrame, *, warning_threshold=0.20, high_threshold=0.40, crisis_threshold=0.60):
        required = {"raw_probability", "calibrated_probability"}
        missing = sorted(required - set(calibration_table.columns))
        if missing:
            raise ValueError(f"Calibration table missing columns: {missing}")
        table = calibration_table[list(required)].copy().sort_values("raw_probability")
        table["raw_probability"] = pd.to_numeric(table["raw_probability"], errors="coerce")
        table["calibrated_probability"] = pd.to_numeric(table["calibrated_probability"], errors="coerce")
        table = table.dropna().drop_duplicates("raw_probability")
        if table.empty:
            raise ValueError("Calibration table must contain at least one valid row")
        if not table["calibrated_probability"].between(0.0, 1.0).all():
            raise ValueError("Calibrated probabilities must be in [0, 1]")
        if not table["calibrated_probability"].is_monotonic_increasing:
            raise ValueError("Calibration table must be monotonic")
        self.table = table.reset_index(drop=True)
        self.warning_threshold = float(warning_threshold)
        self.high_threshold = max(float(high_threshold), self.warning_threshold)
        self.crisis_threshold = max(float(crisis_threshold), self.high_threshold)

    def calibrate(self, raw_probability) -> np.ndarray:
        raw = np.asarray(raw_probability, dtype=float)
        return np.interp(
            raw,
            self.table["raw_probability"].to_numpy(dtype=float),
            self.table["calibrated_probability"].to_numpy(dtype=float),
        )

    def decide(self, raw_probability: float) -> dict:
        probability = float(self.calibrate([raw_probability])[0])
        if probability >= self.crisis_threshold:
            level, cap = "crisis", 0.0
        elif probability >= self.high_threshold:
            level, cap = "high", 0.3
        elif probability >= self.warning_threshold:
            level, cap = "warning", 0.7
        else:
            level, cap = "normal", 1.0
        return {"p_crash_5d": probability, "risk_level": level, "exposure_cap": cap}


@dataclass(frozen=True)
class BanditAction:
    action_id: str
    top_n: int
    minimum_holding_days: int
    turnover_budget: float


def validate_bandit_actions(actions, *, baseline: BanditAction, bound_ratio: float = 0.20):
    """Reject broad action spaces that cannot be learned reliably from sparse returns."""
    dimensions = ("top_n", "minimum_holding_days", "turnover_budget")
    for action in actions:
        changed = []
        for dimension in dimensions:
            base_value = float(getattr(baseline, dimension))
            action_value = float(getattr(action, dimension))
            if abs(action_value - base_value) > 1e-12:
                changed.append(dimension)
                if abs(action_value - base_value) / max(abs(base_value), 1e-12) > float(bound_ratio) + 1e-12:
                    raise ValueError(f"Bandit action {action.action_id} exceeds +/-{bound_ratio:.0%}: {dimension}")
        if len(changed) > 1:
            raise ValueError(f"Bandit action {action.action_id} changes more than one dimension: {changed}")
    return True


class ContextualBanditPresidentPolicy:
    """Finite-action LinUCB selector that leaves execution constraints untouched."""

    def __init__(self, actions, context_size: int, exploration_alpha: float = 0.5):
        self.actions = tuple(actions)
        if not self.actions:
            raise ValueError("At least one bandit action is required")
        self.context_size = int(context_size)
        self.exploration_alpha = float(exploration_alpha)
        self._a = {action.action_id: np.eye(self.context_size) for action in self.actions}
        self._b = {action.action_id: np.zeros(self.context_size) for action in self.actions}

    def select_action(self, context_vector) -> BanditAction:
        x = self._vector(context_vector)
        scored = []
        for action in self.actions:
            inv = np.linalg.inv(self._a[action.action_id])
            theta = inv @ self._b[action.action_id]
            score = float(theta @ x + self.exploration_alpha * np.sqrt(x @ inv @ x))
            scored.append((score, action.action_id, action))
        return max(scored, key=lambda item: (item[0], item[1]))[2]

    def update(self, action_id: str, context_vector, reward: float):
        if action_id not in self._a:
            raise KeyError(f"Unknown bandit action: {action_id}")
        x = self._vector(context_vector)
        self._a[action_id] += np.outer(x, x)
        self._b[action_id] += float(reward) * x

    def _vector(self, values):
        vector = np.asarray(values, dtype=float)
        if vector.shape != (self.context_size,):
            raise ValueError(f"Expected context vector shape {(self.context_size,)}, got {vector.shape}")
        return vector


class BanditDelegatingPresidentPolicy:
    """Select governance parameters with LinUCB, then delegate to the rules policy."""

    def __init__(self, bandit: ContextualBanditPresidentPolicy, delegate=None):
        if delegate is None:
            from functions.decision_council.policy import RulesBasedPresidentPolicy

            delegate = RulesBasedPresidentPolicy()
        self.bandit = bandit
        self.delegate = delegate
        self.last_action_id = None
        self.last_context_vector = None

    def decide(self, context, *, context_vector):
        action = self.bandit.select_action(context_vector)
        delegated_context = replace(
            context,
            top_n=int(action.top_n),
            minimum_holding_days=int(action.minimum_holding_days),
            turnover_budget=float(action.turnover_budget),
        )
        ideal, orders, diagnostics = self.delegate.decide(delegated_context)
        self.last_action_id = action.action_id
        self.last_context_vector = np.asarray(context_vector, dtype=float)
        return ideal, orders, {
            **diagnostics,
            "bandit_action_id": action.action_id,
            "bandit_top_n": int(action.top_n),
            "bandit_minimum_holding_days": int(action.minimum_holding_days),
            "bandit_turnover_budget": float(action.turnover_budget),
        }

    def update_last_action(self, reward: float):
        if self.last_action_id is None or self.last_context_vector is None:
            raise RuntimeError("Bandit policy must decide before receiving a reward")
        self.bandit.update(self.last_action_id, self.last_context_vector, reward)


def _block_rate(block) -> float:
    return float(block["successes"]) / max(int(block["count"]), 1)
