"""Contract metadata for judged governance factor pools.

This module is deliberately metadata-first. It does not run the state machine
or place orders; it normalizes factor-judge outputs into stable fields that the
alpha bundle and basket builder can consume.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd


ADMITTED_VERDICTS = {"promote_candidate", "watchlist"}


@dataclass(frozen=True)
class FactorPoolContract:
    factor_name: str
    raw_column: str
    module: str
    family: str
    role: str
    verdict: str
    score: float
    near_relative_key: str
    source_run_id: str = ""


def load_factor_pool_contract(summary_path: str | Path) -> pd.DataFrame:
    """Load a fast-factor summary and attach stable module/family/role fields."""
    path = Path(summary_path)
    data = pd.read_csv(path)
    if data.empty:
        return _empty_contract()
    rows = []
    for _, row in data.iterrows():
        verdict = str(row.get("verdict", "")).strip()
        factor_name = str(row.get("factor_name", "")).strip()
        module = normalize_factor_module(row.get("module", ""), factor_name=factor_name)
        family = infer_factor_family(factor_name=factor_name, module=module)
        role = infer_state_machine_role(module=module, family=family, factor_name=factor_name)
        score = _score_row(row)
        rows.append(
            {
                "factor_name": factor_name,
                "raw_column": str(row.get("raw_column", "") or ""),
                "module": module,
                "family": family,
                "role": role,
                "verdict": verdict,
                "admitted": verdict in ADMITTED_VERDICTS,
                "score": score,
                "near_relative_key": near_relative_key(factor_name=factor_name, module=module, family=family),
                "source_run_id": str(row.get("run_id", "") or ""),
                "best_horizon_days": row.get("best_horizon_days", pd.NA),
                "best_ic_ir": row.get("best_ic_ir", pd.NA),
                "best_rank_ic_mean": row.get("best_rank_ic_mean", pd.NA),
                "best_cost_adjusted_top_bottom_spread": row.get("best_cost_adjusted_top_bottom_spread", pd.NA),
                "avg_turnover_mean": row.get("avg_turnover_mean", pd.NA),
                "reason": row.get("reason", ""),
            }
        )
    return pd.DataFrame(rows).sort_values(["admitted", "score", "factor_name"], ascending=[False, False, True])


def normalize_factor_module(module, *, factor_name: str = "") -> str:
    text = str(module or "").strip().lower()
    name = str(factor_name or "").lower()
    if text.startswith("blend:") or text.startswith("spread:") or text.startswith("interaction:") or text.startswith("conditional:"):
        return text
    if "macd" in text or "macd" in name:
        return "macd"
    if "rsi" in text or "rsi" in name:
        return "rsi"
    if "turtle" in text or "breakout" in text or "breakout" in name:
        return "breakout"
    if "momentum" in text or "ret_" in name:
        return "momentum"
    if "reversal" in text or "rev_" in name:
        return "reversal"
    if "volatility" in text or "vol_" in name or "downvol" in name:
        return "volatility"
    if "liquidity" in text or "turnover" in name or "amihud" in name:
        return "liquidity"
    if "large_order" in text or "order" in text:
        return "orderflow"
    if any(token in text or token in name for token in ("valuation", "value", "pe_", "pb_")):
        return "valuation"
    if "growth" in text:
        return "growth"
    if "profitability" in text or "roe" in name:
        return "profitability"
    if "cashflow" in text:
        return "cashflow"
    if "sentiment" in text or "social" in text or "supply_chain" in text:
        return "alternative"
    if "barra" in text or "size" in text or "beta" in text:
        return "barra_style"
    return text or "unknown"


def infer_factor_family(*, factor_name: str, module: str) -> str:
    name = str(factor_name).lower()
    if "__" in name:
        parts = name.split("__", 1)[1]
        tokens = [re.sub(r"_[0-9]+$", "", item) for item in parts.split("__")]
        return "+".join(dict.fromkeys(tokens[:2]))
    for token in (
        "macd",
        "rsi",
        "turtle",
        "momentum",
        "reversal",
        "volatility",
        "liquidity",
        "orderflow",
        "valuation",
        "growth",
        "profitability",
        "cashflow",
        "sentiment",
        "barra",
        "size",
    ):
        if token in name or token in str(module).lower():
            return token
    return str(module or "unknown")


def infer_state_machine_role(*, module: str, family: str, factor_name: str) -> str:
    text = f"{module}|{family}|{factor_name}".lower()
    if any(token in text for token in ("volatility", "risk", "drawdown", "beta", "low_noise")):
        return "risk_override"
    if any(token in text for token in ("liquidity", "turnover", "amihud", "amount", "volume")):
        return "liquidity_filter"
    if any(token in text for token in ("macd", "rsi", "turtle", "breakout", "reversal")):
        return "timing_filter"
    if any(token in text for token in ("trend", "momentum", "hold", "quality")):
        return "hold_validation"
    if any(token in text for token in ("exhaust", "downside", "sell", "collapse")):
        return "sell_trigger"
    return "entry_alpha"


def near_relative_key(*, factor_name: str, module: str, family: str) -> str:
    name = str(factor_name).lower()
    name = re.sub(r"candidate_(grid|matrix)_", "", name)
    name = re.sub(r"_(5|10|20|30|40|55|60|90|120|180|240)(d)?", "_n", name)
    name = re.sub(r"rank_(mean|spread|product|gate_hi|gate_lo|ratio)", "rank_op", name)
    return f"{module}:{family}:{name[:80]}"


def build_role_coverage_report(contract: pd.DataFrame) -> pd.DataFrame:
    if contract is None or contract.empty:
        return pd.DataFrame(columns=["role", "admitted_count", "module_count", "family_count"])
    data = contract.copy()
    if "admitted" not in data.columns:
        data["admitted"] = data.get("verdict", "").astype(str).isin(ADMITTED_VERDICTS)
    admitted = data[data["admitted"].fillna(False).astype(bool)]
    if admitted.empty:
        return pd.DataFrame(columns=["role", "admitted_count", "module_count", "family_count"])
    return (
        admitted.groupby("role", dropna=False)
        .agg(
            admitted_count=("factor_name", "count"),
            module_count=("module", "nunique"),
            family_count=("family", "nunique"),
        )
        .reset_index()
        .sort_values(["admitted_count", "role"], ascending=[False, True])
    )


def _score_row(row) -> float:
    values = []
    for column in ("best_cost_adjusted_top_bottom_spread", "best_ic_ir", "best_rank_ic_mean"):
        value = pd.to_numeric(row.get(column), errors="coerce")
        if pd.notna(value):
            values.append(float(value))
    return float(sum(values)) if values else 0.0


def _empty_contract() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "factor_name",
            "raw_column",
            "module",
            "family",
            "role",
            "verdict",
            "admitted",
            "score",
            "near_relative_key",
            "source_run_id",
        ]
    )
