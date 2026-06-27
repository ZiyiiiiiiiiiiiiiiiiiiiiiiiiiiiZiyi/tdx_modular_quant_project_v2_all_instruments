"""Phase-one rule alpha proposals derived from the real feature table."""
from __future__ import annotations

import pandas as pd

from config import (
    ENABLE_BUY_QUALITY_FILTERS,
    BUY_FILTER_MAX_VOLATILITY_MULTIPLIER,
    BUY_FILTER_MIN_AMOUNT_MULTIPLIER,
    BUY_FILTER_MAX_DECLINE_20D,
    BUY_FILTER_MIN_RET_5D,
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_MIN_DAILY_AMOUNT,
    STRATEGY_MIN_SCORE_PERCENTILE,
)
from functions.decision_council.alpha import alpha_collapse_symbols, combine_alpha_proposals
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
) -> pd.DataFrame:
    """Build deterministic proposal rows without pretending they are trained ML outputs."""
    reputation_weights = reputation_weights or {}
    data = daily_features.copy()
    rows = []
    for model_name in model_names:
        if model_name not in MODEL_FEATURES:
            raise KeyError(f"Governance alpha model is not configured: {model_name}")
        feature_col = MODEL_FEATURES[model_name]
        if feature_col not in data.columns:
            continue
        score = pd.to_numeric(data[feature_col], errors="coerce")
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
                "reputation_weight": float(reputation_weights.get(model_name, 1.0)),
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
    
    proposals = build_rule_alpha_proposals(
        daily_features,
        reputation_weights=reputation_weights,
        model_names=model_names,
    )
    if proposals.empty:
        return _empty_candidates(), proposals
    combined = combine_alpha_proposals(proposals)
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
    candidates["expected_return_5d"] = (
        proposals.groupby("symbol")["predicted_return_5d"].mean().reindex(candidates["symbol"]).to_numpy()
    )
    candidates["alpha_collapse_exit"] = candidates["symbol"].isin(collapses)
    instrument_types = tuple(allowed_instrument_types or GOVERNANCE_ALLOWED_INSTRUMENT_TYPES)
    candidates = candidates[
        candidates["instrument_type"].astype(str).isin(instrument_types)
    ]
    # Filter to target index pools (沪深300/中证500/中证100/上证50/中证A500) + all ETFs
    candidates = _apply_index_pool_filter_registry(
        candidates,
        target_index_codes=tuple(target_index_codes),
        universe_mode=universe_mode,
        require_constituents=require_constituents,
        allow_fallback=allow_fallback,
    )
    if "is_trading" in candidates.columns:
        candidates = candidates[candidates["is_trading"].fillna(False)]
    if "abnormal_jump" in candidates.columns:
        candidates = candidates[~candidates["abnormal_jump"].fillna(True)]
    amount = pd.to_numeric(candidates.get("amount"), errors="coerce").fillna(0.0)
    rolling_amount = pd.to_numeric(candidates.get("amount_ma20", amount), errors="coerce").fillna(amount)
    candidates["liquidity_eligible"] = (
        (amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
        & (rolling_amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
    )
    candidates = candidates[candidates["liquidity_eligible"]]
    
    # Apply buy quality filters to improve selection accuracy
    if enable_quality_filters:
        candidates = _apply_buy_quality_filters(candidates)
    
    candidates = candidates.dropna(subset=["symbol", "volatility_20", "alpha_score"])
    selection_mode = str(selection_weight_mode or "reputation_weighted").strip().lower()
    if selection_mode == "role_balanced":
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
    candidates = candidates.dropna(subset=["primary_score"])
    candidates = candidates.sort_values(["primary_score", "symbol"], ascending=[False, True])
    candidates["candidate_rank"] = range(1, len(candidates) + 1)

    # Score qualification filter: only keep stocks above the historical percentile threshold
    if min_score_percentile > 0 and "primary_score" in candidates.columns:
        score_threshold = candidates["primary_score"].quantile(min_score_percentile)
        qualified_mask = candidates["primary_score"] >= score_threshold
        # Always keep currently held positions even if below threshold
        held = set((holding_days or {}).keys())
        candidates = candidates[qualified_mask | candidates["symbol"].astype(str).isin(held)]

    if candidate_limit is not None:
        held = set((holding_days or {}).keys())
        candidates = candidates[
            (candidates["candidate_rank"] <= int(candidate_limit))
            | candidates["symbol"].astype(str).isin(held)
        ]
    return candidates.reset_index(drop=True), proposals


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
