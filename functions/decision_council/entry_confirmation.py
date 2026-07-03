"""Entry confirmation gates for governance buy candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    ENABLE_GOVERNANCE_ENTRY_CONFIRMATION,
    GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BEAR,
    GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BULL,
    GOVERNANCE_ENTRY_ALPHA_THRESHOLD_NEUTRAL,
    GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WARNING,
    GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WEAK,
    GOVERNANCE_ENTRY_MAX_VOLATILITY_MULTIPLIER,
    GOVERNANCE_ENTRY_MATRIX_STRONG_THRESHOLD,
    GOVERNANCE_ENTRY_MATRIX_STARTER_1,
    GOVERNANCE_ENTRY_MATRIX_STARTER_2,
    GOVERNANCE_ENTRY_MATRIX_STRONG_STARTER,
    GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD,
    GOVERNANCE_ENTRY_TIMING_STARTER_1,
    GOVERNANCE_ENTRY_TIMING_STARTER_2,
    GOVERNANCE_ALPHA_QUALITY_STARTER_1,
    GOVERNANCE_ALPHA_QUALITY_STARTER_2,
    GOVERNANCE_ALPHA_QUALITY_STRONG_STARTER,
    GOVERNANCE_BASKET_ENTRY_ENABLED,
    GOVERNANCE_BASKET_ENTRY_MAX_DOWNTREND,
    GOVERNANCE_BASKET_ENTRY_MAX_EXHAUSTION,
    GOVERNANCE_BASKET_ENTRY_MIN_ALPHA_QUALITY_PCT,
    GOVERNANCE_BASKET_ENTRY_MIN_FINAL_SCORE_PCT,
    GOVERNANCE_BASKET_ENTRY_MIN_FOLLOW_THROUGH,
    GOVERNANCE_BASKET_ENTRY_MIN_MATRIX_SCORE_PCT,
    GOVERNANCE_BASKET_ENTRY_MIN_TIMING_PCT,
    GOVERNANCE_DIVERSIFY_ALPHA_QUALITY_MIN,
    GOVERNANCE_DIVERSIFY_DOWNTREND_MAX,
    GOVERNANCE_DIVERSIFY_ENTRY_MATRIX_MIN,
    GOVERNANCE_DIVERSIFY_ENTRY_TIMING_MIN,
    GOVERNANCE_DIVERSIFY_EXHAUSTION_MAX,
    GOVERNANCE_DIVERSIFY_FOLLOW_THROUGH_MIN,
    GOVERNANCE_EXHAUSTION_BUY_MAX,
    GOVERNANCE_EXHAUSTION_BLOCK_THRESHOLD,
    GOVERNANCE_FOLLOW_THROUGH_STARTER_2,
    GOVERNANCE_FOLLOW_THROUGH_STRONG,
    GOVERNANCE_SURGE_ALPHA_MIN,
    GOVERNANCE_SURGE_CAPTURE_THRESHOLD,
    GOVERNANCE_ENTRY_MIN_AMOUNT_MA_RATIO,
    GOVERNANCE_ENTRY_MIN_CLOSE_TO_MA20,
    GOVERNANCE_ENTRY_MIN_CONFIDENCE,
    GOVERNANCE_ENTRY_MIN_EXPECTED_RETURN_AFTER_COST,
    GOVERNANCE_ENTRY_MIN_ORDERFLOW_CONFIRMATIONS,
    GOVERNANCE_ENTRY_MIN_RET_20,
)


ORDERFLOW_COLUMNS = (
    "score_orderflow_amount_shock",
    "score_orderflow_close_drive",
    "score_orderflow_accumulation",
    "score_orderflow_efficiency",
    "score_eod_close_strength",
)

REVERSAL_COLUMNS = (
    "score_mean_reversion",
    "score_rsi_reversal",
    "score_kdj_oversold_cross",
    "score_low_volume_pullback",
    "score_consecutive_decline_rebound",
)

BREAKOUT_COLUMNS = (
    "score_price_volume_breakout",
    "score_turtle_breakout",
    "score_limit_up_follow",
    "score_ma_break",
)

TREND_COLUMNS = (
    "score_mom_lowvol",
    "score_macd_trend",
    "score_macd_cross",
    "score_ma_cross",
    "ret_20",
)


def apply_entry_confirmation(
    candidates: pd.DataFrame,
    *,
    risk_level: str = "normal",
    structural_regime_level: str = "bull",
    entry_calibrator=None,
    confirmation_mode: str = "full",
    capital_usage_mode: str = "allow_cash",
) -> pd.DataFrame:
    """Annotate candidates with entry confirmation diagnostics."""
    data = candidates.copy()
    if data.empty:
        data["entry_confirmed"] = pd.Series(dtype=bool)
        data["entry_quality_score"] = pd.Series(dtype=float)
        data["alpha_quality_score"] = pd.Series(dtype=float)
        data["surge_capture_score"] = pd.Series(dtype=float)
        data["follow_through_score"] = pd.Series(dtype=float)
        data["exhaustion_score"] = pd.Series(dtype=float)
        data["entry_success_probability"] = pd.Series(dtype=float)
        data["entry_size_tier"] = pd.Series(dtype=object)
        data["planned_entry_lots"] = pd.Series(dtype=float)
        data["downtrend_decay_score"] = pd.Series(dtype=float)
        data["post_entry_failure_score"] = pd.Series(dtype=float)
        data["surge_buy_flag"] = pd.Series(dtype=bool)
        data["entry_block_reason"] = pd.Series(dtype=object)
        return data

    threshold = _alpha_threshold(risk_level, structural_regime_level)
    alpha_percentile = _numeric_series(data, "alpha_percentile", default=0.0).fillna(0.0)
    expected_return = _numeric_series(data, "expected_return_5d", default=0.0).fillna(0.0)
    confidence = _numeric_series(data, "aggregate_confidence", default=1.0).fillna(1.0)
    ret_20 = _numeric_series(data, "ret_20", default=None)
    ret_5 = _numeric_series(data, "ret_5", default=None)
    close_to_ma20 = _numeric_series(data, "close_to_ma20", default=None)
    amount = _numeric_series(data, "amount", default=0.0).fillna(0.0)
    amount_ma20 = _numeric_series(data, "amount_ma20", default=None).fillna(amount)
    volatility = _numeric_series(data, "volatility_20", default=None)
    median_volatility = float(volatility.dropna().median()) if not volatility.dropna().empty else 0.0
    volatility_limit = median_volatility * float(GOVERNANCE_ENTRY_MAX_VOLATILITY_MULTIPLIER) if median_volatility > 0 else None

    orderflow_confirm_count = pd.Series(0, index=data.index, dtype=int)
    available_orderflow_columns = [column for column in ORDERFLOW_COLUMNS if column in data.columns]
    for column in ORDERFLOW_COLUMNS:
        if column in data.columns:
            orderflow_confirm_count += (pd.to_numeric(data[column], errors="coerce").fillna(0.0) > 0.0).astype(int)
    orderflow_confirmation = (
        pd.Series(True, index=data.index)
        if not available_orderflow_columns
        else orderflow_confirm_count >= int(GOVERNANCE_ENTRY_MIN_ORDERFLOW_CONFIRMATIONS)
    )
    data["orderflow_candidate_score"] = _module_score(data, ORDERFLOW_COLUMNS)
    data["reversal_entry_score"] = _module_score(data, REVERSAL_COLUMNS)
    data["breakout_gate_score"] = _module_score(data, BREAKOUT_COLUMNS)
    data["trend_hold_score"] = _module_score(data, TREND_COLUMNS)
    data["module_candidate_score"] = (
        0.60 * data["orderflow_candidate_score"]
        + 0.20 * data["breakout_gate_score"]
        + 0.20 * alpha_percentile.clip(0.0, 1.0)
    )
    data["module_entry_score"] = (
        0.50 * data["reversal_entry_score"]
        + 0.30 * data["breakout_gate_score"]
        + 0.20 * data["orderflow_candidate_score"]
    )
    data["module_hold_score"] = (
        0.50 * data["trend_hold_score"]
        + 0.30 * data["orderflow_candidate_score"]
        + 0.20 * alpha_percentile.clip(0.0, 1.0)
    )
    data["orderflow_candidate_pass"] = (
        data["orderflow_candidate_score"].ge(0.50)
        | data["orderflow_candidate_score"].rank(pct=True).ge(0.60)
        | orderflow_confirmation.astype(bool)
    )
    data["reversal_confirm_pass"] = (
        data["reversal_entry_score"].ge(0.45)
        | data["reversal_entry_score"].rank(pct=True).ge(0.70)
    )
    data["breakout_gate_pass"] = (
        data["breakout_gate_score"].ge(0.50)
        | data["breakout_gate_score"].rank(pct=True).ge(0.80)
    )
    is_rebound = str(structural_regime_level).lower() == "rebound"
    rebound_follow_through = _rebound_follow_through(
        ret_5=ret_5,
        ret_20=ret_20,
        close_to_ma20=close_to_ma20,
        orderflow_confirm_count=orderflow_confirm_count,
        expected_return=expected_return,
    )

    checks = {
        "alpha_percentile": alpha_percentile >= threshold,
        "expected_return_after_cost": expected_return >= float(GOVERNANCE_ENTRY_MIN_EXPECTED_RETURN_AFTER_COST),
        "confidence": confidence >= float(GOVERNANCE_ENTRY_MIN_CONFIDENCE),
        "price_confirmation": close_to_ma20.isna()
        | (
            (close_to_ma20 >= float(GOVERNANCE_ENTRY_MIN_CLOSE_TO_MA20))
            & (ret_20.isna() | (ret_20 >= float(GOVERNANCE_ENTRY_MIN_RET_20)))
        ),
        "liquidity_confirmation": amount_ma20.le(0.0)
        | (amount >= amount_ma20 * float(GOVERNANCE_ENTRY_MIN_AMOUNT_MA_RATIO)),
        "volatility_confirmation": pd.Series(True, index=data.index)
        if volatility_limit is None
        else volatility.isna() | (volatility <= volatility_limit),
        "orderflow_confirmation": orderflow_confirmation,
        "rebound_follow_through": rebound_follow_through if is_rebound else pd.Series(True, index=data.index),
    }
    alpha_confirm = checks["alpha_percentile"] & checks["expected_return_after_cost"] & checks["confidence"]
    market_confirm = checks["price_confirmation"] & checks["volatility_confirmation"]
    flow_confirm = checks["liquidity_confirmation"] & checks["orderflow_confirmation"]
    confirmed = pd.Series(True, index=data.index)
    for mask in checks.values():
        confirmed &= mask.astype(bool)
    if str(risk_level).lower() in {"high", "crisis"}:
        confirmed &= False
    if not ENABLE_GOVERNANCE_ENTRY_CONFIRMATION:
        confirmed = pd.Series(True, index=data.index)

    data["entry_alpha_threshold"] = float(threshold)
    data["entry_orderflow_confirm_count"] = orderflow_confirm_count
    data["alpha_confirm"] = alpha_confirm.astype(bool)
    data["market_confirm"] = market_confirm.astype(bool)
    data["flow_confirm"] = flow_confirm.astype(bool)
    data["rebound_follow_through"] = rebound_follow_through.astype(bool)
    data["calibrated_win_prob_5d"] = _calibrated_win_probability(
        alpha_percentile=alpha_percentile,
        expected_return=expected_return,
        confidence=confidence,
        orderflow_confirm_count=orderflow_confirm_count,
        market_confirm=market_confirm,
    )
    if entry_calibrator is not None:
        data = entry_calibrator.score_candidates(
            data,
            regime_name=structural_regime_level,
            horizon_days=5,
        )
        data = entry_calibrator.score_candidates(
            data,
            regime_name=structural_regime_level,
            horizon_days=10,
        )
        if "p_win_5d_calibrated" in data.columns:
            data["calibrated_win_prob_5d"] = pd.to_numeric(
                data["p_win_5d_calibrated"], errors="coerce"
            ).fillna(data["calibrated_win_prob_5d"])
    else:
        data["p_win_5d_calibrated"] = data["calibrated_win_prob_5d"]
        data["p_win_5d_wilson_lower"] = (data["p_win_5d_calibrated"] - 0.08).clip(0.30, 0.58)
        data["avg_win_5d_by_bucket"] = 0.018
        data["avg_loss_5d_by_bucket"] = 0.017
        data["expected_edge_5d"] = (
            data["p_win_5d_calibrated"] * data["avg_win_5d_by_bucket"]
            - (1.0 - data["p_win_5d_calibrated"]) * data["avg_loss_5d_by_bucket"]
        )
        data["conservative_expected_edge_5d"] = (
            data["p_win_5d_wilson_lower"] * data["avg_win_5d_by_bucket"]
            - (1.0 - data["p_win_5d_wilson_lower"]) * data["avg_loss_5d_by_bucket"]
        )
        volatility_floor = volatility.fillna(0.02).clip(lower=0.005)
        data["edge_to_risk_5d"] = data["expected_edge_5d"] / volatility_floor
        data["conservative_edge_to_risk_5d"] = data["conservative_expected_edge_5d"] / volatility_floor
        data["entry_calibration_sample_count_5d"] = 0
        data["entry_calibration_trust_5d"] = 0.0
        data["p_win_10d_calibrated"] = data["p_win_5d_calibrated"]
        data["p_win_10d_wilson_lower"] = data["p_win_5d_wilson_lower"]
        data["avg_win_10d_by_bucket"] = 0.036
        data["avg_loss_10d_by_bucket"] = 0.034
        data["expected_edge_10d"] = (
            data["p_win_10d_calibrated"] * data["avg_win_10d_by_bucket"]
            - (1.0 - data["p_win_10d_calibrated"]) * data["avg_loss_10d_by_bucket"]
        )
        data["conservative_expected_edge_10d"] = (
            data["p_win_10d_wilson_lower"] * data["avg_win_10d_by_bucket"]
            - (1.0 - data["p_win_10d_wilson_lower"]) * data["avg_loss_10d_by_bucket"]
        )
        data["edge_to_risk_10d"] = data["expected_edge_10d"] / volatility_floor
        data["conservative_edge_to_risk_10d"] = data["conservative_expected_edge_10d"] / volatility_floor
        data["entry_calibration_sample_count_10d"] = 0
        data["entry_calibration_trust_10d"] = 0.0
    edge_to_risk_10d = pd.to_numeric(data.get("edge_to_risk_10d"), errors="coerce").fillna(float("-inf"))
    expected_edge_10d = pd.to_numeric(data.get("expected_edge_10d"), errors="coerce").fillna(float("-inf"))
    conservative_edge_10d = pd.to_numeric(data.get("conservative_expected_edge_10d"), errors="coerce").fillna(expected_edge_10d)
    conservative_edge_to_risk_10d = pd.to_numeric(data.get("conservative_edge_to_risk_10d"), errors="coerce").fillna(edge_to_risk_10d)
    p_win_10d = pd.to_numeric(data.get("p_win_10d_calibrated"), errors="coerce").fillna(0.0)
    p_win_10d_lower = pd.to_numeric(data.get("p_win_10d_wilson_lower"), errors="coerce").fillna((p_win_10d - 0.08).clip(0.30, 0.58))
    calibration_trust_10d = pd.to_numeric(data.get("entry_calibration_trust_10d"), errors="coerce").fillna(0.0).clip(0.0, 1.0)
    data["entry_edge_rank_pct"] = edge_to_risk_10d.rank(pct=True).fillna(0.0)
    data["entry_conservative_edge_rank_pct"] = conservative_edge_to_risk_10d.rank(pct=True).fillna(0.0)
    data["entry_evidence_grade"] = _entry_evidence_grade(
        p_win_lower=p_win_10d_lower,
        conservative_edge=conservative_edge_10d,
        calibration_trust=calibration_trust_10d,
    )
    risk_blocks_new_buy = pd.Series(str(risk_level).lower() in {"high", "crisis"}, index=data.index)
    hard_veto = (
        ~checks["liquidity_confirmation"].astype(bool)
        | ~checks["volatility_confirmation"].astype(bool)
        | risk_blocks_new_buy
    )
    soft_confirm = alpha_confirm.astype(bool) & market_confirm.astype(bool) & flow_confirm.astype(bool)
    edge_confirm = (
        alpha_percentile.ge(max(float(threshold) - 0.10, 0.50))
        & data["orderflow_candidate_pass"].astype(bool)
        & data["reversal_confirm_pass"].astype(bool)
        & market_confirm.astype(bool)
    )
    role_confirm = (
        data["orderflow_candidate_pass"].astype(bool)
        & data["reversal_confirm_pass"].astype(bool)
        & (
            data["breakout_gate_pass"].astype(bool)
            | data["trend_hold_score"].ge(0.55)
        )
        & market_confirm.astype(bool)
        & checks["liquidity_confirmation"].astype(bool)
    )
    mode = str(confirmation_mode or "full").strip().lower()
    if is_rebound:
        rebound_evidence = (
            rebound_follow_through.astype(bool)
            & data["entry_conservative_edge_rank_pct"].ge(0.70)
        )
        soft_confirm &= rebound_follow_through.astype(bool)
        edge_confirm &= rebound_evidence
        role_confirm &= rebound_follow_through.astype(bool)
    confirmed = (~hard_veto.astype(bool)) & (role_confirm | edge_confirm)
    if mode in {"fixed_percentile_only", "no_probability", "no_probability_edge"}:
        confirmed = (
            ~hard_veto.astype(bool)
            & checks["alpha_percentile"].astype(bool)
            & market_confirm.astype(bool)
            & flow_confirm.astype(bool)
        )
        if is_rebound:
            confirmed &= rebound_follow_through.astype(bool)
    data["starter_position_allowed"] = confirmed & (
        data["orderflow_candidate_pass"].astype(bool)
        & data["reversal_confirm_pass"].astype(bool)
    )
    data["confirmed_add_position_allowed"] = confirmed & (
        data["breakout_gate_pass"].astype(bool)
        & data["orderflow_candidate_pass"].astype(bool)
        & data["reversal_confirm_pass"].astype(bool)
    )
    data["entry_quality_score"] = _quality_score(
        alpha_percentile=alpha_percentile,
        expected_return=expected_return,
        confidence=confidence,
        orderflow_confirm_count=orderflow_confirm_count,
    )
    data["entry_quality_score"] = (
        0.45 * data["entry_quality_score"]
        + 0.30 * data["module_entry_score"]
        + 0.15 * data["module_candidate_score"]
        + 0.10 * data["module_hold_score"]
    ).clip(0.0, 1.0)
    expected_return_rank = expected_return.rank(pct=True).fillna(0.0)
    data["entry_alpha_score"] = (
        0.60 * alpha_percentile.clip(0.0, 1.0)
        + 0.25 * data["module_candidate_score"]
        + 0.15 * expected_return_rank
    ).clip(0.0, 1.0)
    data["alpha_quality_score"] = (
        0.30 * data["reversal_entry_score"]
        + 0.25 * data["trend_hold_score"]
        + 0.20 * data["orderflow_candidate_score"]
        + 0.10 * data["breakout_gate_score"]
        + 0.10 * checks["liquidity_confirmation"].astype(float)
        + 0.05 * expected_return_rank
    ).clip(0.0, 1.0)
    data["trend_stability_score"] = (
        0.55 * data["trend_hold_score"]
        + 0.25 * data["breakout_gate_score"]
        + 0.20 * expected_return_rank
    ).clip(0.0, 1.0)
    data["volume_health_score"] = (
        0.65 * data["orderflow_candidate_score"]
        + 0.20 * data["module_candidate_score"]
        + 0.15 * checks["liquidity_confirmation"].astype(float)
    ).clip(0.0, 1.0)
    drawdown_raw = close_to_ma20.fillna(0.0).clip(lower=-0.20, upper=0.15)
    data["drawdown_quality_score"] = (1.0 - (drawdown_raw.abs() / 0.20)).clip(0.0, 1.0)
    ret_3 = _numeric_series(data, "ret_3", default=None).fillna(ret_5.fillna(0.0))
    ret_10 = _numeric_series(data, "ret_10", default=None).fillna(ret_20.fillna(0.0))
    ret_3_rank = ret_3.rank(pct=True).fillna(0.0)
    close_strength = _numeric_series(data, "score_eod_close_strength", default=0.0).fillna(0.0).rank(pct=True).fillna(0.0)
    volume_expansion_score = (amount / amount_ma20.replace(0.0, pd.NA)).replace([float("inf"), float("-inf")], pd.NA)
    volume_expansion_score = ((volume_expansion_score.fillna(1.0) - 1.0) / 1.5).clip(0.0, 1.0)
    data["volume_expansion_score"] = volume_expansion_score
    data["close_near_high_score"] = close_strength.clip(0.0, 1.0)
    amount_ratio = (amount / amount_ma20.replace(0.0, pd.NA)).replace([float("inf"), float("-inf")], pd.NA).fillna(1.0)
    data["surge_capture_score"] = (
        0.30 * ret_3_rank
        + 0.25 * data["volume_expansion_score"]
        + 0.20 * data["close_near_high_score"]
        + 0.15 * data["breakout_gate_score"]
        + 0.10 * data["orderflow_candidate_score"]
    ).clip(0.0, 1.0)
    overextension_score = (
        0.35 * ((ret_3.fillna(0.0) - 0.04) / 0.08).clip(0.0, 1.0)
        + 0.35 * ((ret_5.fillna(0.0) - 0.07) / 0.12).clip(0.0, 1.0)
        + 0.30 * ((ret_10.fillna(0.0) - 0.10) / 0.18).clip(0.0, 1.0)
    ).clip(0.0, 1.0)
    volume_climax_score = ((amount_ratio - 1.8) / 2.2).clip(0.0, 1.0)
    close_weakness_score = (1.0 - data["close_near_high_score"]).clip(0.0, 1.0)
    distance_from_ma20_score = ((close_to_ma20.fillna(0.0) - 0.08) / 0.20).clip(0.0, 1.0)
    consecutive_up_proxy = (
        ret_3.fillna(0.0).gt(0.035).astype(float) * 0.50
        + ret_5.fillna(0.0).gt(0.065).astype(float) * 0.50
    ).clip(0.0, 1.0)
    gap_or_limit_afterrun_score = (
        data["breakout_gate_score"].ge(0.80).astype(float)
        * overextension_score.ge(0.50).astype(float)
    )
    data["exhaustion_score"] = (
        0.25 * overextension_score
        + 0.20 * volume_climax_score
        + 0.20 * close_weakness_score
        + 0.15 * distance_from_ma20_score
        + 0.10 * consecutive_up_proxy
        + 0.10 * gap_or_limit_afterrun_score
    ).clip(0.0, 1.0)
    volume_hold_score = (1.0 - (amount_ratio - 1.0).abs() / 1.5).clip(0.0, 1.0)
    pullback_not_break_score = (
        close_to_ma20.fillna(0.0).ge(-0.02).astype(float) * 0.55
        + ret_5.fillna(0.0).ge(-0.015).astype(float) * 0.45
    ).clip(0.0, 1.0)
    orderflow_persistence = (
        0.60 * data["orderflow_candidate_score"]
        + 0.40 * (orderflow_confirm_count / max(len(ORDERFLOW_COLUMNS), 1)).clip(0.0, 1.0)
    ).clip(0.0, 1.0)
    volatility_noise_score = (
        (volatility / max(median_volatility, 1e-12) - 1.0).clip(0.0, 2.0) / 2.0
        if median_volatility > 0
        else pd.Series(0.0, index=data.index)
    ).clip(0.0, 1.0)
    data["volatility_noise_score"] = volatility_noise_score
    volatility_compression_after_surge = (1.0 - volatility_noise_score).clip(0.0, 1.0)
    data["follow_through_score"] = (
        0.30 * data["close_near_high_score"]
        + 0.25 * volume_hold_score
        + 0.20 * pullback_not_break_score
        + 0.15 * orderflow_persistence
        + 0.10 * volatility_compression_after_surge
    ).clip(0.0, 1.0)
    ma_decay_score = (
        close_to_ma20.fillna(0.0).lt(-0.03).astype(float) * 0.55
        + ret_20.fillna(0.0).lt(-0.04).astype(float) * 0.45
    ).clip(0.0, 1.0)
    weak_rebound_score = (
        ret_5.fillna(0.0).lt(0.01).astype(float) * 0.60
        + ret_10.fillna(0.0).lt(0.00).astype(float) * 0.40
    ).clip(0.0, 1.0)
    volume_shrink_rebound_score = (
        ret_5.fillna(0.0).gt(0.0).astype(float)
        * (amount / amount_ma20.replace(0.0, pd.NA)).fillna(1.0).lt(0.85).astype(float)
    )
    lower_high_low_proxy = (
        ret_5.fillna(0.0).lt(0.0).astype(float) * 0.50
        + ret_20.fillna(0.0).lt(0.0).astype(float) * 0.50
    ).clip(0.0, 1.0)
    data["downtrend_decay_score"] = (
        0.30 * ma_decay_score
        + 0.25 * lower_high_low_proxy
        + 0.20 * weak_rebound_score
        + 0.15 * volume_shrink_rebound_score
        + 0.10 * drawdown_raw.lt(-0.06).astype(float)
    ).clip(0.0, 1.0)
    data["post_entry_failure_score"] = 0.0
    data["entry_timing_score"] = (
        0.25 * data["reversal_entry_score"]
        + 0.25 * data["drawdown_quality_score"]
        + 0.20 * data["volume_health_score"]
        + 0.15 * data["trend_stability_score"]
        + 0.15 * (1.0 - data["volatility_noise_score"])
    ).clip(0.0, 1.0)
    data["entry_liquidity_score"] = data["volume_health_score"].clip(0.0, 1.0)
    logit = (
        -1.20
        + 1.40 * data["alpha_quality_score"]
        + 1.10 * data["entry_timing_score"]
        + 0.70 * data["entry_liquidity_score"]
        + 0.45 * data["surge_capture_score"]
        - 1.20 * data["downtrend_decay_score"]
        - 1.00 * data["volatility_noise_score"]
        - 0.80 * data["exhaustion_score"]
    )
    data["entry_success_probability"] = pd.Series(
        1.0 / (1.0 + np.exp(-logit.clip(lower=-20.0, upper=20.0))),
        index=data.index,
    ).clip(0.0, 1.0)
    data["entry_matrix_score"] = (
        0.40 * data["alpha_quality_score"]
        + 0.30 * data["entry_timing_score"]
        + 0.15 * data["entry_liquidity_score"]
        + 0.10 * data["follow_through_score"]
        + 0.05 * data["surge_capture_score"]
        - 0.25 * data["exhaustion_score"]
        - 0.20 * data["downtrend_decay_score"]
    ).clip(0.0, 1.0)
    data["entry_matrix_percentile"] = data["entry_matrix_score"].rank(pct=True).fillna(0.0)
    data["alpha_quality_percentile"] = data["alpha_quality_score"].rank(pct=True).fillna(0.0)
    data["entry_timing_percentile"] = data["entry_timing_score"].rank(pct=True).fillna(0.0)
    data["follow_through_percentile"] = data["follow_through_score"].rank(pct=True).fillna(0.0)
    data["exhaustion_percentile"] = data["exhaustion_score"].rank(pct=True).fillna(0.0)
    data["downtrend_percentile"] = data["downtrend_decay_score"].rank(pct=True).fillna(0.0)
    tail_risk_proxy = (
        0.45 * data["volatility_noise_score"]
        + 0.30 * data["downtrend_decay_score"]
        + 0.25 * data["exhaustion_score"]
    ).clip(0.0, 1.0)
    data["tail_risk_proxy"] = tail_risk_proxy
    data["empirical_distribution_score"] = (
        0.30 * data["entry_matrix_percentile"]
        + 0.20 * data["alpha_quality_percentile"]
        + 0.20 * data["entry_timing_percentile"]
        + 0.15 * data["follow_through_percentile"]
        + 0.15 * (1.0 - tail_risk_proxy.rank(pct=True).fillna(1.0))
    ).clip(0.0, 1.0)
    data["final_entry_score"] = (
        0.70 * data["entry_matrix_score"]
        + 0.20 * data["empirical_distribution_score"]
        + 0.10 * (1.0 - data["downtrend_decay_score"])
    ).clip(0.0, 1.0)
    data["final_entry_score_percentile"] = data["final_entry_score"].rank(pct=True).fillna(0.0)
    starter_1 = (
        data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_STARTER_1))
        & data["alpha_quality_score"].ge(float(GOVERNANCE_ALPHA_QUALITY_STARTER_1))
        & data["entry_timing_score"].ge(float(GOVERNANCE_ENTRY_TIMING_STARTER_1))
        & data["exhaustion_score"].lt(float(GOVERNANCE_EXHAUSTION_BUY_MAX))
        & data["downtrend_decay_score"].lt(0.55)
    )
    starter_2 = (
        data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_STARTER_2))
        & data["alpha_quality_score"].ge(float(GOVERNANCE_ALPHA_QUALITY_STARTER_2))
        & data["entry_timing_score"].ge(float(GOVERNANCE_ENTRY_TIMING_STARTER_2))
        & data["follow_through_score"].ge(float(GOVERNANCE_FOLLOW_THROUGH_STARTER_2))
        & data["exhaustion_score"].lt(0.55)
        & data["downtrend_decay_score"].lt(0.50)
    )
    strong_starter = (
        data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_STRONG_STARTER))
        & data["alpha_quality_score"].ge(float(GOVERNANCE_ALPHA_QUALITY_STRONG_STARTER))
        & data["surge_capture_score"].ge(float(GOVERNANCE_SURGE_CAPTURE_THRESHOLD))
        & data["follow_through_score"].ge(float(GOVERNANCE_FOLLOW_THROUGH_STRONG))
        & data["exhaustion_score"].lt(0.50)
        & data["downtrend_decay_score"].lt(0.45)
        & data["volume_expansion_score"].ge(0.60)
        & data["close_near_high_score"].ge(0.60)
    )
    paper_watch = (
        data["entry_matrix_score"].ge(0.58)
        & (
            data["exhaustion_score"].ge(float(GOVERNANCE_EXHAUSTION_BLOCK_THRESHOLD))
            | data["downtrend_decay_score"].ge(0.60)
        )
    )
    diversify_1 = (
        data["entry_matrix_score"].ge(float(GOVERNANCE_DIVERSIFY_ENTRY_MATRIX_MIN))
        & data["alpha_quality_score"].ge(float(GOVERNANCE_DIVERSIFY_ALPHA_QUALITY_MIN))
        & data["entry_timing_score"].ge(float(GOVERNANCE_DIVERSIFY_ENTRY_TIMING_MIN))
        & data["follow_through_score"].ge(float(GOVERNANCE_DIVERSIFY_FOLLOW_THROUGH_MIN))
        & data["exhaustion_score"].lt(float(GOVERNANCE_DIVERSIFY_EXHAUSTION_MAX))
        & data["downtrend_decay_score"].lt(float(GOVERNANCE_DIVERSIFY_DOWNTREND_MAX))
    )
    role_pass = data.get("state_machine_role_pass", pd.Series(True, index=data.index)).fillna(False).astype(bool)
    basket_entry = (
        bool(GOVERNANCE_BASKET_ENTRY_ENABLED)
        & role_pass
        & data["final_entry_score_percentile"].ge(float(GOVERNANCE_BASKET_ENTRY_MIN_FINAL_SCORE_PCT))
        & data["entry_matrix_percentile"].ge(float(GOVERNANCE_BASKET_ENTRY_MIN_MATRIX_SCORE_PCT))
        & data["alpha_quality_percentile"].ge(float(GOVERNANCE_BASKET_ENTRY_MIN_ALPHA_QUALITY_PCT))
        & data["entry_timing_percentile"].ge(float(GOVERNANCE_BASKET_ENTRY_MIN_TIMING_PCT))
        & data["follow_through_score"].ge(float(GOVERNANCE_BASKET_ENTRY_MIN_FOLLOW_THROUGH))
        & data["exhaustion_score"].lt(float(GOVERNANCE_BASKET_ENTRY_MAX_EXHAUSTION))
        & data["downtrend_decay_score"].lt(float(GOVERNANCE_BASKET_ENTRY_MAX_DOWNTREND))
        & checks["liquidity_confirmation"].astype(bool)
        & checks["volatility_confirmation"].astype(bool)
        & ~risk_blocks_new_buy.astype(bool)
    )
    data["entry_size_tier"] = (
        pd.Series("blocked", index=data.index)
        .mask(data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD)), "watching")
        .mask(basket_entry, "basket_1_lot")
        .mask(diversify_1, "diversify_1_lot")
        .mask(starter_1, "starter_1_lot")
        .mask(starter_2, "starter_2_lot")
        .mask(strong_starter, "starter_strong")
        .mask(paper_watch, "paper_watch")
    )
    data["planned_entry_lots"] = (
        pd.Series(0.0, index=data.index)
        .mask(basket_entry, 1.0)
        .mask(diversify_1, 1.0)
        .mask(starter_1, 1.0)
        .mask(starter_2, 2.0)
        .mask(strong_starter, 3.0)
    )
    data["entry_quality_tier"] = pd.Series("blocked", index=data.index).mask(
        data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD)),
        "watch",
    ).mask(
        data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_STRONG_THRESHOLD)),
        "direct",
    )
    data["candidate_pool_flag"] = data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD))
    data["watchlist_flag"] = data["entry_quality_tier"].eq("watch")
    data["direct_buy_flag"] = data["entry_quality_tier"].eq("direct")
    data["entry_confirmation_mode"] = mode
    strong_matrix_confirm = (
        data["direct_buy_flag"].astype(bool)
        & data["exhaustion_score"].lt(float(GOVERNANCE_EXHAUSTION_BUY_MAX))
        & data["downtrend_decay_score"].lt(0.60)
        & ~hard_veto.astype(bool)
        & checks["liquidity_confirmation"].astype(bool)
        & checks["volatility_confirmation"].astype(bool)
    )
    surge_matrix_confirm = (
        data["alpha_quality_score"].ge(float(GOVERNANCE_SURGE_ALPHA_MIN))
        & data["surge_capture_score"].ge(float(GOVERNANCE_SURGE_CAPTURE_THRESHOLD))
        & data["follow_through_score"].ge(0.55)
        & data["exhaustion_score"].lt(0.70)
        & data["close_near_high_score"].ge(0.65)
        & data["volume_expansion_score"].ge(0.60)
        & data["downtrend_decay_score"].lt(0.50)
        & ~hard_veto.astype(bool)
        & checks["liquidity_confirmation"].astype(bool)
    )
    data["surge_buy_flag"] = surge_matrix_confirm.astype(bool)
    force_deploy = str(capital_usage_mode or "allow_cash").strip().lower() == "force_deploy"
    matrix_confirm = (
        (
            starter_1.astype(bool)
            | starter_2.astype(bool)
            | strong_starter.astype(bool)
            | basket_entry.astype(bool)
            | strong_matrix_confirm.astype(bool)
            | surge_matrix_confirm.astype(bool)
            | (force_deploy and diversify_1.astype(bool))
        )
        & ~hard_veto.astype(bool)
        & checks["liquidity_confirmation"].astype(bool)
    )
    confirmed = matrix_confirm.astype(bool)
    if mode in {"factor_only", "matrix_only", "stop_mode"}:
        confirmed = (
            data["entry_matrix_score"].ge(float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD))
            & data["exhaustion_score"].lt(float(GOVERNANCE_EXHAUSTION_BLOCK_THRESHOLD))
            & checks["liquidity_confirmation"].astype(bool)
            & ~risk_blocks_new_buy.astype(bool)
        )
    if not ENABLE_GOVERNANCE_ENTRY_CONFIRMATION:
        confirmed = pd.Series(True, index=data.index)
    data["entry_confirmed"] = confirmed.astype(bool)
    data["entry_block_reason"] = [
        _first_block_reason(row_index, checks, risk_level, data)
        if not bool(data.at[row_index, "entry_confirmed"])
        else "confirmed"
        for row_index in data.index
    ]
    return data


def _numeric_series(data: pd.DataFrame, column: str, *, default: float | None) -> pd.Series:
    if column in data.columns:
        return pd.to_numeric(data[column], errors="coerce")
    return pd.Series(default, index=data.index, dtype="float64")


def _module_score(data: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    """Rank-normalize heterogeneous factor columns into a 0-1 module score."""
    available = [column for column in columns if column in data.columns]
    if not available:
        return pd.Series(0.0, index=data.index, dtype="float64")
    ranked = []
    for column in available:
        values = pd.to_numeric(data[column], errors="coerce")
        if values.notna().sum() <= 1:
            ranked.append(pd.Series(0.0, index=data.index, dtype="float64"))
            continue
        ranked.append(values.rank(pct=True).fillna(0.0).clip(0.0, 1.0))
    return pd.concat(ranked, axis=1).mean(axis=1).fillna(0.0).clip(0.0, 1.0)


def _alpha_threshold(risk_level: str, structural_regime_level: str) -> float:
    if str(risk_level).lower() == "warning":
        return float(GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WARNING)
    regime = str(structural_regime_level).lower()
    if regime in {"bull", "rebound"}:
        return float(GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BULL)
    if regime == "neutral":
        return float(GOVERNANCE_ENTRY_ALPHA_THRESHOLD_NEUTRAL)
    if regime == "weak":
        return float(GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WEAK)
    return float(GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BEAR)


def _quality_score(
    *,
    alpha_percentile: pd.Series,
    expected_return: pd.Series,
    confidence: pd.Series,
    orderflow_confirm_count: pd.Series,
) -> pd.Series:
    orderflow_score = (orderflow_confirm_count / max(len(ORDERFLOW_COLUMNS), 1)).clip(0.0, 1.0)
    expected_score = (expected_return / 0.02).clip(lower=0.0, upper=1.0)
    return (
        0.45 * alpha_percentile.clip(0.0, 1.0)
        + 0.20 * expected_score
        + 0.20 * confidence.clip(0.0, 1.0)
        + 0.15 * orderflow_score
    )


def _calibrated_win_probability(
    *,
    alpha_percentile: pd.Series,
    expected_return: pd.Series,
    confidence: pd.Series,
    orderflow_confirm_count: pd.Series,
    market_confirm: pd.Series,
) -> pd.Series:
    orderflow_score = (orderflow_confirm_count / max(len(ORDERFLOW_COLUMNS), 1)).clip(0.0, 1.0)
    expected_score = (expected_return / 0.03).clip(lower=-1.0, upper=1.0)
    raw = (
        0.46
        + 0.12 * (alpha_percentile.fillna(0.5).clip(0.0, 1.0) - 0.5)
        + 0.08 * expected_score.fillna(0.0)
        + 0.05 * (confidence.fillna(0.5).clip(0.0, 1.0) - 0.5)
        + 0.04 * (orderflow_score.fillna(0.0) - 0.5)
        + 0.03 * market_confirm.fillna(False).astype(float)
    )
    return raw.clip(0.35, 0.65)


def _rebound_follow_through(
    *,
    ret_5: pd.Series,
    ret_20: pd.Series,
    close_to_ma20: pd.Series,
    orderflow_confirm_count: pd.Series,
    expected_return: pd.Series,
) -> pd.Series:
    ret5 = pd.to_numeric(ret_5, errors="coerce")
    ret20 = pd.to_numeric(ret_20, errors="coerce")
    ma20_gap = pd.to_numeric(close_to_ma20, errors="coerce")
    expected = pd.to_numeric(expected_return, errors="coerce").fillna(0.0)
    flow_count = pd.to_numeric(orderflow_confirm_count, errors="coerce").fillna(0)
    not_failed_bounce = ret5.isna() | (ret5 >= -0.015)
    not_overextended = ma20_gap.isna() | (ma20_gap <= 0.12)
    medium_term_alive = ret20.isna() | (ret20 >= -0.02)
    flow_or_edge = (flow_count >= 2) | (expected >= 0.002)
    return (not_failed_bounce & not_overextended & medium_term_alive & flow_or_edge).fillna(False)


def _entry_evidence_grade(
    *,
    p_win_lower: pd.Series,
    conservative_edge: pd.Series,
    calibration_trust: pd.Series,
) -> pd.Series:
    strong = p_win_lower.ge(0.50) & conservative_edge.gt(0.0) & calibration_trust.ge(0.50)
    usable = p_win_lower.ge(0.45) & conservative_edge.ge(-0.001)
    starter = p_win_lower.ge(0.40) | conservative_edge.ge(-0.002)
    return pd.Series("blocked", index=p_win_lower.index).mask(starter, "starter").mask(usable, "usable").mask(strong, "strong")


def _first_block_reason(row_index, checks: dict[str, pd.Series], risk_level: str, data: pd.DataFrame | None = None) -> str:
    if str(risk_level).lower() in {"high", "crisis"}:
        return "risk_level_blocks_new_buy"
    if data is not None:
        for reason, column in (
            ("orderflow_candidate", "orderflow_candidate_pass"),
            ("reversal_confirm", "reversal_confirm_pass"),
            ("breakout_gate", "breakout_gate_pass"),
        ):
            if column in data.columns:
                try:
                    if not bool(data.at[row_index, column]):
                        return reason
                except Exception:
                    continue
    for name, mask in checks.items():
        try:
            if not bool(mask.loc[row_index]):
                return name
        except Exception:
            if not bool(mask):
                return name
    return "unknown"
