"""Phase-one rule alpha proposals derived from the real feature table."""
from __future__ import annotations

import pandas as pd
import numpy as np

from config import (
    ENABLE_BUY_QUALITY_FILTERS,
    BUY_FILTER_MAX_VOLATILITY_MULTIPLIER,
    BUY_FILTER_MIN_AMOUNT_MULTIPLIER,
    BUY_FILTER_MAX_DECLINE_20D,
    BUY_FILTER_MIN_RET_5D,
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
    GOVERNANCE_FACTOR_JUDGED_ALPHA_DIRECTIONS,
    GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS,
    GOVERNANCE_FACTOR_JUDGED_MIN_WEIGHT,
    GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE,
    GOVERNANCE_MIN_DAILY_AMOUNT,
    STRATEGY_MIN_SCORE_PERCENTILE,
)
from functions.decision_council.alpha import alpha_collapse_symbols, combine_alpha_proposals
from functions.decision_council.analytics import factor_module
from functions.investable_universe import active_index_members, load_index_constituents


MODEL_FEATURES = GOVERNANCE_ALPHA_MODEL_FEATURES

# Index constituents cache (loaded once)
_INDEX_CONSTITUENTS_CACHE: dict[str, set[str]] | None = None


def _load_index_constituents() -> dict[str, set[str]]:
    """Load index constituents and build a set of valid stock symbols per date."""
    global _INDEX_CONSTITUENTS_CACHE
    if _INDEX_CONSTITUENTS_CACHE is not None:
        return _INDEX_CONSTITUENTS_CACHE

    from config import PROCESSED_DIR
    constituent_path = PROCESSED_DIR / "index_constituents.parquet"
    if not constituent_path.exists():
        _INDEX_CONSTITUENTS_CACHE = {}
        return _INDEX_CONSTITUENTS_CACHE

    df = pd.read_parquet(constituent_path)
    if df.empty:
        _INDEX_CONSTITUENTS_CACHE = {}
        return _INDEX_CONSTITUENTS_CACHE

    all_symbols = set(df["symbol"].astype(str).unique())
    cache = {"all": all_symbols}
    if "index_code" in df.columns:
        grouped = df.groupby(df["index_code"].astype(str).str.zfill(6))["symbol"].apply(
            lambda s: set(s.astype(str))
        )
        cache.update(grouped.to_dict())
    _INDEX_CONSTITUENTS_CACHE = cache
    return _INDEX_CONSTITUENTS_CACHE


def _apply_index_pool_filter(candidates: pd.DataFrame) -> pd.DataFrame:
    """Filter stocks to only include index constituents + all ETFs.

    Keeps:
    - All ETFs (instrument_type == etf_fund)
    - Stocks that are in target index pools (沪深300/中证500/中证100/上证50/中证A500)
    """
    if candidates.empty:
        return candidates

    constituents = _load_index_constituents()
    if not constituents:
        # No constituent data, skip filter
        return candidates

    valid_symbols = constituents.get("all", set())
    if not valid_symbols:
        return candidates

    is_etf = candidates["instrument_type"].astype(str) == "etf_fund"
    is_index_stock = candidates["symbol"].astype(str).isin(valid_symbols)

    filtered = candidates[is_etf | is_index_stock].copy()

    return filtered


def _symbol_in_target_codes(index_pool_codes: str, target_index_codes: set[str]) -> bool:
    codes = {item.strip() for item in str(index_pool_codes).split(",") if item and item.strip()}
    return bool(codes & target_index_codes)


def _apply_index_pool_filter_registry(
    candidates: pd.DataFrame,
    *,
    target_index_codes: tuple[str, ...] = (),
    universe_mode: str = "index_pool_strict",
    require_constituents: bool = True,
    allow_fallback: bool = False,
) -> pd.DataFrame:
    """Apply registry-aware universe filtering for governance candidates."""
    if candidates.empty:
        return candidates
    if universe_mode == "blocked":
        return candidates.iloc[0:0].copy()
    if universe_mode in {"quality_fallback", "all_a_share_research"}:
        return candidates

    normalized_codes = tuple(str(code).zfill(6) for code in target_index_codes if str(code).strip())
    target_code_set = set(normalized_codes)

    if "index_pool_codes" in candidates.columns and target_code_set:
        is_etf = candidates["instrument_type"].astype(str) == "etf_fund"
        is_index_stock = candidates["index_pool_codes"].map(
            lambda value: _symbol_in_target_codes(value, target_code_set)
        )
        return candidates[is_etf | is_index_stock].copy()

    constituents = load_index_constituents()
    if constituents.empty:
        if require_constituents and not allow_fallback:
            raise ValueError(
                "Index constituents are required for governance universe filtering but unavailable."
            )
        return candidates

    as_of_date = pd.to_datetime(candidates.get("date"), errors="coerce").dropna()
    if as_of_date.empty:
        cached = _load_index_constituents()
        valid_symbols = set()
        for code in normalized_codes:
            valid_symbols.update(cached.get(code, set()))
    else:
        active = active_index_members(
            constituents,
            as_of_date=as_of_date.max(),
            index_codes=normalized_codes or None,
        )
        valid_symbols = set(active["symbol"].astype(str).unique())

    if not valid_symbols:
        if require_constituents and not allow_fallback:
            raise ValueError(
                f"No active constituents available for governance universe codes: {sorted(target_code_set)}"
            )
        return candidates

    is_etf = candidates["instrument_type"].astype(str) == "etf_fund"
    is_index_stock = candidates["symbol"].astype(str).isin(valid_symbols)
    return candidates[is_etf | is_index_stock].copy()


