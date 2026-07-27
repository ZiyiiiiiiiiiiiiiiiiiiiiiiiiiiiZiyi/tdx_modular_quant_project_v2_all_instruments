"""Frozen environment manifest and benchmark-proxy preflight gates."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path

import pandas as pd

from functions.decision_council.outputs import write_governance_text

from config import (
    ADJUSTED_FEATURE_PRICE_MODE,
    DATA_VERSION,
    DECISION_COUNCIL_VERSION,
    GOVERNANCE_ENVIRONMENT_MANIFEST_JSON,
    SAFETY_PROXY_MAX_MISSING_DAYS,
    SAFETY_PROXY_MODE,
    SAFETY_PROXY_SYMBOLS,
    GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
    GOVERNANCE_ENTRY_RANK_LIMIT,
    GOVERNANCE_HOLD_RANK_LIMIT,
    GOVERNANCE_IMPACT_MODEL_VERSION,
    GOVERNANCE_PARTIAL_ADJUSTMENT_RATE,
)


class DataDependencyError(RuntimeError):
    """Raised when a frozen governance dependency is unavailable."""


def select_safety_proxy(feature_df: pd.DataFrame, proxy_symbols=SAFETY_PROXY_SYMBOLS) -> str | None:
    available = set(feature_df.get("symbol", pd.Series(dtype=object)).dropna().astype(str))
    return next((symbol for symbol in proxy_symbols if symbol in available), None)


def validate_safety_proxy(
    feature_df: pd.DataFrame,
    *,
    mode: str = SAFETY_PROXY_MODE,
    proxy_symbols=SAFETY_PROXY_SYMBOLS,
    max_missing_days: int = SAFETY_PROXY_MAX_MISSING_DAYS,
) -> dict:
    if mode not in {"strict", "degraded_backtest"}:
        raise ValueError("SAFETY_PROXY_MODE must be 'strict' or 'degraded_backtest'")
    proxy_symbol = select_safety_proxy(feature_df, proxy_symbols)
    if proxy_symbol is None:
        if mode == "strict":
            raise DataDependencyError("No configured HS300 ETF safety proxy is available")
        return {"proxy_symbol": None, "degraded": True, "max_consecutive_missing_days": None}

    dates = pd.DatetimeIndex(
        pd.to_datetime(feature_df["date"], errors="coerce").dropna().drop_duplicates().sort_values()
    )
    proxy_dates = pd.DatetimeIndex(pd.to_datetime(
        feature_df.loc[feature_df["symbol"].astype(str) == proxy_symbol, "date"],
        errors="coerce",
    ).dropna().drop_duplicates())
    missing = pd.Series(~dates.isin(proxy_dates), index=dates)
    streak = _max_true_streak(missing.tolist())
    if streak > max_missing_days and mode == "strict":
        raise DataDependencyError(
            f"Safety proxy {proxy_symbol} is missing for {streak} consecutive trading days"
        )
    return {
        "proxy_symbol": proxy_symbol,
        "degraded": bool(streak > max_missing_days),
        "max_consecutive_missing_days": streak,
    }


def build_environment_manifest(
    feature_df: pd.DataFrame,
    *,
    safety_proxy_mode: str = SAFETY_PROXY_MODE,
    config_values: dict | None = None,
    data_fingerprints: dict | None = None,
    calendar_version: str = "feature_dates_v1",
    random_seed: int = 42,
) -> dict:
    proxy = validate_safety_proxy(feature_df, mode=safety_proxy_mode)
    dates = pd.to_datetime(feature_df["date"], errors="coerce").dropna()
    frozen_config = {
        "decision_council_version": DECISION_COUNCIL_VERSION,
        "safety_proxy_mode": safety_proxy_mode,
        "data_version": DATA_VERSION,
        **(config_values or {}),
    }
    encoded = json.dumps(frozen_config, sort_keys=True, default=str).encode("utf-8")
    manifest = {
        "python_path": sys.executable,
        "python_version": platform.python_version(),
        "package_versions": _package_versions(),
        "pip_freeze": _all_package_versions(),
        "config_hash": hashlib.sha256(encoded).hexdigest(),
        "frozen_config": frozen_config,
        "random_seed": int(random_seed),
        "calendar_version": calendar_version,
        "feature_snapshot_date": dates.max().date().isoformat() if not dates.empty else None,
        "adjustment_mode": ADJUSTED_FEATURE_PRICE_MODE,
        "benchmark_proxy_symbol": proxy["proxy_symbol"],
        "safety_proxy_degraded": proxy["degraded"],
        "data_fingerprints": data_fingerprints or {},
        "feature_selection_log": {
            "phase_one_rule_alpha": ["ret_20", "score_mom_lowvol", "close_to_ma20"],
            "risk_inputs": ["volatility_20", "amount", "amount_ma20"],
        },
        "feature_preprocessing_params": {
            "rule_alpha_scale": "cross_section_abs_median_per_decision_date",
            "standardization": "none_phase_one_rules",
        },
        "threshold_migration_log": [
            {
                "version": DECISION_COUNCIL_VERSION,
                "status": "temporary_frozen_exploratory",
                "entry_rank_limit": GOVERNANCE_ENTRY_RANK_LIMIT,
                "hold_rank_limit": GOVERNANCE_HOLD_RANK_LIMIT,
                "daily_turnover_budget": GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
                "partial_adjustment_rate": GOVERNANCE_PARTIAL_ADJUSTMENT_RATE,
                "note": "Replace with endogenous no-trade region after execution-cost calibration.",
            }
        ],
        "impact_model_version": GOVERNANCE_IMPACT_MODEL_VERSION,
        "impact_model_calibration_status": "uncalibrated_daily_proxy_requires_vwap_validation",
    }
    return manifest


def save_environment_manifest(manifest: dict, output_path=GOVERNANCE_ENVIRONMENT_MANIFEST_JSON) -> Path:
    return write_governance_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        output_path,
        encoding="utf-8",
    )


def _max_true_streak(flags) -> int:
    longest = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def _package_versions() -> dict:
    names = ("numpy", "pandas", "pyarrow", "scikit-learn", "xgboost", "lightgbm", "baostock")
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _all_package_versions() -> dict:
    """Freeze the full installed distribution set for reproducible research."""
    packages = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages[str(name)] = distribution.version
    return dict(sorted(packages.items(), key=lambda item: item[0].lower()))
