# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass

import pandas as pd

from config import LABEL_DEFAULT_HORIZONS, LABEL_DEFAULT_TARGET_RETURN
from functions.pricing.feature_leakage_audit import validate_label_metadata


@dataclass(frozen=True)
class LabelSpec:
    name: str
    task_type: str
    horizon: int
    formula: str
    uses_path_dependent_stat: bool
    uses_future_window_aggregate: bool
    description: str


def default_label_specs():
    specs = {}
    for horizon in LABEL_DEFAULT_HORIZONS:
        specs[f"future_ret_{horizon}"] = LabelSpec(
            name=f"future_ret_{horizon}",
            task_type="regression",
            horizon=horizon,
            formula=f"close[t+{horizon}] / close[t] - 1",
            uses_path_dependent_stat=False,
            uses_future_window_aggregate=False,
            description=f"Future {horizon}-day return based on close-to-close ratio.",
        )

    specs["binary_updown_label"] = LabelSpec(
        name="binary_updown_label",
        task_type="classification",
        horizon=LABEL_DEFAULT_HORIZONS[0],
        formula=f"1 if future_ret_{LABEL_DEFAULT_HORIZONS[0]} > 0 else 0",
        uses_path_dependent_stat=False,
        uses_future_window_aggregate=False,
        description="Binary direction label based on positive future return.",
    )
    specs["below_target_penalized_return"] = LabelSpec(
        name="below_target_penalized_return",
        task_type="regression",
        horizon=LABEL_DEFAULT_HORIZONS[1],
        formula=(
            f"future_ret_{LABEL_DEFAULT_HORIZONS[1]} - "
            f"max({LABEL_DEFAULT_TARGET_RETURN:.4f} - future_ret_{LABEL_DEFAULT_HORIZONS[1]}, 0)"
        ),
        uses_path_dependent_stat=False,
        uses_future_window_aggregate=False,
        description="Future return penalized when it falls below the configured target return.",
    )
    return specs


def label_metadata_map(specs=None):
    specs = specs or default_label_specs()
    return {
        name: asdict(spec)
        for name, spec in specs.items()
    }


def validate_label_specs(specs=None):
    specs = specs or default_label_specs()
    issues = []
    for name, spec in specs.items():
        if spec.task_type not in {"regression", "classification"}:
            issues.append(f"{name}: unsupported task_type {spec.task_type}")
        if not isinstance(spec.horizon, int) or spec.horizon <= 0:
            issues.append(f"{name}: horizon must be positive integer")
        if spec.uses_future_window_aggregate:
            issues.append(f"{name}: future-window aggregate labels are not allowed")
        issues.extend(validate_label_metadata(name, asdict(spec)))
    return issues


def apply_default_labels(df, price_col="close"):
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values(["symbol", "date"]).copy()
    if price_col not in data.columns:
        raise ValueError(f"Label price column is missing: {price_col}")
    grouped_close = data.groupby("symbol")[price_col]

    for horizon in LABEL_DEFAULT_HORIZONS:
        future_close = grouped_close.shift(-horizon)
        data[f"future_ret_{horizon}"] = future_close / data[price_col] - 1

    data["binary_updown_label"] = (
        data[f"future_ret_{LABEL_DEFAULT_HORIZONS[0]}"] > 0
    ).astype("Int64")
    target = LABEL_DEFAULT_TARGET_RETURN
    horizon = LABEL_DEFAULT_HORIZONS[1]
    future_ret = data[f"future_ret_{horizon}"]
    data["below_target_penalized_return"] = future_ret - (target - future_ret).clip(lower=0)
    return data


def build_label_formula_table(specs=None):
    specs = specs or default_label_specs()
    rows = []
    for spec in specs.values():
        rows.append(
            {
                "label_name": spec.name,
                "task_type": spec.task_type,
                "horizon": spec.horizon,
                "formula": spec.formula,
                "uses_path_dependent_stat": spec.uses_path_dependent_stat,
                "uses_future_window_aggregate": spec.uses_future_window_aggregate,
                "description": spec.description,
            }
        )
    return pd.DataFrame(rows)
