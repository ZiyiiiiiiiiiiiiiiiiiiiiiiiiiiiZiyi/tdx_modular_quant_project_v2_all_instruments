"""Canonical economic-family and replacement-seat contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from functions.factors.pit_factor_registry import pit_factor_registry_rows


FAMILY_CONTRACT_VERSION = "economic_factor_family_contract_v1"


@dataclass(frozen=True)
class FactorFamilyContract:
    family: str
    target_min: int
    target_max: int
    allowed_roles: tuple[str, ...]
    formal_pit_required: bool
    selection_mode: str = "direct"
    causal_requirement: str = "causal_unknown_allowed"


FAMILY_CONTRACTS = (
    FactorFamilyContract("valuation", 2, 4, ("entry_alpha", "entry_alpha_proxy", "hold_validation"), True),
    FactorFamilyContract("profitability", 2, 5, ("entry_alpha", "entry_alpha_proxy", "hold_validation"), True),
    FactorFamilyContract("investment", 1, 4, ("entry_alpha_proxy", "risk_override", "hold_validation"), True),
    FactorFamilyContract("cashflow", 2, 5, ("entry_alpha", "entry_alpha_proxy", "risk_override", "hold_validation"), True),
    FactorFamilyContract("growth", 2, 5, ("entry_alpha", "entry_alpha_proxy", "hold_validation"), True),
    FactorFamilyContract("event", 1, 5, ("timing_filter", "risk_override", "hold_validation"), True, causal_requirement="registered_event_design"),
    FactorFamilyContract("rsi", 1, 4, ("timing_filter", "risk_override", "entry_alpha_proxy"), False),
    FactorFamilyContract("orderflow", 1, 5, ("liquidity_filter", "timing_filter", "entry_alpha_proxy"), False),
    FactorFamilyContract("breakout", 1, 4, ("timing_filter", "entry_alpha_proxy"), False),
    FactorFamilyContract("alternative_proxy", 0, 5, ("entry_alpha_proxy", "timing_filter", "liquidity_filter", "risk_override"), True),
    FactorFamilyContract("quality", 0, 1, ("hold_validation",), True, selection_mode="report_only_composite"),
)

FAMILY_ALIASES = {
    "value": "valuation", "valuation": "valuation",
    "profit": "profitability", "roe": "profitability", "roa": "profitability",
    "profitability": "profitability", "quality_profit": "profitability",
    "investment": "investment", "asset_growth": "investment", "capex": "investment",
    "cash": "cashflow", "cashflow": "cashflow", "cashflow_quality": "cashflow", "ocf": "cashflow",
    "growth": "growth", "growth_quality": "growth",
    "event": "event", "announcement": "event",
    "rsi": "rsi", "orderflow": "orderflow", "orderflow_proxy": "orderflow",
    "breakout": "breakout", "alternative": "alternative_proxy", "alternative_proxy": "alternative_proxy",
    "quality": "quality",
}


TECHNICAL_CANDIDATE_SPECS = (
    {"factor_name": "rsi_oversold_14", "raw_column": "cand_rsi_oversold_14", "family": "rsi", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "rsi_overheat_14", "raw_column": "cand_rsi_overheat_14", "family": "rsi", "allowed_roles": "risk_override", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "rsi_recovery_14", "raw_column": "cand_rsi_recovery_14", "family": "rsi", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "rsi_divergence_proxy", "raw_column": "cand_rsi_divergence_proxy", "family": "rsi", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "rsi_pullback_in_uptrend", "raw_column": "cand_rsi_pullback_in_uptrend", "family": "rsi", "allowed_roles": "timing_filter|entry_alpha_proxy", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "orderflow_amount_shock", "raw_column": "score_orderflow_amount_shock", "family": "orderflow", "allowed_roles": "liquidity_filter|timing_filter", "direction": "higher_better", "pit_requirement": "ohlcv_proxy"},
    {"factor_name": "orderflow_close_drive", "raw_column": "score_orderflow_close_drive", "family": "orderflow", "allowed_roles": "liquidity_filter", "direction": "higher_better", "pit_requirement": "ohlcv_proxy"},
    {"factor_name": "orderflow_accumulation", "raw_column": "score_orderflow_accumulation", "family": "orderflow", "allowed_roles": "liquidity_filter|entry_alpha_proxy", "direction": "higher_better", "pit_requirement": "ohlcv_proxy"},
    {"factor_name": "orderflow_efficiency", "raw_column": "score_orderflow_efficiency", "family": "orderflow", "allowed_roles": "liquidity_filter", "direction": "higher_better", "pit_requirement": "ohlcv_proxy"},
    {"factor_name": "eod_close_strength", "raw_column": "score_eod_close_strength", "family": "orderflow", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "ohlcv_proxy"},
    {"factor_name": "price_volume_breakout", "raw_column": "score_price_volume_breakout", "family": "breakout", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "turtle_breakout", "raw_column": "score_turtle_breakout", "family": "breakout", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "volatility_compression_breakout", "raw_column": "score_volatility_compression_breakout", "family": "breakout", "allowed_roles": "timing_filter", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "limit_up_follow", "raw_column": "score_limit_up_follow", "family": "breakout", "allowed_roles": "timing_filter|risk_override", "direction": "higher_better", "pit_requirement": "market_data_t_minus_0"},
    {"factor_name": "margin_financing_change", "raw_column": "cand_margin_financing_change", "family": "alternative_proxy", "allowed_roles": "entry_alpha_proxy|timing_filter", "direction": "higher_better", "pit_requirement": "external_timestamped"},
    {"factor_name": "etf_flow_proxy", "raw_column": "cand_etf_flow_proxy", "family": "alternative_proxy", "allowed_roles": "entry_alpha_proxy|liquidity_filter", "direction": "higher_better", "pit_requirement": "external_timestamped"},
    {"factor_name": "analyst_revision_proxy", "raw_column": "cand_analyst_revision_proxy", "family": "alternative_proxy", "allowed_roles": "entry_alpha_proxy", "direction": "higher_better", "pit_requirement": "external_timestamped"},
    {"factor_name": "announcement_text_sentiment", "raw_column": "cand_announcement_text_sentiment", "family": "alternative_proxy", "allowed_roles": "entry_alpha_proxy|timing_filter", "direction": "higher_better", "pit_requirement": "external_timestamped"},
)


def family_contract_frame() -> pd.DataFrame:
    rows = []
    for contract in FAMILY_CONTRACTS:
        row = asdict(contract)
        row["allowed_roles"] = "|".join(contract.allowed_roles)
        row["family_contract_version"] = FAMILY_CONTRACT_VERSION
        rows.append(row)
    return pd.DataFrame(rows)


def canonical_family(value, *, factor_name: str = "", module: str = "") -> str:
    text = " ".join((str(value or ""), str(factor_name or ""), str(module or ""))).lower()
    direct = FAMILY_ALIASES.get(str(value or "").strip().lower())
    if direct:
        return direct
    token_order = (
        ("orderflow", "orderflow"), ("breakout", "breakout"), ("turtle", "breakout"),
        ("rsi", "rsi"), ("valuation", "valuation"), ("book_to_price", "valuation"),
        ("earnings_yield", "valuation"), ("roe", "profitability"), ("roa", "profitability"),
        ("margin", "profitability"), ("capex", "investment"), ("asset_growth", "investment"),
        ("cash", "cashflow"), ("ocf", "cashflow"), ("accrual", "cashflow"),
        ("growth", "growth"), ("event", "event"), ("announcement", "event"),
    )
    return next((family for token, family in token_order if token in text), str(value or "unknown"))


def candidate_catalog_frame() -> pd.DataFrame:
    rows = []
    for spec in pit_factor_registry_rows():
        item = dict(spec)
        item["pit_requirement"] = "pit_level2"
        item["candidate_source"] = "pit_factor_registry"
        rows.append(item)
    for spec in TECHNICAL_CANDIDATE_SPECS:
        item = dict(spec)
        item["candidate_source"] = "canonical_candidate_catalog"
        rows.append(item)
    frame = pd.DataFrame(rows)
    frame["family"] = [
        canonical_family(family, factor_name=name, module=module)
        for family, name, module in zip(
            frame.get("family", ""), frame.get("factor_name", ""), frame.get("module", "")
        )
    ]
    frame["family_contract_version"] = FAMILY_CONTRACT_VERSION
    return frame.drop_duplicates("factor_name", keep="first").reset_index(drop=True)