def _apply_buy_quality_filters(
    candidates: pd.DataFrame,
    min_amount_multiplier: float = BUY_FILTER_MIN_AMOUNT_MULTIPLIER,
    max_volatility_multiplier: float = BUY_FILTER_MAX_VOLATILITY_MULTIPLIER,
    max_decline_20d: float = BUY_FILTER_MAX_DECLINE_20D,
    min_ret_5d: float = BUY_FILTER_MIN_RET_5D,
) -> pd.DataFrame:
    """
    Apply quality filters to buy candidates to improve selection accuracy.
    
    Filters applied:
    1. Volatility filter: Exclude stocks with volatility > multiplier * median
    2. Amount filter: Require daily amount > multiplier * minimum
    3. Momentum filter: Exclude stocks in sharp decline
    
    Parameters
    ----------
    candidates : pd.DataFrame
        Candidate stocks with features
    min_amount_multiplier : float
        Minimum amount multiplier vs GOVERNANCE_MIN_DAILY_AMOUNT
    max_volatility_multiplier : float
        Maximum volatility multiplier vs median volatility
    max_decline_20d : float
        Maximum allowed 20-day decline (negative value)
    min_ret_5d : float
        Minimum 5-day return threshold (negative value)
    
    Returns
    -------
    pd.DataFrame : Filtered candidates
    """
    if candidates.empty:
        return candidates
    
    filtered = candidates.copy()
    initial_count = len(filtered)
    
    # 1. Volatility filter: Exclude extremely volatile stocks
    if "volatility_20" in filtered.columns:
        vol = pd.to_numeric(filtered["volatility_20"], errors="coerce")
        vol_median = vol.median()
        if pd.notna(vol_median) and vol_median > 0:
            vol_threshold = vol_median * max_volatility_multiplier
            vol_mask = vol <= vol_threshold
            filtered = filtered[vol_mask | vol.isna()]  # Keep NaN for now
    
    # 2. Amount filter: Require higher liquidity
    if "amount" in filtered.columns and "amount_ma20" in filtered.columns:
        amount = pd.to_numeric(filtered["amount"], errors="coerce").fillna(0.0)
        amount_ma20 = pd.to_numeric(filtered["amount_ma20"], errors="coerce").fillna(amount)
        min_amount = float(GOVERNANCE_MIN_DAILY_AMOUNT) * min_amount_multiplier
        amount_mask = (amount >= min_amount) & (amount_ma20 >= min_amount)
        filtered = filtered[amount_mask]
    
    # 3. Momentum filter: Exclude stocks in sharp decline
    # Check for ret_20 (20-day return) if available
    if "ret_20" in filtered.columns:
        ret_20 = pd.to_numeric(filtered["ret_20"], errors="coerce")
        momentum_mask = ret_20 >= max_decline_20d
        filtered = filtered[momentum_mask | ret_20.isna()]  # Keep NaN
    
    # 4. Short-term momentum: Exclude recent sharp decline
    if "ret_5" in filtered.columns:
        ret_5 = pd.to_numeric(filtered["ret_5"], errors="coerce")
        short_mask = ret_5 >= min_ret_5d
        filtered = filtered[short_mask | ret_5.isna()]  # Keep NaN
    
    # Log filtering results
    final_count = len(filtered)
    if initial_count > 0:
        filter_ratio = final_count / initial_count
        # Only log if significant filtering occurred
        if filter_ratio < 0.8:
            pass  # Could add logging here if needed
    
    return filtered


