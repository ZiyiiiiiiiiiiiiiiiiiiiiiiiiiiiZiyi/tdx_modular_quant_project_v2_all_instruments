"""PIT diagnostic products for the post-drawdown governance review.

The builders in this module are deliberately read-only.  They turn existing
decision ledgers into explicit evidence products; they do not mutate orders,
positions, forecasts, or deployment authority.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Iterable

import pandas as pd


EXIT_AUTHORITY_CONTRACT = "scap_exit_authority_v2"
EXIT_DELAY_CONTRACT = "scap_exit_delay_counterfactual_v1"
MARKET_STATE_CONTRACT = "scap_market_state_vector_v1"
RECOVERY_EPISODE_CONTRACT = "scap_recovery_episode_v1"
ENTRY_QUALITY_CONTRACT = "scap_entry_quality_authority_v1"
BENCHMARK_BUNDLE_CONTRACT = "scap_benchmark_bundle_v1"


EXIT_AUTHORITY_COLUMNS = [
    "observation_id", "decision_id", "decision_date", "symbol",
    "signal_type", "detected", "detected_score", "first_detected_date",
    "consecutive_count", "confirmation_required", "paper_active",
    "policy_enabled", "control_enabled", "authority_active",
    "selected_exit_reason", "selected_for_exit", "veto_reasons",
    "superseded_by", "intended_exit_fraction", "earliest_execution_date",
    "sell_order_id", "sell_fill_id", "sell_execution_date", "sell_execution_price",
    "evidence_as_of_date", "data_quality_state", "authority_contract_version",
]

EXIT_DELAY_COLUMNS = [
    "observation_id", "decision_id", "symbol", "signal_type",
    "first_detected_date", "first_authority_date", "selected_exit_date",
    "sell_execution_date", "authority_delay_sessions",
    "execution_delay_sessions", "detection_close", "authority_close",
    "execution_price", "forward_return_5d", "forward_return_10d",
    "forward_return_20d", "actual_exit_return_from_detection",
    "counterfactual_status", "right_censored", "contract_version",
]

MARKET_STATE_COLUMNS = [
    "contract_id", "decision_id", "decision_date", "safety_proxy_id",
    "fast_shock_state", "structural_state", "recovery_state",
    "fast_state_streak", "structural_state_streak", "recovery_streak",
    "return_5d", "return_20d", "drawdown_5d", "drawdown_20d",
    "underwater_from_peak", "liquidity_stress", "hard_safety_cap",
    "base_deployment_target", "structural_multiplier", "structural_cap",
    "recovery_cap", "sizing_attainable_cap", "effective_deployment_cap",
    "actual_exposure", "authority_mode", "data_quality_state",
    "blocked_reasons", "evidence_as_of_date",
]

RECOVERY_EPISODE_COLUMNS = [
    "episode_id", "start_date", "end_date", "start_state", "end_state",
    "days_in_episode", "minimum_effective_cap", "maximum_underwater",
    "open_reached", "authority_mode", "contract_version",
]

ENTRY_QUALITY_COLUMNS = [
    "evidence_id", "proposal_id", "decision_id", "decision_date", "symbol",
    "action_type", "authority_tier", "calibration_state",
    "effective_sample_size", "coverage_evidence_authorized",
    "full_universe_oos_status", "decision_return", "decision_return_basis",
    "requested_lots", "maximum_lots", "maximum_notional",
    "robust_net_profit_amount", "authority_penalty_amount",
    "scenario_risk_penalty_amount", "model_uncertainty_amount",
    "risk_adjusted_ce_amount", "economic_order_pass", "trade_mode",
    "selected_by_plan", "authority_reasons", "blocked_reasons",
    "evidence_as_of_date", "authority_mode", "contract_version",
]

BENCHMARK_BUNDLE_COLUMNS = [
    "contract_id", "decision_date", "benchmark_id", "role",
    "constituent_rule", "weighting_rule", "rebalance_rule", "daily_return",
    "net_value", "return_valid", "coverage_ratio", "authority",
    "data_quality_state", "degraded_reasons", "evidence_as_of_date",
]


def _empty(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _bool(value, default: bool = False) -> bool:
    if value is None or pd.isna(value):
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _number(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _tokens(value) -> tuple[str, ...]:
    if value is None or (not isinstance(value, (tuple, list, set)) and pd.isna(value)):
        return ()
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip().strip("()[]")
    if not text:
        return ()
    separator = "|" if "|" in text else ","
    return tuple(
        token.strip().strip("'\"")
        for token in text.split(separator)
        if token.strip().strip("'\"")
    )


def _stable_id(*parts: object, prefix: str) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def resolve_post_entry_failure_authority(
    *,
    signal_detected: bool,
    strategy_logic_version: str,
    control_mode: str,
    control_enabled: bool,
    authorized_reasons: Iterable[str] = (),
    selected_reason: str | None = None,
    configured_mode: str = "legacy",
) -> dict:
    """Resolve detection, policy, control, and selection without conflation.

    ``diagnostic`` and ``shadow`` never grant authority. ``trading`` does.
    ``legacy`` preserves the pre-remediation aggressive-profit-only rule.
    """
    mode = str(configured_mode or "legacy").strip().lower()
    if mode not in {"legacy", "diagnostic", "shadow", "trading"}:
        raise ValueError("post-entry-failure mode must be legacy/diagnostic/shadow/trading")
    mainline_v3 = str(strategy_logic_version or "").strip().lower().startswith("mainline_v3")
    legacy_policy = not (
        mainline_v3 and str(control_mode or "").strip().lower() != "aggressive_profit"
    )
    policy_enabled = bool(mode == "trading" or (mode == "legacy" and legacy_policy))
    authorized = set(str(item) for item in authorized_reasons)
    authority_active = bool(
        signal_detected
        and policy_enabled
        and control_enabled
        and "post_entry_failure_exit" in authorized
    )
    vetoes: list[str] = []
    if signal_detected and mode in {"diagnostic", "shadow"}:
        vetoes.append(f"configured_{mode}_only")
    elif signal_detected and not policy_enabled:
        vetoes.append("mainline_v3_non_aggressive_profit_observation_only")
    if signal_detected and not control_enabled:
        vetoes.append("control_disabled")
    selected = bool(authority_active and selected_reason == "post_entry_failure_exit")
    superseded = None
    if authority_active and selected_reason and not selected:
        superseded = str(selected_reason)
        vetoes.append(f"superseded_by:{selected_reason}")
    return {
        "detected": bool(signal_detected),
        "paper_active": bool(signal_detected),
        "policy_enabled": policy_enabled,
        "control_enabled": bool(control_enabled),
        "authority_active": authority_active,
        "selected_for_exit": selected,
        "superseded_by": superseded,
        "veto_reasons": tuple(vetoes),
        "mode": mode,
    }


_EXIT_SIGNALS = {
    "profit_hard_stop_exit": {
        "paper": "paper_profit_hard_stop_exit", "active": "profit_hard_stop_exit",
    },
    "profit_giveback_exit": {
        "paper": "paper_profit_giveback_exit", "active": "profit_giveback_exit",
    },
    "loss_containment_exit": {
        "paper": "paper_loss_containment_exit", "active": "loss_containment_exit",
        "count": "loss_containment_confirmation_count",
        "required": "loss_containment_confirmation_required",
    },
    "post_entry_failure_exit": {
        "paper": "post_entry_failure_paper_active", "active": "post_entry_failure_authority_active",
        "score": "post_entry_failure_score",
    },
    "thesis_failure_exit": {
        "paper": "paper_thesis_failure_exit", "active": "thesis_failure_exit",
        "count": "signal_failure_confirmation_count",
        "required": "signal_failure_confirmation_required",
    },
    "signal_failure_exit": {
        "paper": "paper_signal_failure_exit", "active": "signal_failure_exit",
        "count": "signal_failure_confirmation_count",
        "required": "signal_failure_confirmation_required",
    },
    "stale_time_exit": {
        "paper": "paper_stale_time_exit", "active": "stale_time_exit",
    },
}


def build_exit_signal_authority_ledger(
    position_state: pd.DataFrame,
    execution_ledger: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if position_state is None or position_state.empty:
        return _empty(EXIT_AUTHORITY_COLUMNS)
    state = position_state.copy()
    state["decision_date"] = pd.to_datetime(
        state.get("decision_date", state.get("date")), errors="coerce"
    ).dt.normalize()
    state = state[state["decision_date"].notna()].copy()
    executions = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    if not executions.empty:
        executions["trade_date"] = pd.to_datetime(executions.get("trade_date"), errors="coerce").dt.normalize()
        executions = executions[
            executions.get("side", pd.Series("", index=executions.index)).astype(str).str.lower().eq("sell")
        ].copy()
    first_seen: dict[tuple[str, str], pd.Timestamp] = {}
    rows: list[dict] = []
    for row in state.sort_values(["decision_date", "symbol"]).to_dict("records"):
        decision_date = pd.Timestamp(row["decision_date"])
        decision_id = str(row.get("decision_id") or f"gov_{decision_date:%Y%m%d}")
        symbol = str(row.get("symbol") or "")
        triggered = set(_tokens(row.get("exit_triggered_reasons")))
        authorized = set(_tokens(row.get("exit_authorized_reasons")))
        vetoed = set(_tokens(row.get("exit_vetoed_reasons")))
        selected_reason = str(row.get("position_exit_reason") or "").strip()
        for signal_type, mapping in _EXIT_SIGNALS.items():
            paper_col = mapping["paper"]
            fallback_paper = (
                row.get("paper_post_entry_failure_exit")
                if signal_type == "post_entry_failure_exit"
                else False
            )
            paper = _bool(row.get(paper_col, fallback_paper)) or signal_type in triggered
            active = _bool(row.get(mapping["active"])) or signal_type in authorized
            selected = bool(selected_reason == signal_type)
            if not (paper or active or selected):
                continue
            key = (symbol, signal_type)
            first_seen.setdefault(key, decision_date)
            policy_enabled = _bool(row.get("post_entry_failure_policy_enabled"), True)
            control_enabled = active or signal_type not in vetoed
            veto_reasons = list(vetoed if signal_type in vetoed else ())
            if signal_type == "post_entry_failure_exit":
                control_enabled = _bool(row.get("post_entry_failure_control_enabled"), control_enabled)
                veto_reasons.extend(_tokens(row.get("post_entry_failure_authority_veto_reasons")))
            superseded_by = selected_reason if active and selected_reason and not selected else ""
            if superseded_by:
                veto_reasons.append(f"superseded_by:{superseded_by}")
            sell = pd.DataFrame()
            if not executions.empty:
                sell = executions[
                    executions.get("symbol", pd.Series("", index=executions.index)).astype(str).eq(symbol)
                    & (
                        executions.get("decision_id", pd.Series("", index=executions.index)).astype(str).eq(decision_id)
                        | executions.get("reason", pd.Series("", index=executions.index)).astype(str).eq(signal_type)
                        | executions.get("position_exit_reason", pd.Series("", index=executions.index)).astype(str).eq(signal_type)
                    )
                ].sort_values("trade_date")
            fill = sell.iloc[0] if not sell.empty else {}
            observation_id = _stable_id(decision_id, symbol, signal_type, prefix="exitobs")
            rows.append({
                "observation_id": observation_id,
                "decision_id": decision_id,
                "decision_date": decision_date,
                "symbol": symbol,
                "signal_type": signal_type,
                "detected": bool(paper),
                "detected_score": _number(row.get(mapping.get("score", "")), default=float("nan")),
                "first_detected_date": first_seen[key],
                "consecutive_count": int(_number(row.get(mapping.get("count", "")), 1 if paper else 0)),
                "confirmation_required": max(int(_number(row.get(mapping.get("required", "")), 1)), 1),
                "paper_active": bool(paper),
                "policy_enabled": bool(policy_enabled),
                "control_enabled": bool(control_enabled),
                "authority_active": bool(active),
                "selected_exit_reason": selected_reason,
                "selected_for_exit": selected,
                "veto_reasons": "|".join(dict.fromkeys(veto_reasons)),
                "superseded_by": superseded_by,
                "intended_exit_fraction": 1.0 if selected else 0.0,
                "earliest_execution_date": decision_date + pd.offsets.BDay(1) if selected else pd.NaT,
                "sell_order_id": fill.get("order_id", "") if isinstance(fill, pd.Series) else "",
                "sell_fill_id": fill.get("fill_id", "") if isinstance(fill, pd.Series) else "",
                "sell_execution_date": fill.get("trade_date", pd.NaT) if isinstance(fill, pd.Series) else pd.NaT,
                "sell_execution_price": _number(fill.get("price"), float("nan")) if isinstance(fill, pd.Series) else pd.NA,
                "evidence_as_of_date": decision_date,
                "data_quality_state": "complete" if "exit_triggered_reasons" in state.columns else "legacy_partial",
                "authority_contract_version": EXIT_AUTHORITY_CONTRACT,
            })
    return pd.DataFrame(rows, columns=EXIT_AUTHORITY_COLUMNS)


def build_exit_delay_counterfactual(
    authority_ledger: pd.DataFrame,
    price_frame: pd.DataFrame,
) -> pd.DataFrame:
    if authority_ledger is None or authority_ledger.empty:
        return _empty(EXIT_DELAY_COLUMNS)
    prices = price_frame.copy() if price_frame is not None else pd.DataFrame()
    close_col = "close_nominal" if "close_nominal" in prices.columns else "close"
    if prices.empty or close_col not in prices.columns:
        result = authority_ledger.loc[:, ["observation_id", "decision_id", "symbol", "signal_type", "first_detected_date"]].copy()
        for column in EXIT_DELAY_COLUMNS:
            if column not in result.columns:
                result[column] = pd.NA
        result["counterfactual_status"] = "price_history_unavailable"
        result["right_censored"] = True
        result["contract_version"] = EXIT_DELAY_CONTRACT
        return result[EXIT_DELAY_COLUMNS]
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.normalize()
    prices[close_col] = pd.to_numeric(prices[close_col], errors="coerce")
    paths = {
        str(symbol): frame.dropna(subset=["date", close_col]).sort_values("date").drop_duplicates("date")
        for symbol, frame in prices.groupby(prices["symbol"].astype(str), sort=False)
    }
    rows: list[dict] = []
    grouped = authority_ledger.sort_values("decision_date").groupby(["symbol", "signal_type"], sort=False)
    for (symbol, signal_type), group in grouped:
        detected = group[group["detected"].map(_bool)]
        if detected.empty:
            continue
        first = detected.iloc[0]
        detect_date = pd.Timestamp(first["decision_date"]).normalize()
        authority = group[group["authority_active"].map(_bool)]
        selected = group[group["selected_for_exit"].map(_bool)]
        authority_date = pd.Timestamp(authority.iloc[0]["decision_date"]).normalize() if not authority.empty else pd.NaT
        selected_date = pd.Timestamp(selected.iloc[0]["decision_date"]).normalize() if not selected.empty else pd.NaT
        execution_dates = pd.to_datetime(selected.get("sell_execution_date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
        execution_date = execution_dates.iloc[0].normalize() if not execution_dates.empty else pd.NaT
        path = paths.get(str(symbol), pd.DataFrame())
        post = path[path["date"] >= detect_date].reset_index(drop=True) if not path.empty else pd.DataFrame()
        detection_close = _number(post.iloc[0][close_col], float("nan")) if not post.empty else float("nan")
        def _session_distance(target) -> object:
            if pd.isna(target) or path.empty:
                return pd.NA
            return int(((path["date"] > detect_date) & (path["date"] <= target)).sum())
        def _forward(horizon: int) -> object:
            if len(post) <= horizon or not detection_close or pd.isna(detection_close):
                return pd.NA
            return float(post.iloc[horizon][close_col] / detection_close - 1.0)
        authority_close = pd.NA
        if pd.notna(authority_date) and not path.empty:
            match = path[path["date"] >= authority_date]
            if not match.empty:
                authority_close = float(match.iloc[0][close_col])
        execution_price = pd.to_numeric(
            selected.get("sell_execution_price", pd.Series(dtype=float)),
            errors="coerce",
        ).dropna()
        execution_price_value = float(execution_price.iloc[0]) if not execution_price.empty else pd.NA
        right_censored = len(post) <= 20
        status = "complete" if not right_censored else "right_censored"
        rows.append({
            "observation_id": first["observation_id"], "decision_id": first["decision_id"],
            "symbol": symbol, "signal_type": signal_type,
            "first_detected_date": detect_date, "first_authority_date": authority_date,
            "selected_exit_date": selected_date, "sell_execution_date": execution_date,
            "authority_delay_sessions": _session_distance(authority_date),
            "execution_delay_sessions": _session_distance(execution_date),
            "detection_close": detection_close, "authority_close": authority_close,
            "execution_price": execution_price_value,
            "forward_return_5d": _forward(5), "forward_return_10d": _forward(10),
            "forward_return_20d": _forward(20),
            "actual_exit_return_from_detection": (
                float(execution_price_value / detection_close - 1.0)
                if pd.notna(execution_price_value) and pd.notna(detection_close) and detection_close > 0
                else pd.NA
            ),
            "counterfactual_status": status, "right_censored": right_censored,
            "contract_version": EXIT_DELAY_CONTRACT,
        })
    return pd.DataFrame(rows, columns=EXIT_DELAY_COLUMNS)


def advance_market_recovery_state(
    previous_state: str,
    healthy_streak: int,
    *,
    fast_state: str,
    hard_freeze_active: bool,
    return_5d: float | None,
    return_20d: float | None,
    confirmation_days: int = 3,
) -> tuple[str, int, bool, bool]:
    """Advance one causal recovery state using only information known today."""
    state = str(previous_state or "BLOCKED").strip().upper()
    fast = str(fast_state or "unknown").strip().lower()
    hard_block = bool(hard_freeze_active or fast in {"crisis", "extreme", "critical"})
    healthy = bool(
        not hard_block
        and fast in {"normal", "low", "medium"}
        and return_5d is not None and pd.notna(return_5d) and float(return_5d) >= 0.0
        and return_20d is not None and pd.notna(return_20d) and float(return_20d) >= -0.02
    )
    streak = int(healthy_streak) + 1 if healthy else 0
    if hard_block:
        return "BLOCKED", 0, hard_block, healthy
    if state == "BLOCKED":
        return "STABILIZING", streak, hard_block, healthy
    if healthy and streak >= max(int(confirmation_days), 1):
        state = {"STABILIZING": "STEP1", "STEP1": "STEP2", "STEP2": "OPEN"}.get(state, state)
        streak = 0
    elif not healthy and state != "STABILIZING":
        state = "STABILIZING"
    return state, streak, hard_block, healthy


def effective_market_deployment_cap(
    *,
    hard_safety_cap: float,
    base_deployment_target: float,
    structural_state: str,
    recovery_state: str,
    sizing_attainable_cap: float,
) -> dict:
    """Return each independent cap and their mathematical intersection."""
    structural_budgets = {
        "bull": 1.00, "neutral": 0.85, "weak": 0.65,
        "bear": 0.45, "crisis": 0.20, "unknown": 0.00,
    }
    fractions = {
        "BLOCKED": 0.0, "STABILIZING": 0.40,
        "STEP1": 0.65, "STEP2": 0.85, "OPEN": 1.0,
    }
    hard = min(max(float(hard_safety_cap), 0.0), 1.0)
    base = min(max(float(base_deployment_target), 0.0), 1.0)
    sizing = min(max(float(sizing_attainable_cap), 0.0), 1.0)
    structural_budget = structural_budgets.get(
        str(structural_state or "unknown").lower(), 0.0
    )
    structural_cap = min(base, structural_budget, hard)
    multiplier = structural_cap / base if base > 1e-12 else 0.0
    recovery_cap = hard * fractions.get(str(recovery_state).upper(), 0.0)
    return {
        "structural_multiplier": multiplier,
        "structural_cap": structural_cap,
        "recovery_cap": recovery_cap,
        "effective_deployment_cap": min(hard, structural_cap, recovery_cap, sizing),
    }


def build_market_state_ledger(
    daily_result: pd.DataFrame,
    safety_ledger: pd.DataFrame,
    *,
    authority_mode: str = "diagnostic",
    recovery_confirm_days: int = 3,
) -> pd.DataFrame:
    if safety_ledger is None or safety_ledger.empty:
        return _empty(MARKET_STATE_COLUMNS)
    mode = str(authority_mode or "diagnostic").strip().lower()
    if mode not in {"diagnostic", "shadow", "trading"}:
        raise ValueError("market recovery authority mode must be diagnostic/shadow/trading")
    safety = safety_ledger.copy()
    safety["decision_date"] = pd.to_datetime(safety.get("decision_date"), errors="coerce").dt.normalize()
    daily = daily_result.copy() if daily_result is not None else pd.DataFrame()
    if not daily.empty:
        daily["decision_date"] = pd.to_datetime(daily.get("date"), errors="coerce").dt.normalize()
        keep = [column for column in ("decision_date", "decision_id", "actual_exposure", "integer_attainable_exposure", "executable_target_exposure", "desired_exposure_target", "target_exposure") if column in daily.columns]
        safety = safety.merge(daily[keep].drop_duplicates("decision_date", keep="last"), on="decision_date", how="left", suffixes=("", "_daily"))
    rows: list[dict] = []
    prior_fast = prior_structural = None
    fast_streak = structural_streak = healthy_streak = 0
    recovery_state = "BLOCKED"
    for row in safety.sort_values("decision_date").to_dict("records"):
        date = pd.Timestamp(row["decision_date"])
        fast = str(row.get("risk_level") or "unknown").strip().lower()
        structural = str(row.get("structural_regime_level") or "unknown").strip().lower()
        fast_streak = fast_streak + 1 if fast == prior_fast else 1
        structural_streak = structural_streak + 1 if structural == prior_structural else 1
        prior_fast, prior_structural = fast, structural
        ret5 = _number(row.get("benchmark_return_5d"), float("nan"))
        ret20 = _number(row.get("benchmark_return_20d"), float("nan"))
        underwater = _number(row.get("benchmark_underwater_from_peak"), float("nan"))
        recovery_state, healthy_streak, hard_block, healthy = (
            advance_market_recovery_state(
                recovery_state,
                healthy_streak,
                fast_state=fast,
                hard_freeze_active=_bool(row.get("hard_freeze_active")),
                return_5d=ret5,
                return_20d=ret20,
                confirmation_days=recovery_confirm_days,
            )
        )
        hard_cap = min(max(_number(row.get("exposure_cap", row.get("safety_exposure_cap", 1.0)), 1.0), 0.0), 1.0)
        base_target = min(max(_number(row.get("desired_exposure_target", row.get("target_exposure", hard_cap)), hard_cap), 0.0), 1.0)
        sizing_cap = _number(row.get("integer_attainable_exposure", row.get("executable_target_exposure", hard_cap)), hard_cap)
        sizing_cap = min(max(sizing_cap, 0.0), 1.0)
        caps = effective_market_deployment_cap(
            hard_safety_cap=hard_cap,
            base_deployment_target=base_target,
            structural_state=structural,
            recovery_state=recovery_state,
            sizing_attainable_cap=sizing_cap,
        )
        missing = [name for name, value in (("return_5d", ret5), ("return_20d", ret20), ("underwater", underwater)) if pd.isna(value)]
        blocked = []
        if hard_block:
            blocked.append("hard_safety_block")
        if missing:
            blocked.append("missing_safety_proxy_history:" + ",".join(missing))
        rows.append({
            "contract_id": _stable_id(date.date(), row.get("proxy_symbol", ""), prefix="marketstate"),
            "decision_id": str(row.get("decision_id") or f"gov_{date:%Y%m%d}"),
            "decision_date": date, "safety_proxy_id": str(row.get("proxy_symbol") or ""),
            "fast_shock_state": fast, "structural_state": structural,
            "recovery_state": recovery_state, "fast_state_streak": fast_streak,
            "structural_state_streak": structural_streak, "recovery_streak": healthy_streak,
            "return_5d": ret5, "return_20d": ret20,
            "drawdown_5d": _number(row.get("benchmark_drawdown_5d"), float("nan")),
            "drawdown_20d": _number(row.get("benchmark_drawdown_20d"), float("nan")),
            "underwater_from_peak": underwater,
            "liquidity_stress": _number(row.get("market_liquidity_stress_ratio"), float("nan")),
            "hard_safety_cap": hard_cap, "base_deployment_target": base_target,
            "structural_multiplier": caps["structural_multiplier"],
            "structural_cap": caps["structural_cap"],
            "recovery_cap": caps["recovery_cap"], "sizing_attainable_cap": sizing_cap,
            "effective_deployment_cap": caps["effective_deployment_cap"],
            "actual_exposure": _number(row.get("actual_exposure", row.get("nominal_exposure", 0.0)), 0.0),
            "authority_mode": mode,
            "data_quality_state": "complete" if not missing else "partial",
            "blocked_reasons": "|".join(blocked), "evidence_as_of_date": date,
        })
    return pd.DataFrame(rows, columns=MARKET_STATE_COLUMNS)


def build_recovery_episode_ledger(market_state: pd.DataFrame) -> pd.DataFrame:
    if market_state is None or market_state.empty:
        return _empty(RECOVERY_EPISODE_COLUMNS)
    data = market_state.sort_values("decision_date").copy()
    # A persisted window can begin after the causal transition from the
    # implicit initial BLOCKED state to STABILIZING. Requiring an observed
    # BLOCKED row would silently discard that entire recovery episode.
    groups: list[pd.DataFrame] = []
    current_indexes: list[object] = []
    for index, row in data.iterrows():
        state = str(row.get("recovery_state") or "BLOCKED").upper()
        if not current_indexes and state != "OPEN":
            current_indexes = [index]
        elif current_indexes:
            current_indexes.append(index)
            if state == "OPEN":
                groups.append(data.loc[current_indexes].copy())
                current_indexes = []
    if current_indexes:
        groups.append(data.loc[current_indexes].copy())
    rows = []
    for number, group in enumerate(groups, start=1):
        start = pd.Timestamp(group.iloc[0]["decision_date"])
        end = pd.Timestamp(group.iloc[-1]["decision_date"])
        rows.append({
            "episode_id": f"recovery_{start:%Y%m%d}_{number:03d}",
            "start_date": start, "end_date": end,
            "start_state": str(group.iloc[0]["recovery_state"]),
            "end_state": str(group.iloc[-1]["recovery_state"]),
            "days_in_episode": len(group),
            "minimum_effective_cap": pd.to_numeric(group["effective_deployment_cap"], errors="coerce").min(),
            "maximum_underwater": pd.to_numeric(group["underwater_from_peak"], errors="coerce").max(),
            "open_reached": group["recovery_state"].astype(str).eq("OPEN").any(),
            "authority_mode": str(group.iloc[-1]["authority_mode"]),
            "contract_version": RECOVERY_EPISODE_CONTRACT,
        })
    return pd.DataFrame(rows, columns=RECOVERY_EPISODE_COLUMNS)


def build_entry_quality_authority(
    proposal_ledger: pd.DataFrame,
    daily_result: pd.DataFrame | None = None,
    *,
    authority_mode: str = "diagnostic",
) -> pd.DataFrame:
    if proposal_ledger is None or proposal_ledger.empty:
        return _empty(ENTRY_QUALITY_COLUMNS)
    mode = str(authority_mode or "diagnostic").strip().lower()
    if mode not in {"diagnostic", "shadow", "trading"}:
        raise ValueError("entry quality authority mode must be diagnostic/shadow/trading")
    proposals = proposal_ledger.copy()
    proposals["decision_date"] = pd.to_datetime(
        proposals.get("decision_date", proposals.get("decision_id", pd.Series(index=proposals.index, dtype=object)).astype(str).str.extract(r"(\d{8})")[0]),
        errors="coerce",
    ).dt.normalize()
    daily_penalties: dict[str, dict] = {}
    if daily_result is not None and not daily_result.empty and "decision_id" in daily_result.columns:
        wanted = [column for column in ("decision_id", "scenario_risk_penalty_amount", "model_uncertainty_amount") if column in daily_result.columns]
        daily_penalties = daily_result[wanted].drop_duplicates("decision_id", keep="last").set_index("decision_id").to_dict("index")
    rows = []
    for row in proposals.to_dict("records"):
        decision_id = str(row.get("decision_id") or "")
        action_type = str(row.get("action_type") or "")
        tier = str(row.get("authority_tier") or "D").upper()
        calibration = str(row.get("calibration_evidence_state") or "unavailable").lower()
        coverage = _bool(row.get("coverage_evidence_authorized"))
        oos_status = str(row.get("full_universe_oos_status") or "unavailable").lower()
        robust = _number(row.get("robust_net_profit_amount"))
        authority_penalty = max(_number(row.get("authority_penalty_amount")), 0.0)
        plan_penalty = daily_penalties.get(decision_id, {})
        scenario_penalty = max(_number(row.get("scenario_risk_penalty_amount", plan_penalty.get("scenario_risk_penalty_amount", 0.0))), 0.0)
        uncertainty = max(_number(row.get("model_uncertainty_amount", plan_penalty.get("model_uncertainty_amount", 0.0))), 0.0)
        # robust_net_profit is already net of lifecycle costs, but the proposal
        # contract carries authority penalty separately. Portfolio scenario
        # penalties are shown separately and subtracted once here.
        ce = robust - authority_penalty - scenario_penalty - uncertainty
        reasons: list[str] = []
        blocked: list[str] = []
        if action_type not in {"new_entry", "replacement_buy", "winner_add", "loser_add"}:
            trade_mode = "not_applicable"
        elif tier == "D" or ce <= 0.0 or not _bool(row.get("economic_order_pass"), True):
            trade_mode = "blocked"
            if tier == "D": blocked.append("tier_d_no_entry_authority")
            if ce <= 0.0: blocked.append("risk_adjusted_ce_non_positive")
            if not _bool(row.get("economic_order_pass"), True): blocked.append("economic_order_failed")
        elif tier == "C":
            if oos_status in {"pass", "eligible", "qualified"}:
                trade_mode = "degraded_exploration"
                reasons.append("tier_c_strict_pit_oos_qualified")
            else:
                trade_mode = "shadow_only"
                blocked.append("tier_c_full_universe_oos_unavailable")
        elif calibration in {"calibrated", "recovering"} and coverage:
            trade_mode = "normal"
            reasons.append("calibrated_coverage_evidence")
        else:
            trade_mode = "degraded_exploration"
            reasons.append("ab_authority_with_incomplete_distribution_coverage")
        proposal_id = str(row.get("proposal_id") or "")
        rows.append({
            "evidence_id": _stable_id(proposal_id, decision_id, prefix="entryevidence"),
            "proposal_id": proposal_id, "decision_id": decision_id,
            "decision_date": row.get("decision_date"), "symbol": str(row.get("symbol") or ""),
            "action_type": action_type, "authority_tier": tier,
            "calibration_state": calibration,
            "effective_sample_size": _number(row.get("calibration_effective_sample_size")),
            "coverage_evidence_authorized": coverage,
            "full_universe_oos_status": oos_status,
            "decision_return": _number(row.get("unit_capital_robust_return")),
            "decision_return_basis": str(row.get("decision_return_basis") or "legacy_unknown"),
            "requested_lots": int(_number(row.get("requested_lots"))),
            "maximum_lots": int(_number(row.get("requested_lots"))) if trade_mode not in {"blocked", "shadow_only", "not_applicable"} else 0,
            "maximum_notional": _number(row.get("market_notional_amount")) if trade_mode not in {"blocked", "shadow_only", "not_applicable"} else 0.0,
            "robust_net_profit_amount": robust, "authority_penalty_amount": authority_penalty,
            "scenario_risk_penalty_amount": scenario_penalty,
            "model_uncertainty_amount": uncertainty, "risk_adjusted_ce_amount": ce,
            "economic_order_pass": _bool(row.get("economic_order_pass"), True),
            "trade_mode": trade_mode, "selected_by_plan": _bool(row.get("selected_by_plan")),
            "authority_reasons": "|".join(reasons), "blocked_reasons": "|".join(blocked),
            "evidence_as_of_date": row.get("decision_date"), "authority_mode": mode,
            "contract_version": ENTRY_QUALITY_CONTRACT,
        })
    return pd.DataFrame(rows, columns=ENTRY_QUALITY_COLUMNS)


def build_benchmark_bundle(
    performance_benchmark: pd.DataFrame,
    safety_ledger: pd.DataFrame,
) -> pd.DataFrame:
    performance = performance_benchmark.copy() if performance_benchmark is not None else pd.DataFrame()
    safety = safety_ledger.copy() if safety_ledger is not None else pd.DataFrame()
    dates = pd.Index([])
    if not performance.empty:
        performance["decision_date"] = pd.to_datetime(performance.get("date"), errors="coerce").dt.normalize()
        scope = performance.get(
            "benchmark_scope", pd.Series("decision", index=performance.index)
        )
        performance = performance[scope.astype(str).eq("decision")]
        dates = dates.union(pd.Index(performance["decision_date"].dropna().unique()))
    if not safety.empty:
        safety["decision_date"] = pd.to_datetime(safety.get("decision_date"), errors="coerce").dt.normalize()
        dates = dates.union(pd.Index(safety["decision_date"].dropna().unique()))
    rows = []
    for date in sorted(pd.Timestamp(value) for value in dates):
        perf = performance[performance["decision_date"].eq(date)].tail(1)
        safety_row = safety[safety["decision_date"].eq(date)].tail(1)
        p = perf.iloc[0] if not perf.empty else {}
        s = safety_row.iloc[0] if not safety_row.empty else {}
        specs = [
            {
                "benchmark_id": p.get("benchmark_id", "performance_unavailable") if isinstance(p, pd.Series) else "performance_unavailable",
                "role": "performance_primary", "constituent_rule": p.get("benchmark_constituent_rule", "") if isinstance(p, pd.Series) else "",
                "weighting_rule": p.get("benchmark_weighting", "") if isinstance(p, pd.Series) else "",
                "rebalance_rule": "monthly_or_configured", "daily_return": p.get("benchmark_daily_return", pd.NA) if isinstance(p, pd.Series) else pd.NA,
                "net_value": p.get("benchmark_net_value", pd.NA) if isinstance(p, pd.Series) else pd.NA,
                "return_valid": _bool(p.get("benchmark_return_valid")) if isinstance(p, pd.Series) else False,
                "coverage_ratio": _number(p.get("benchmark_return_coverage")) if isinstance(p, pd.Series) else 0.0,
                "authority": "performance_attribution_only", "degraded_reasons": "" if not perf.empty else "performance_benchmark_unavailable",
            },
            {
                "benchmark_id": "opportunity_set_unavailable", "role": "opportunity_set",
                "constituent_rule": "requires_point_in_time_investable_universe", "weighting_rule": "not_computed",
                "rebalance_rule": "not_computed", "daily_return": pd.NA, "net_value": pd.NA,
                "return_valid": False, "coverage_ratio": 0.0, "authority": "diagnostic_only",
                "degraded_reasons": "pit_opportunity_set_benchmark_not_materialized",
            },
            {
                "benchmark_id": "style_matched_unavailable", "role": "style_matched",
                "constituent_rule": "requires_pit_style_exposure_matching", "weighting_rule": "not_computed",
                "rebalance_rule": "not_computed", "daily_return": pd.NA, "net_value": pd.NA,
                "return_valid": False, "coverage_ratio": 0.0, "authority": "diagnostic_only",
                "degraded_reasons": "pit_style_matched_benchmark_not_materialized",
            },
            {
                "benchmark_id": s.get("proxy_symbol", "safety_proxy_unavailable") if isinstance(s, pd.Series) else "safety_proxy_unavailable",
                "role": "safety_proxy", "constituent_rule": "fixed_configured_market_safety_proxy",
                "weighting_rule": "single_proxy", "rebalance_rule": "none",
                "daily_return": pd.NA, "net_value": pd.NA,
                "return_valid": bool(isinstance(s, pd.Series) and not _bool(s.get("degraded"))),
                "coverage_ratio": 1.0 if isinstance(s, pd.Series) and not _bool(s.get("degraded")) else 0.0,
                "authority": "hard_safety_input_only",
                "degraded_reasons": "" if isinstance(s, pd.Series) and not _bool(s.get("degraded")) else "safety_proxy_degraded_or_unavailable",
            },
        ]
        for spec in specs:
            rows.append({
                "contract_id": _stable_id(date.date(), spec["role"], spec["benchmark_id"], prefix="benchmark"),
                "decision_date": date, **spec,
                "data_quality_state": "complete" if spec["return_valid"] else "legacy_unavailable",
                "evidence_as_of_date": date,
            })
    return pd.DataFrame(rows, columns=BENCHMARK_BUNDLE_COLUMNS)
