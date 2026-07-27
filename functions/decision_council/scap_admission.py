"""Profile-aware research admission for SCAP-V1."""
from __future__ import annotations

import numpy as np
import pandas as pd


SCAP_ADMISSION_VERSION = "scap_admission_v2_opportunity_compatible"


def build_scap_admission_report(
    *,
    governance_summary: pd.DataFrame,
    cost_stress: pd.DataFrame,
    daily_result: pd.DataFrame,
    holdings_ledger: pd.DataFrame,
    initial_cash: float,
    profit_factor_threshold: float = 1.15,
    minimum_closed_trades: int = 30,
    minimum_trading_days: int = 504,
    minimum_positive_slice_share: float = 0.60,
    win_rate_path_threshold: float = 0.55,
    payoff_path_threshold: float = 1.30,
    structural_single_position_cap: float = 0.40,
) -> pd.DataFrame:
    """Build a small-account gate without using the institutional 25% veto."""
    if governance_summary is None or governance_summary.empty:
        return pd.DataFrame([{
            "evidence_status": "missing_governance_summary",
            "research_stage_eligible": False,
            "production_eligible": False,
            "scap_admission_version": SCAP_ADMISSION_VERSION,
        }])
    row = governance_summary.iloc[-1]
    runtime_identity = {
        name: row.get(name, "")
        for name in (
            "capital_profile_name",
            "objective_metric",
            "special_strategy_version",
            "scap_exit_stage",
            "scap_loss_stop",
            "runtime_identity_hash",
            "code_fingerprint",
            "runtime_identity_schema_version",
            "experiment_sample_role",
        )
    }
    final_net_value = _number(row.get("final_net_value"))
    total_return = _number(row.get("total_return"))
    profit_factor = _number(row.get("profit_factor"))
    closed_trades = int(_number(row.get("closed_trade_count"), 0.0))
    trading_days = int(_number(row.get("trading_days"), 0.0))
    win_rate = _number(row.get("closed_trade_win_rate"))
    payoff = _number(row.get("payoff_ratio"))
    terminal_net_profit = (
        (final_net_value - 1.0) * float(initial_cash)
        if np.isfinite(final_net_value)
        else total_return * float(initial_cash)
    )
    rolling_slices = _rolling_slice_returns(daily_result)
    positive_slice_share = (
        float((rolling_slices > 0.0).mean()) if not rolling_slices.empty else np.nan
    )
    opportunity_capacity = int(
        np.floor(max(trading_days, 0) * 5.0 / 20.0)
    )
    required_closed_trades = min(
        int(minimum_closed_trades), max(opportunity_capacity, 0)
    )
    regime_count = _regime_count(daily_result)
    stress_base = _stress_row(cost_stress, minimum_commission=5.0, market_multiplier=1.0)
    stress_worst = _stress_row(cost_stress, minimum_commission=5.0, market_multiplier=2.0)
    base_stress_profitable = bool(stress_base.get("scenario_profitable", False))
    worst_stress_pf = _number(stress_worst.get("profit_factor_after_cost"))
    latest_top1 = _latest_top1_weight(holdings_ledger)
    structural_concentration_pass = bool(
        not np.isfinite(latest_top1)
        or latest_top1 <= float(structural_single_position_cap) + 1e-12
    )
    profit_style_path = (
        "win_rate"
        if np.isfinite(win_rate) and win_rate >= float(win_rate_path_threshold)
        else (
            "right_tail"
            if np.isfinite(payoff) and payoff >= float(payoff_path_threshold)
            else "none"
        )
    )
    gates = {
        "terminal_net_profit_positive": bool(terminal_net_profit > 0.0),
        "profit_factor_pass": bool(np.isfinite(profit_factor) and profit_factor >= float(profit_factor_threshold)),
        "closed_trade_evidence_pass": (
            required_closed_trades >= int(minimum_closed_trades)
            and closed_trades >= required_closed_trades
        ),
        "history_length_pass": trading_days >= int(minimum_trading_days),
        "market_state_coverage_pass": regime_count >= 3,
        "positive_slice_share_pass": bool(
            len(rolling_slices) >= 4
            and np.isfinite(positive_slice_share)
            and positive_slice_share >= float(minimum_positive_slice_share)
        ),
        "base_cost_stress_pass": base_stress_profitable,
        "worst_cost_stress_pf_pass": bool(np.isfinite(worst_stress_pf) and worst_stress_pf >= 1.0),
        "structural_concentration_pass": structural_concentration_pass,
    }
    development_window = str(
        runtime_identity.get("experiment_sample_role", "")
    ).strip().lower() == "development_audit"
    research_eligible = all(gates.values()) and not development_window
    failed = [name for name, passed in gates.items() if not passed]
    if development_window:
        failed.append("development_window_not_final_oos")
    return pd.DataFrame([{
        "terminal_net_profit_after_cost": terminal_net_profit,
        "total_return": total_return,
        "profit_factor_after_cost": profit_factor,
        "closed_trade_count": closed_trades,
        "trading_days": trading_days,
        "market_state_count": regime_count,
        "rolling_slice_count": int(len(rolling_slices)),
        "positive_126d_slice_share": positive_slice_share,
        "slice_contract": "126_trading_day_window_63_day_step",
        "opportunity_capacity_20d_5_slots": opportunity_capacity,
        "required_closed_trade_evidence": required_closed_trades,
        "profit_style_path": profit_style_path,
        "profit_style_path_is_diagnostic_only": True,
        "closed_trade_win_rate": win_rate,
        "payoff_ratio": payoff,
        "minimum_commission_base": 5.0,
        "base_cost_stress_profitable": base_stress_profitable,
        "worst_cost_stress_profit_factor": worst_stress_pf,
        "latest_top1_account_weight": latest_top1,
        "institutional_25pct_gate_is_diagnostic_only": True,
        **gates,
        "failed_gate_count": len(failed),
        "failed_gates": "|".join(failed),
        "evidence_status": "research_gate_pass" if research_eligible else "research_gate_blocked",
        "research_stage_eligible": research_eligible,
        "prospective_paper_gate_pass": False,
        "production_eligible": False,
        "production_block_reason": (
            "development_window_not_final_oos"
            if development_window
            else "prospective_paper_run_not_yet_completed"
        ),
        "scap_admission_version": SCAP_ADMISSION_VERSION,
        **runtime_identity,
    }])