def build_rule_alpha_proposals(
    daily_features: pd.DataFrame,
    *,
    reputation_weights: dict[str, float] | None = None,
    model_names=GOVERNANCE_ALPHA_MODELS,
    factor_judged: bool = False,
    runtime_context=None,
) -> pd.DataFrame:
    """Build deterministic proposal rows without pretending they are trained ML outputs."""
    reputation_weights = reputation_weights or {}
    data = daily_features.copy()
    rows = []
    model_features = getattr(runtime_context, "model_feature_map", None) or MODEL_FEATURES
    for model_name in model_names:
        if model_name not in model_features:
            raise KeyError(f"Governance alpha model is not configured: {model_name}")
        feature_col = model_features[model_name]
        if feature_col not in data.columns:
            continue
        score = pd.to_numeric(data[feature_col], errors="coerce")
        if factor_judged:
            runtime_directions = getattr(runtime_context, "direction_map", None) or {}
            if model_name in runtime_directions:
                direction_value = str(runtime_directions[model_name]).strip().lower()
                if direction_value not in {"higher_better", "lower_better"}:
                    raise ValueError(f"Unsupported runtime factor direction: {direction_value!r}")
                direction = -1.0 if direction_value == "lower_better" else 1.0
            else:
                direction = float(GOVERNANCE_FACTOR_JUDGED_ALPHA_DIRECTIONS.get(model_name, 1.0))
            score = score * (-1.0 if direction < 0.0 else 1.0)
        volatility = pd.to_numeric(data.get("volatility_20"), errors="coerce").fillna(0.0)
        non_null_abs_score = score.abs().dropna()
        scale = non_null_abs_score.median() if not non_null_abs_score.empty else 1.0
        scale = float(scale) if pd.notna(scale) and scale > 1e-12 else 1.0
        predicted = (score / scale).clip(-5.0, 5.0) * 0.01
        part = pd.DataFrame(
            {
                "symbol": data["symbol"].astype(str),
                "model_name": model_name,
                "predicted_return_5d": predicted,
                "prediction_std": volatility.clip(lower=0.001),
                "reputation_weight": _effective_alpha_weight(
                    model_name,
                    reputation_weights=reputation_weights,
                    factor_judged=factor_judged,
                ),
            }
        )
        rows.append(part)
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "model_name",
                "predicted_return_5d",
                "prediction_std",
                "reputation_weight",
            ]
        )
    return pd.concat(rows, ignore_index=True)


