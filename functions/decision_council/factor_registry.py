"""Governance factor registry used by post-run research diagnostics.

The registry is intentionally metadata-only. It does not change trading
decisions; it gives every alpha input an auditable identity and role.
"""
from __future__ import annotations

import pandas as pd

from config import (
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_CLUSTER_MAX_WEIGHT,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
    GOVERNANCE_FACTOR_MIN_ABS_RANK_IC,
    GOVERNANCE_FACTOR_MIN_COVERAGE,
    GOVERNANCE_FACTOR_MIN_IC_IR,
    GOVERNANCE_FACTOR_MIN_RANK_IC_POSITIVE_RATIO,
    GOVERNANCE_FACTOR_MIN_SAMPLE_COUNT,
    GOVERNANCE_FACTOR_MIN_TOP_BOTTOM_SPREAD_10D,
)
from functions.decision_council.analytics import factor_module
from functions.factors.factor_candidate_pool import candidate_factor_registry_rows


def build_factor_registry() -> dict[str, dict]:
    """Return metadata for governance alpha factors configured in config.py."""
    registry: dict[str, dict] = {}
    for factor_name, column in GOVERNANCE_ALPHA_MODEL_FEATURES.items():
        module = factor_module(factor_name)
        role = _role_for_module(factor_name, module)
        registry[str(factor_name)] = {
            "factor_name": str(factor_name),
            "module": module,
            "source_file": _source_file_for_column(column),
            "raw_column": str(column),
            "direction": "higher_better",
            "horizons": "5|10|20",
            "allowed_roles": "|".join(role["allowed_roles"]),
            "requires_pit": True,
            "neutralize_industry": bool(module not in {"event_limit"}),
            "neutralize_size": True,
            "min_coverage": float(GOVERNANCE_FACTOR_MIN_COVERAGE),
            "min_ic_ir": float(GOVERNANCE_FACTOR_MIN_IC_IR),
            "min_abs_rank_ic": float(GOVERNANCE_FACTOR_MIN_ABS_RANK_IC),
            "min_rank_ic_positive_ratio": float(GOVERNANCE_FACTOR_MIN_RANK_IC_POSITIVE_RATIO),
            "min_top_bottom_spread_10d": float(GOVERNANCE_FACTOR_MIN_TOP_BOTTOM_SPREAD_10D),
            "min_sample_count": int(GOVERNANCE_FACTOR_MIN_SAMPLE_COUNT),
            "cluster_weight_cap": float(GOVERNANCE_CLUSTER_MAX_WEIGHT),
            "status": "experimental",
            "role_rationale": role["role_rationale"],
            "candidate_pool": "governance_formal",
        }
    for row in candidate_factor_registry_rows():
        factor_name = str(row["factor_name"])
        if factor_name in registry:
            continue
        role = _role_for_module(factor_name, str(row.get("module", "unknown")))
        admitted_roles = GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP.get(factor_name)
        is_v2_admitted = factor_name in set(GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2)
        registry[factor_name] = {
            "factor_name": factor_name,
            "module": str(row.get("module", "unknown")),
            "source_file": str(row.get("source_file", "functions/factors/factor_candidate_pool.py")),
            "raw_column": str(row["raw_column"]),
            "direction": str(row.get("direction", "higher_better")),
            "horizons": "5|10|20",
            "allowed_roles": "|".join(admitted_roles) if admitted_roles else "observe_only",
            "requires_pit": True,
            "neutralize_industry": bool(row.get("neutralize_industry", True)),
            "neutralize_size": bool(row.get("neutralize_size", True)),
            "min_coverage": float(GOVERNANCE_FACTOR_MIN_COVERAGE),
            "min_ic_ir": float(GOVERNANCE_FACTOR_MIN_IC_IR),
            "min_abs_rank_ic": float(GOVERNANCE_FACTOR_MIN_ABS_RANK_IC),
            "min_rank_ic_positive_ratio": float(GOVERNANCE_FACTOR_MIN_RANK_IC_POSITIVE_RATIO),
            "min_top_bottom_spread_10d": float(GOVERNANCE_FACTOR_MIN_TOP_BOTTOM_SPREAD_10D),
            "min_sample_count": int(GOVERNANCE_FACTOR_MIN_SAMPLE_COUNT),
            "cluster_weight_cap": float(GOVERNANCE_CLUSTER_MAX_WEIGHT),
            "status": "tradable_candidate_v2" if is_v2_admitted else "pre_screen",
            "role_rationale": (
                "admitted into diversified_pre_screen_bundle_v2 with explicit state-machine roles"
                if is_v2_admitted
                else "pre-screen candidate; may enter formal pool only after validation"
            ),
            "candidate_pool": "pre_screen_candidate",
        }
    return registry


def factor_registry_snapshot(registry: dict[str, dict] | None = None) -> pd.DataFrame:
    """Flatten registry metadata to a CSV-friendly frame."""
    registry = registry or build_factor_registry()
    columns = [
        "factor_name",
        "module",
        "source_file",
        "raw_column",
        "direction",
        "horizons",
        "allowed_roles",
        "requires_pit",
        "neutralize_industry",
        "neutralize_size",
        "min_coverage",
        "min_abs_rank_ic",
        "min_ic_ir",
        "min_rank_ic_positive_ratio",
        "min_top_bottom_spread_10d",
        "min_sample_count",
        "cluster_weight_cap",
        "status",
        "candidate_pool",
        "role_rationale",
    ]
    rows = [dict(meta) for _, meta in sorted(registry.items())]
    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[columns]


def _role_for_module(factor_name: str, module: str) -> dict:
    name = str(factor_name).lower()
    module = str(module).lower()
    if module in {"trend", "flow_close"}:
        return {
            "allowed_roles": ["buy", "hold_validation", "sell_warning"],
            "role_rationale": "trend and flow factors can support entries and warn on continuation failure",
        }
    if module in {"reversal_pullback", "range_grid"}:
        return {
            "allowed_roles": ["buy", "hold_validation"],
            "role_rationale": "reversal factors are entry timing tools and should not force exits alone",
        }
    if module in {"event_limit"} or "limit" in name or "event" in name:
        return {
            "allowed_roles": ["buy", "sell_warning", "risk_override"],
            "role_rationale": "event factors decay quickly and require separate hold validation",
        }
    if module in {"defensive"} or "lowvol" in name:
        return {
            "allowed_roles": ["hold_validation", "risk_override"],
            "role_rationale": "defensive factors are primarily sizing and risk-control inputs",
        }
    return {
        "allowed_roles": ["buy", "hold_validation"],
        "role_rationale": "default alpha input; sell usage requires separate validation",
    }


def _source_file_for_column(column: str) -> str:
    column = str(column)
    if "orderflow" in column or "eod_close" in column:
        return "functions/factors/advanced_price_volume.py"
    if "momentum" in column or "mom" in column or "ret_" in column:
        return "functions/factors/factor_momentum.py"
    if "reversion" in column or "rsi" in column or "kdj" in column or "decline" in column:
        return "functions/factors/factor_reversal.py"
    if "vol" in column or "lowvol" in column:
        return "functions/factors/factor_volatility.py"
    if "ml" in column:
        return "functions/factors/factor_ml.py"
    if any(token in column for token in ("value", "quality", "growth", "fundamental")):
        return "functions/feature_engineering.py"
    return "functions/factors"
