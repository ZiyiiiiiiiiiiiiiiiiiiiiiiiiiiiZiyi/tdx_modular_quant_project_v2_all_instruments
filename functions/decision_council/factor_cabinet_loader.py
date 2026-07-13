"""Read-only state-machine inputs from a factor cabinet."""
from __future__ import annotations

from pathlib import Path
import json

import pandas as pd


def load_factor_cabinet(path: str | Path) -> pd.DataFrame:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    factors = payload.get("factors", [])
    return pd.DataFrame(factors)


def build_state_inputs_from_cabinet(scores: pd.DataFrame, cabinet: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-factor stock scores into state-machine role scores."""
    if scores is None or scores.empty or cabinet is None or cabinet.empty:
        return pd.DataFrame()
    data = scores.copy()
    factors = cabinet[["factor_name", "cabinet_role"]].dropna()
    long = data.melt(id_vars=[col for col in ("date", "symbol") if col in data.columns], value_vars=[f for f in factors["factor_name"] if f in data.columns], var_name="factor_name", value_name="factor_score")
    long = long.merge(factors, on="factor_name", how="inner")
    pivot = long.pivot_table(index=[col for col in ("date", "symbol") if col in long.columns], columns="cabinet_role", values="factor_score", aggfunc="mean").reset_index()
    rename = {
        "strict_entry_alpha": "strict_entry_alpha_score",
        "proxy_entry_alpha": "proxy_entry_alpha_score",
        "timing_filter": "timing_score",
        "risk_override": "risk_score",
        "liquidity_filter": "liquidity_score",
        "hold_validation": "hold_score",
    }
    pivot = pivot.rename(columns=rename)
    for column in ["strict_entry_alpha_score", "proxy_entry_alpha_score", "timing_score", "risk_score", "liquidity_score", "hold_score"]:
        if column not in pivot.columns:
            pivot[column] = pd.NA
    pivot["entry_alpha_score"] = (
        0.50 * pd.to_numeric(pivot["strict_entry_alpha_score"], errors="coerce").fillna(0.0)
        + 0.25 * pd.to_numeric(pivot["proxy_entry_alpha_score"], errors="coerce").fillna(0.0)
    )
    pivot["entry_source"] = pivot.apply(
        lambda row: "strict" if pd.notna(row.get("strict_entry_alpha_score")) else "proxy" if pd.notna(row.get("proxy_entry_alpha_score")) else "none",
        axis=1,
    )
    return pivot
