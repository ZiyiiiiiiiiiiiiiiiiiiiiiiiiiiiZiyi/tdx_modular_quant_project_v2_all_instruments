"""Factor Judge v2 profile loading and factor-to-profile mapping."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_PROFILE_PATH = Path("config/factor_judge_profiles.yaml")


@dataclass(frozen=True)
class FactorJudgeProfile:
    name: str
    description: str
    use_for: tuple[str, ...]
    horizons: tuple[int, ...]
    role_candidates: tuple[str, ...]
    metrics: dict[str, Any]
    neutralize: tuple[str, ...] = ()
    allow_non_monotonic: bool = False
    point_in_time_required: bool = False
    event_window_mode: bool = False


def load_factor_judge_profiles(path: str | Path = DEFAULT_PROFILE_PATH) -> dict[str, FactorJudgeProfile]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Factor judge profile config not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    profiles = {}
    for name, raw in dict(payload.get("profiles", {})).items():
        profiles[str(name)] = FactorJudgeProfile(
            name=str(name),
            description=str(raw.get("description", "")),
            use_for=tuple(str(item).lower() for item in raw.get("use_for", []) or []),
            horizons=tuple(int(item) for item in raw.get("horizons", []) or []),
            role_candidates=tuple(str(item) for item in raw.get("role_candidates", []) or []),
            metrics=dict(raw.get("metrics", {}) or {}),
            neutralize=tuple(str(item) for item in raw.get("neutralize", []) or []),
            allow_non_monotonic=bool(raw.get("allow_non_monotonic", False)),
            point_in_time_required=bool(raw.get("point_in_time_required", False)),
            event_window_mode=bool(raw.get("event_window_mode", False)),
        )
    if not profiles:
        raise ValueError(f"No factor judge profiles defined in {config_path}")
    return profiles


def infer_factor_type(factor_name: str, module: str = "", family: str = "") -> str | None:
    text = "|".join([str(factor_name), str(module), str(family)]).lower()
    checks = [
        ("rsi", ("rsi",)),
        ("macd", ("macd",)),
        ("kdj", ("kdj",)),
        ("bollinger", ("bollinger", "bbands", "band")),
        ("turtle_breakout", ("turtle",)),
        ("breakout", ("breakout", "price_pos")),
        ("pullback_confirmation", ("kline", "shadow", "gap", "close_loc", "body_mean")),
        ("reversal", ("reversal", "rev_")),
        ("momentum", ("momentum", "ret_", "trend", "relative_strength", "range_grid")),
        ("volatility", ("volatility", "vol_neg", "downvol", "drawdown", "skew", "kurtosis", "higher_moment")),
        ("liquidity", ("liquidity", "amihud", "turnover")),
        ("volume_price", ("volume", "amount", "obv", "money_flow", "close_volume", "flow_close", "eod_close")),
        ("orderflow_proxy", ("orderflow", "large_order")),
        ("low_noise", ("low_noise",)),
        ("growth", ("growth", "revenue_yoy", "profit_yoy")),
        ("profitability", ("profitability", "roe", "roa", "margin")),
        ("cashflow", ("cashflow", "ocf", "fcf", "accrual")),
        ("quality", ("quality", "piotroski")),
        ("valuation", ("valuation", "pe_", "pb_", "value_proxy", "peg")),
        ("barra_style", ("barra", "beta", "size")),
        ("earnings_surprise", ("earnings", "surprise")),
        ("announcement", ("announcement", "buyback", "shareholder", "event_limit", "limit_up", "holiday_effect")),
        ("alternative_proxy", ("sentiment", "supply_chain", "social", "attention", "crowding")),
    ]
    for factor_type, tokens in checks:
        if any(token in text for token in tokens):
            return factor_type
    return None


def map_factor_to_profile(
    factor_name: str,
    module: str = "",
    family: str = "",
    *,
    profiles: dict[str, FactorJudgeProfile] | None = None,
) -> tuple[str | None, str | None]:
    profiles = profiles or load_factor_judge_profiles()
    factor_type = infer_factor_type(factor_name, module=module, family=family)
    if factor_type is None:
        return None, None
    for profile in profiles.values():
        if factor_type in profile.use_for:
            return profile.name, factor_type
    return None, factor_type


def build_profile_mapping_report(factors: pd.DataFrame, *, profiles=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    profiles = profiles or load_factor_judge_profiles()
    rows = []
    unmapped = []
    if factors is None:
        factors = pd.DataFrame()
    for _, row in factors.iterrows():
        factor_name = str(row.get("factor_name", ""))
        module = str(row.get("module", ""))
        family = str(row.get("family", ""))
        profile_name, factor_type = map_factor_to_profile(
            factor_name,
            module=module,
            family=family,
            profiles=profiles,
        )
        payload = {
            "factor_name": factor_name,
            "module": module,
            "family": family,
            "factor_type": factor_type or "",
            "judge_profile": profile_name or "",
        }
        rows.append(payload)
        if not profile_name:
            unmapped.append({**payload, "reason": "profile_not_mapped"})
    return pd.DataFrame(rows), pd.DataFrame(unmapped)