def _number(value, default=np.nan) -> float:
    try:
        result = float(value)
        return result if np.isfinite(result) else float(default)
    except Exception:
        return float(default)


def _rolling_slice_returns(
    daily: pd.DataFrame, *, window_days: int = 126, step_days: int = 63
) -> pd.Series:
    if daily is None or daily.empty or "date" not in daily.columns:
        return pd.Series(dtype=float)
    value_column = "account_net_value" if "account_net_value" in daily.columns else "nominal_nav"
    if value_column not in daily.columns:
        return pd.Series(dtype=float)
    data = daily[["date", value_column]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data[value_column] = pd.to_numeric(data[value_column], errors="coerce")
    data = data.dropna().sort_values("date")
    if data.empty:
        return pd.Series(dtype=float)
    values = data[value_column].reset_index(drop=True)
    returns = []
    for end in range(int(window_days) - 1, len(values), int(step_days)):
        start = end - int(window_days) + 1
        base = float(values.iloc[start])
        if base > 0.0:
            returns.append(float(values.iloc[end]) / base - 1.0)
    return pd.Series(returns, dtype=float)


def _regime_count(daily: pd.DataFrame) -> int:
    if daily is None or daily.empty:
        return 0
    column = "structural_regime_level" if "structural_regime_level" in daily.columns else "regime_name"
    if column not in daily.columns:
        return 0
    values = daily[column].dropna().astype(str)
    values = values[~values.str.lower().isin({"", "unknown", "nan"})]
    return int(values.nunique())


def _stress_row(stress: pd.DataFrame, *, minimum_commission: float, market_multiplier: float) -> dict:
    if stress is None or stress.empty:
        return {}
    selected = stress[
        pd.to_numeric(stress["minimum_commission"], errors="coerce").eq(float(minimum_commission))
        & pd.to_numeric(stress["market_cost_multiplier"], errors="coerce").eq(float(market_multiplier))
    ]
    return selected.iloc[-1].to_dict() if not selected.empty else {}


def _latest_top1_weight(holdings: pd.DataFrame) -> float:
    if holdings is None or holdings.empty or not {"date", "account_weight"}.issubset(holdings.columns):
        return np.nan
    data = holdings.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["account_weight"] = pd.to_numeric(data["account_weight"], errors="coerce")
    latest = data["date"].max()
    return _number(data.loc[data["date"].eq(latest), "account_weight"].max())