def build_daily_candidates(
    daily_features: pd.DataFrame,
    *,
    reputation_weights: dict[str, float] | None = None,
    holding_days: dict[str, int] | None = None,
    candidate_limit: int | None = None,
    model_names=GOVERNANCE_ALPHA_MODELS,
    min_score_percentile: float | None = None,
    enable_quality_filters: bool | None = None,
    allowed_instrument_types: tuple[str, ...] | None = None,
    target_index_codes: tuple[str, ...] = (),
    universe_mode: str = "index_pool_strict",
    require_constituents: bool = True,
    allow_fallback: bool = False,
    selection_weight_mode: str = "reputation_weighted",
    runtime_context=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Combine rule proposals with tradable feature rows for president-policy input.
    
    Parameters
    ----------
    daily_features : pd.DataFrame
        Daily feature data
    reputation_weights : dict, optional
        Reputation weights for each model
    holding_days : dict, optional
        Current holding days for each symbol
    candidate_limit : int, optional
        Maximum number of candidates
    model_names : tuple
        Model names to use
    min_score_percentile : float, optional
        Minimum score percentile threshold
    enable_quality_filters : bool, optional
        Whether to apply buy quality filters (default: from config)
    
    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame] : (candidates, proposals)
    """
    if min_score_percentile is None:
        min_score_percentile = STRATEGY_MIN_SCORE_PERCENTILE
    if enable_quality_filters is None:
        enable_quality_filters = ENABLE_BUY_QUALITY_FILTERS
    held_symbols = {str(symbol) for symbol in (holding_days or {})}

    def preserve_held(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
        """Keep held rows visible to the lifecycle state machine.

        Entry eligibility columns retain their original false values, so this
        does not turn an ineligible holding into a new buy candidate.
        """
        if before.empty or not held_symbols or "symbol" not in before.columns:
            return after
        present = set(after["symbol"].astype(str)) if not after.empty else set()
        missing = held_symbols - present
        if not missing:
            return after
        held_rows = before[before["symbol"].astype(str).isin(missing)]
        return pd.concat([after, held_rows], ignore_index=True)
    
    funnel_counts = {"universe_count": int(len(daily_features))}
    proposals = build_rule_alpha_proposals(
        daily_features,
        reputation_weights=reputation_weights,
        model_names=model_names,
        factor_judged=str(selection_weight_mode or "").strip().lower() in {"factor_judged", "cabinet_native"},
        runtime_context=runtime_context,
    )
    funnel_counts["proposal_symbol_count"] = int(proposals["symbol"].nunique()) if not proposals.empty else 0
    if proposals.empty:
        empty = _empty_candidates()
        empty.attrs["candidate_funnel_counts"] = funnel_counts
        return empty, proposals
    combined = combine_alpha_proposals(proposals)
    combined = _attach_state_machine_alpha_evidence(combined, proposals, runtime_context=runtime_context)
    collapses = alpha_collapse_symbols(proposals, combined, holding_days or {})
    source = daily_features.copy()
    keep = [
        "date",
        "symbol",
        "instrument_type",
        "volatility_20",
        "ret_5",
        "ret_20",
        "close_to_ma20",
        "close",
        "close_nominal",
        "amount",
        "amount_ma20",
        "is_trading",
        "abnormal_jump",
        "kelly_score",
        "target_weight",
        "p_win_lower",
        "payoff_ratio",
        "index_pool_codes",
        "in_target_index_pool",
        "score_orderflow_amount_shock",
        "score_orderflow_close_drive",
        "score_orderflow_accumulation",
        "score_orderflow_efficiency",
        "score_eod_close_strength",
        "score_mean_reversion",
        "score_rsi_reversal",
        "score_kdj_oversold_cross",
        "score_low_volume_pullback",
        "score_consecutive_decline_rebound",
        "score_price_volume_breakout",
        "score_turtle_breakout",
        "score_limit_up_follow",
        "score_ma_break",
        "score_mom_lowvol",
        "score_macd_trend",
        "score_macd_cross",
        "score_ma_cross",
    ]
    source = source[[column for column in keep if column in source.columns]].copy()
    candidates = source.merge(combined, on="symbol", how="inner")
    candidates["_entry_eligible"] = ~candidates["symbol"].astype(str).isin(held_symbols)
    funnel_counts["factor_valid_count"] = int(len(candidates))
    candidates["expected_return_5d"] = (
        proposals.groupby("symbol")["predicted_return_5d"].mean().reindex(candidates["symbol"]).to_numpy()
    )
    candidates["alpha_collapse_exit"] = candidates["symbol"].isin(collapses)
    instrument_types = tuple(allowed_instrument_types or GOVERNANCE_ALLOWED_INSTRUMENT_TYPES)
    before = candidates
    eligible = candidates["instrument_type"].astype(str).isin(instrument_types)
    before["_entry_eligible"] = before["_entry_eligible"] & eligible
    candidates = preserve_held(before, before[eligible])
    funnel_counts["instrument_type_pass_count"] = int(candidates["_entry_eligible"].sum())
    # Filter to target index pools (沪深300/中证500/中证100/上证50/中证A500) + all ETFs
    before = candidates
    filtered = _apply_index_pool_filter_registry(
        before,
        target_index_codes=tuple(target_index_codes),
        universe_mode=universe_mode,
        require_constituents=require_constituents,
        allow_fallback=allow_fallback,
    )
    passed_symbols = set(filtered["symbol"].astype(str))
    before["_entry_eligible"] = before["_entry_eligible"] & before["symbol"].astype(str).isin(passed_symbols)
    if "_entry_eligible" in filtered.columns:
        filtered["_entry_eligible"] = filtered["_entry_eligible"] & filtered["symbol"].astype(str).isin(passed_symbols)
    candidates = preserve_held(before, filtered)
    funnel_counts["universe_membership_pass_count"] = int(candidates["_entry_eligible"].sum())
    if "is_trading" in candidates.columns:
        before = candidates
        eligible = candidates["is_trading"].fillna(False).astype(bool)
        before["_entry_eligible"] = before["_entry_eligible"] & eligible
        candidates = preserve_held(before, before[eligible])
        funnel_counts["trading_pass_count"] = int(candidates["_entry_eligible"].sum())
    else:
        funnel_counts["trading_pass_count"] = int(len(candidates))
    if "abnormal_jump" in candidates.columns:
        before = candidates
        eligible = ~candidates["abnormal_jump"].fillna(True).astype(bool)
        before["_entry_eligible"] = before["_entry_eligible"] & eligible
        candidates = preserve_held(before, before[eligible])
        funnel_counts["price_quality_pass_count"] = int(candidates["_entry_eligible"].sum())
    else:
        funnel_counts["price_quality_pass_count"] = int(len(candidates))
    amount = pd.to_numeric(candidates.get("amount"), errors="coerce").fillna(0.0)
    rolling_amount = pd.to_numeric(candidates.get("amount_ma20", amount), errors="coerce").fillna(amount)
    candidates["liquidity_eligible"] = (
        (amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
        & (rolling_amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
    )
    before = candidates
    before["_entry_eligible"] = before["_entry_eligible"] & before["liquidity_eligible"]
    candidates = preserve_held(before, before[before["liquidity_eligible"]])
    funnel_counts["liquidity_pass_count"] = int(candidates["_entry_eligible"].sum())
    
    # Apply buy quality filters to improve selection accuracy
    if enable_quality_filters:
        before = candidates
        filtered = _apply_buy_quality_filters(before)
        passed_symbols = set(filtered["symbol"].astype(str))
        before["_entry_eligible"] = before["_entry_eligible"] & before["symbol"].astype(str).isin(passed_symbols)
        if "_entry_eligible" in filtered.columns:
            filtered["_entry_eligible"] = filtered["_entry_eligible"] & filtered["symbol"].astype(str).isin(passed_symbols)
        candidates = preserve_held(before, filtered)
        funnel_counts["buy_quality_pass_count"] = int(candidates["_entry_eligible"].sum())
    else:
        funnel_counts["buy_quality_pass_count"] = int(len(candidates))
    
    before = candidates
    filtered = candidates.dropna(subset=["symbol", "volatility_20", "alpha_score"])
    passed_symbols = set(filtered["symbol"].astype(str))
    before["_entry_eligible"] = before["_entry_eligible"] & before["symbol"].astype(str).isin(passed_symbols)
    if "_entry_eligible" in filtered.columns:
        filtered["_entry_eligible"] = filtered["_entry_eligible"] & filtered["symbol"].astype(str).isin(passed_symbols)
    candidates = preserve_held(before, filtered)
    funnel_counts["required_value_pass_count"] = int(candidates["_entry_eligible"].sum())
    selection_mode = str(selection_weight_mode or "reputation_weighted").strip().lower()
    if selection_mode == "cabinet_native":
        from functions.decision_council.cabinet_native_scoring import attach_cabinet_native_scores
        candidates, _family_evidence = attach_cabinet_native_scores(
            candidates,
            proposals,
            runtime_context=runtime_context,
        )
    elif selection_mode == "factor_judged":
        candidates["primary_score"] = pd.to_numeric(candidates["alpha_percentile"], errors="coerce")
        candidates["score_authority"] = "factor_judged_alpha_ensemble"
    elif selection_mode == "role_balanced":
        candidates["role_balanced_score"] = _role_balanced_selection_score(candidates)
        candidates["primary_score"] = candidates["role_balanced_score"]
        candidates["score_authority"] = "role_balanced_orderflow_reversal_breakout_trend"
    elif "kelly_score" in candidates.columns:
        candidates["primary_score"] = pd.to_numeric(
            candidates["kelly_score"], errors="coerce"
        )
        candidates["score_authority"] = "kelly"
    else:
        candidates["primary_score"] = candidates["alpha_score"]
        candidates["score_authority"] = "exploratory_alpha_fallback"
    before = candidates
    filtered = candidates.dropna(subset=["primary_score"])
    passed_symbols = set(filtered["symbol"].astype(str))
    before["_entry_eligible"] = before["_entry_eligible"] & before["symbol"].astype(str).isin(passed_symbols)
    if "_entry_eligible" in filtered.columns:
        filtered["_entry_eligible"] = filtered["_entry_eligible"] & filtered["symbol"].astype(str).isin(passed_symbols)
    candidates = preserve_held(before, filtered)
    funnel_counts["primary_score_pass_count"] = int(candidates["_entry_eligible"].sum())
    candidates = candidates.sort_values(["primary_score", "symbol"], ascending=[False, True])
    candidates["candidate_rank"] = range(1, len(candidates) + 1)

    # Score qualification filter: only keep stocks above the historical percentile threshold
    if min_score_percentile > 0 and "primary_score" in candidates.columns:
        score_threshold = candidates["primary_score"].quantile(min_score_percentile)
        qualified_mask = candidates["primary_score"] >= score_threshold
        candidates["_entry_eligible"] = candidates["_entry_eligible"] & qualified_mask
        # Always keep currently held positions even if below threshold
        candidates = candidates[qualified_mask | candidates["symbol"].astype(str).isin(held_symbols)]
    funnel_counts["score_percentile_pass_count"] = int(candidates["_entry_eligible"].sum())

    if candidate_limit is not None:
        candidates["_entry_eligible"] = candidates["_entry_eligible"] & candidates["candidate_rank"].le(int(candidate_limit))
        candidates = candidates[
            (candidates["candidate_rank"] <= int(candidate_limit))
            | candidates["symbol"].astype(str).isin(held_symbols)
        ]
    funnel_counts["candidate_limit_pass_count"] = int(candidates["_entry_eligible"].sum())
    funnel_counts["held_lifecycle_visible_count"] = int(
        candidates["symbol"].astype(str).isin(held_symbols).sum()
    )
    result = candidates.drop(columns=["_entry_eligible"], errors="ignore").reset_index(drop=True)
    result.attrs["candidate_funnel_counts"] = funnel_counts
    return result, proposals


def _attach_state_machine_alpha_evidence(combined: pd.DataFrame, proposals: pd.DataFrame, *, runtime_context=None) -> pd.DataFrame:
    """Attach per-symbol diversity evidence used by the president state machine.

    This is intentionally computed from active model votes, not from the raw
    bundle list. A symbol cannot pass merely because the configured bundle is
    diverse; it must have live support from multiple modules/families on the day.
    """
    output = combined.copy()
    defaults = {
        "alpha_active_model_count": 0,
        "alpha_active_module_count": 0,
        "alpha_active_family_count": 0,
        "alpha_max_active_module_share": 1.0,
        "alpha_range_grid_vote_share": 1.0,
        "entry_alpha_vote_count": 0,
        "timing_filter_vote_count": 0,
        "risk_override_vote_count": 0,
        "liquidity_guard_vote_count": 0,
        "hold_validation_vote_count": 0,
        "sell_trigger_vote_count": 0,
        "state_machine_role_pass": False,
        "state_machine_role_block_reason": "alpha_evidence_missing",
    }
    for column, value in defaults.items():
        output[column] = value
    if proposals is None or proposals.empty or "symbol" not in proposals.columns:
        return output

    gate = dict(getattr(runtime_context, "diversity_gate", None) or GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE)
    if not bool(gate.get("enabled", True)):
        output["state_machine_role_pass"] = True
        output["state_machine_role_block_reason"] = "disabled"
        return output

    data = proposals.copy()
    data["symbol"] = data["symbol"].astype(str)
    data["model_name"] = data["model_name"].astype(str)
    data["predicted_return_5d"] = pd.to_numeric(data["predicted_return_5d"], errors="coerce")
    data["reputation_weight"] = pd.to_numeric(data.get("reputation_weight"), errors="coerce").fillna(0.0).clip(lower=0.0)
    data["alpha_percentile_model"] = data.groupby("model_name")["predicted_return_5d"].rank(pct=True)
    active_floor = float(gate.get("active_model_percentile", 0.55))
    active = data[
        data["predicted_return_5d"].gt(0.0)
        & data["reputation_weight"].gt(0.0)
        & data["alpha_percentile_model"].ge(active_floor)
    ].copy()
    if active.empty:
        return output

    module_map = getattr(runtime_context, "module_map", None) or {}
    family_map = getattr(runtime_context, "family_map", None) or {}
    active["factor_module"] = active["model_name"].map(lambda name: module_map.get(name, factor_module(name)))
    active["factor_family"] = active["model_name"].map(lambda name: family_map.get(name, _state_machine_factor_family(name)))
    active["vote_weight"] = active["reputation_weight"].clip(lower=0.0)

    rows = []
    for symbol, group in active.groupby("symbol", sort=False):
        modules = group["factor_module"].astype(str)
        families = group["factor_family"].astype(str)
        total_weight = max(float(group["vote_weight"].sum()), 1e-12)
        module_share = group.groupby("factor_module")["vote_weight"].sum() / total_weight
        roles = _role_vote_counts(group, runtime_context=runtime_context)
        max_share = float(module_share.max()) if not module_share.empty else 1.0
        range_grid_share = float(module_share.get("range_grid", 0.0))
        block_reasons = []
        if int(modules.nunique()) < int(gate.get("min_active_modules", 3)):
            block_reasons.append("active_modules_below_min")
        if int(families.nunique()) < int(gate.get("min_active_families", 3)):
            block_reasons.append("active_families_below_min")
        if max_share > float(gate.get("max_active_module_share", 0.70)):
            block_reasons.append("active_module_share_above_cap")
        if range_grid_share > float(gate.get("max_range_grid_vote_share", 0.35)):
            block_reasons.append("range_grid_vote_share_above_cap")
        if int(roles["entry_alpha_vote_count"]) < int(gate.get("min_entry_alpha_votes", 1)):
            block_reasons.append("entry_alpha_votes_below_min")
        if int(roles["timing_filter_vote_count"]) < int(gate.get("min_timing_filter_votes", 1)):
            block_reasons.append("timing_filter_votes_below_min")
        risk_or_liquidity = int(roles["risk_override_vote_count"]) + int(roles["liquidity_guard_vote_count"])
        if risk_or_liquidity < int(gate.get("min_risk_or_liquidity_votes", 1)):
            block_reasons.append("risk_or_liquidity_votes_below_min")
        if int(roles["hold_validation_vote_count"]) < int(gate.get("min_hold_validation_votes", 0)):
            block_reasons.append("hold_validation_votes_below_min")
        if int(roles["sell_trigger_vote_count"]) < int(gate.get("min_sell_trigger_votes", 0)):
            block_reasons.append("sell_trigger_votes_below_min")
        rows.append(
            {
                "symbol": str(symbol),
                "alpha_active_model_count": int(group["model_name"].nunique()),
                "alpha_active_module_count": int(modules.nunique()),
                "alpha_active_family_count": int(families.nunique()),
                "alpha_max_active_module_share": max_share,
                "alpha_range_grid_vote_share": range_grid_share,
                **roles,
                "state_machine_role_pass": not block_reasons,
                "state_machine_role_block_reason": "|".join(block_reasons) if block_reasons else "passed",
            }
        )
    evidence = pd.DataFrame(rows)
    return output.drop(columns=list(defaults), errors="ignore").merge(evidence, on="symbol", how="left").assign(
        alpha_active_model_count=lambda frame: pd.to_numeric(frame["alpha_active_model_count"], errors="coerce").fillna(0).astype(int),
        alpha_active_module_count=lambda frame: pd.to_numeric(frame["alpha_active_module_count"], errors="coerce").fillna(0).astype(int),
        alpha_active_family_count=lambda frame: pd.to_numeric(frame["alpha_active_family_count"], errors="coerce").fillna(0).astype(int),
        alpha_max_active_module_share=lambda frame: pd.to_numeric(frame["alpha_max_active_module_share"], errors="coerce").fillna(1.0),
        alpha_range_grid_vote_share=lambda frame: pd.to_numeric(frame["alpha_range_grid_vote_share"], errors="coerce").fillna(1.0),
        entry_alpha_vote_count=lambda frame: pd.to_numeric(frame["entry_alpha_vote_count"], errors="coerce").fillna(0).astype(int),
        timing_filter_vote_count=lambda frame: pd.to_numeric(frame["timing_filter_vote_count"], errors="coerce").fillna(0).astype(int),
        risk_override_vote_count=lambda frame: pd.to_numeric(frame["risk_override_vote_count"], errors="coerce").fillna(0).astype(int),
        liquidity_guard_vote_count=lambda frame: pd.to_numeric(frame["liquidity_guard_vote_count"], errors="coerce").fillna(0).astype(int),
        hold_validation_vote_count=lambda frame: pd.to_numeric(frame["hold_validation_vote_count"], errors="coerce").fillna(0).astype(int),
        sell_trigger_vote_count=lambda frame: pd.to_numeric(frame["sell_trigger_vote_count"], errors="coerce").fillna(0).astype(int),
        state_machine_role_pass=lambda frame: pd.Series(
            np.where(frame["state_machine_role_pass"].notna(), frame["state_machine_role_pass"], False),
            index=frame.index,
        ).astype(bool),
        state_machine_role_block_reason=lambda frame: frame["state_machine_role_block_reason"].fillna("alpha_evidence_missing").astype(str),
    )


def _role_vote_counts(group: pd.DataFrame, *, runtime_context=None) -> dict[str, int]:
    counts = {
        "entry_alpha_vote_count": 0,
        "timing_filter_vote_count": 0,
        "risk_override_vote_count": 0,
        "liquidity_guard_vote_count": 0,
        "hold_validation_vote_count": 0,
        "sell_trigger_vote_count": 0,
    }
    for model_name in group["model_name"].dropna().astype(str).unique():
        role_map = getattr(runtime_context, "role_map", None) or GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP
        roles = role_map.get(model_name)
        if not roles:
            if runtime_context is not None and getattr(runtime_context, "factor_source", "") != "legacy_bundle":
                raise ValueError(f"factor_cabinet role missing for runtime model: {model_name}")
            module = factor_module(model_name)
            roles = _default_roles_for_module(module)
        role_set = {str(role) for role in roles}
        if "entry_alpha" in role_set:
            counts["entry_alpha_vote_count"] += 1
        if "timing_filter" in role_set:
            counts["timing_filter_vote_count"] += 1
        if "risk_override" in role_set:
            counts["risk_override_vote_count"] += 1
        if "liquidity_guard" in role_set:
            counts["liquidity_guard_vote_count"] += 1
        if "hold_validation" in role_set:
            counts["hold_validation_vote_count"] += 1
        if "sell_trigger" in role_set:
            counts["sell_trigger_vote_count"] += 1
    return counts


def _default_roles_for_module(module: str) -> tuple[str, ...]:
    module = str(module).lower()
    if module in {"flow_close"}:
        return ("entry_alpha", "timing_filter", "liquidity_guard")
    if module in {"trend"}:
        return ("entry_alpha", "hold_validation")
    if module in {"reversal_pullback", "range_grid"}:
        return ("entry_alpha", "timing_filter")
    if module in {"defensive"}:
        return ("risk_override", "hold_validation")
    if module in {"event_limit"}:
        return ("entry_alpha", "sell_trigger")
    return ("entry_alpha",)


def _state_machine_factor_family(model_name: str) -> str:
    name = str(model_name).lower()
    if name.startswith("candidate_grid_rank_ratio__rev") and "amihud" in name:
        return "rev_amihud_ratio_grid"
    if name.startswith("candidate_grid_rank_spread__rev") and "amihud" in name:
        return "rev_amihud_spread_grid"
    if name.startswith("candidate_grid_rank_product__ret") and "__rev_" in name:
        return "ret_reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__rev_" in name:
        return "reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__size_" in name:
        return "rev_size_interaction_grid"
    if name.startswith("candidate_grid_rank_gate_hi__ret") and "__size_" in name:
        return "ret_size_conditional_grid"
    if name.startswith("candidate_grid_rank_gate_hi__rev") and "__size_" in name:
        return "rev_size_conditional_grid"
    if name.startswith("candidate_grid_rank_mean__rev") and "__rev_" in name:
        return "short_medium_reversal_blend_grid"
    if name.startswith("candidate_grid_base_rank__rev"):
        return "single_reversal_grid"
    if name.startswith("candidate_grid_base_rank__vol"):
        return "single_volatility_grid"
    if name.startswith("candidate_grid_base_rank__downvol"):
        return "single_downside_volatility_grid"
    if name.startswith("candidate_size_") or name.startswith("candidate_grid_base_rank__size"):
        return "size_style"
    if name.startswith("candidate_idiosyncratic_vol"):
        return "idiosyncratic_volatility_defense"
    if name.startswith("candidate_downside_volatility"):
        return "downside_volatility_defense"
    if "size_total" in name or "size_float" in name:
        return "size_conditioned_grid"
    if "volatility" in name or "vol_neg" in name or "idiosyncratic_vol" in name:
        return "volatility_defense"
    if "orderflow" in name or "volume" in name or "close_strength" in name:
        return "flow_close"
    if "limit" in name or "event" in name or "holiday" in name:
        return "event_limit"
    if "momentum" in name or "macd" in name or "breakout" in name or "ma_" in name:
        return "trend"
    if "reversal" in name or "decline" in name or "oversold" in name or "pullback" in name:
        return "reversal_pullback"
    tokens = name.split("__")
    return tokens[0] if tokens else name


def _effective_alpha_weight(
    model_name: str,
    *,
    reputation_weights: dict[str, float],
    factor_judged: bool,
) -> float:
    base_weight = float(reputation_weights.get(model_name, 1.0))
    if not factor_judged:
        return base_weight
    judged_weight = float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model_name, 0.0))
    if judged_weight <= float(GOVERNANCE_FACTOR_JUDGED_MIN_WEIGHT):
        return 0.0
    return max(base_weight, 0.0) * judged_weight


def _role_balanced_selection_score(candidates: pd.DataFrame) -> pd.Series:
    """Use module roles as the main candidate score instead of reputation weights."""
    data = candidates.copy()
    orderflow = _module_score(
        data,
        (
            "score_orderflow_amount_shock",
            "score_orderflow_close_drive",
            "score_orderflow_accumulation",
            "score_orderflow_efficiency",
            "score_eod_close_strength",
        ),
    )
    reversal = _module_score(
        data,
        (
            "score_mean_reversion",
            "score_rsi_reversal",
            "score_kdj_oversold_cross",
            "score_low_volume_pullback",
            "score_consecutive_decline_rebound",
        ),
    )
    breakout = _module_score(
        data,
        (
            "score_price_volume_breakout",
            "score_turtle_breakout",
            "score_limit_up_follow",
            "score_ma_break",
        ),
    )
    trend = _module_score(
        data,
        (
            "score_mom_lowvol",
            "score_macd_trend",
            "score_macd_cross",
            "score_ma_cross",
            "ret_20",
        ),
    )
    alpha = pd.to_numeric(data.get("alpha_percentile", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return (
        0.34 * orderflow
        + 0.30 * reversal
        + 0.22 * breakout
        + 0.10 * trend
        + 0.04 * alpha
    ).fillna(0.0).clip(0.0, 1.0)


def _module_score(data: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    available = [column for column in columns if column in data.columns]
    if not available:
        return pd.Series(0.0, index=data.index, dtype="float64")
    ranked = []
    for column in available:
        values = pd.to_numeric(data[column], errors="coerce")
        if values.notna().sum() <= 1:
            ranked.append(pd.Series(0.0, index=data.index, dtype="float64"))
        else:
            ranked.append(values.rank(pct=True).fillna(0.0).clip(0.0, 1.0))
    return pd.concat(ranked, axis=1).mean(axis=1).fillna(0.0).clip(0.0, 1.0)


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "symbol",
            "instrument_type",
            "volatility_20",
            "close",
            "close_nominal",
            "amount",
            "amount_ma20",
            "is_trading",
            "abnormal_jump",
            "ret_20",
            "close_to_ma20",
            "alpha_score",
            "alpha_percentile",
            "expected_return_5d",
            "aggregate_confidence",
            "entry_confirmed",
            "entry_quality_score",
            "entry_block_reason",
            "alpha_collapse_exit",
            "liquidity_eligible",
            "candidate_rank",
            "primary_score",
            "score_authority",
        ]
    )
