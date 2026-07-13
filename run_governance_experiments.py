# -*- coding: utf-8 -*-
"""
Unified Governance Experiments Entry Point

统一实验入口，替代以下零散脚本：
- run_governance_ensemble.py
- run_governance_lightgbm.py
- run_governance_tabnet.py
- run_governance_industrial_pipeline.py

支持的实验类型：
- alpha_ablation: Alpha因子消融实验
- universe_ablation: 股票池消融实验
- risk_policy_ablation: 风险策略消融实验
- position_sizing_ablation: 仓位管理消融实验

用法：
    python run_governance_experiments.py --variant rules_based_president --alpha-bundle president_core_bundle
    python run_governance_experiments.py --experiment-plan experiment_plan.json
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from config import (
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_END_DATE,
    GOVERNANCE_FACTOR_JUDGE_RUN_ID,
    GOVERNANCE_INITIAL_CASH,
    GOVERNANCE_OUTPUT_DIR,
    GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID,
    GOVERNANCE_START_DATE,
    RESULT_DIR,
    SAFETY_PROXY_MODE,
)
from functions.universe_registry import (
    UNIVERSE_REGISTRY,
    get_universe_spec,
    list_active_universes,
)
from functions.alpha_registry import (
    ALPHA_REGISTRY,
)
from functions.governance_variant_registry import (
    GOVERNANCE_VARIANT_REGISTRY,
    get_governance_variant_spec,
)
from functions.alpha_bundles import (
    ALPHA_BUNDLE_REGISTRY,
    get_alpha_bundle_spec,
    list_active_alpha_bundles,
)
from functions.decision_council.candidate_factor_cache import (
    attach_pre_screen_candidate_factor_cache,
)
from functions.decision_council.factor_cabinet_feature_cache import (
    attach_factor_cabinet_feature_cache,
)
from functions.decision_council.outputs import write_governance_csv, write_governance_text
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LEGACY,
    LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    factor_source_output_label,
    install_factor_source_model_map,
    resolve_factor_source,
)
from functions.decision_council.runner import (
    GovernanceBacktestRunner,
    _governance_feature_columns,
    _prepare_features,
)
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.output_naming import dated_run_dir, run_suffix
from functions.pipeline_cache import file_fingerprint


class ProgressTracker:
    """Track progress and estimate remaining time."""

    def __init__(self, total_steps, desc="Processing"):
        self.total_steps = total_steps
        self.current_step = 0
        self.desc = desc
        self.start_time = time.time()
        self._last_line_width = 0

    def update(self, step_info=""):
        self.current_step += 1
        elapsed = time.time() - self.start_time
        progress = self.current_step / self.total_steps
        progress_pct = progress * 100

        if self.current_step > 0:
            avg_time_per_step = elapsed / self.current_step
            remaining_steps = self.total_steps - self.current_step
            estimated_remaining = avg_time_per_step * remaining_steps
            remaining_str = str(timedelta(seconds=int(estimated_remaining)))
        else:
            remaining_str = "calculating..."

        bar_length = 30
        filled_length = int(bar_length * progress)
        bar = "#" * filled_length + "-" * (bar_length - filled_length)
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        line = (
            f"{self.desc}: [{bar}] {progress_pct:.1f}% ({self.current_step}/{self.total_steps}) | "
            f"Elapsed: {elapsed_str} | Remaining: {remaining_str} | {step_info}"
        )
        trailing_spaces = " " * max(self._last_line_width - len(line), 0)
        print(f"\r{line}{trailing_spaces}", end="", flush=True)
        self._last_line_width = len(line)

        if self.current_step >= self.total_steps:
            print()


def build_output_path(variant_name: str, alpha_bundle: str, universe_name: str) -> Path:
    """构建输出路径：results/governance/{universe}/{variant}/{bundle}/"""
    return RESULT_DIR / "governance" / universe_name / variant_name / alpha_bundle


def _is_small_capital_profile(capital_profile: dict | None) -> bool:
    profile = dict(capital_profile or {})
    return (
        profile.get("name") == "small_capital_branch"
        or profile.get("base_profile") == "small_capital_branch"
        or bool(profile.get("retail_lot_adapter", False))
    )


def _normalize_governance_control_mode(value) -> str:
    mode = str(value or "normal").strip().lower()
    aliases = {
        "default": "normal",
        "full": "normal",
        "factor": "factor_only",
        "stop": "factor_only",
        "stop_mode": "factor_only",
        "paper": "paper_controls",
        "safe_factor": "safe_factor_only",
        "safe_stop": "safe_factor_only",
    }
    mode = aliases.get(mode, mode)
    allowed = {"normal", "factor_only", "paper_controls", "safe_factor_only"}
    if mode not in allowed:
        raise ValueError(f"Invalid governance control mode: {mode}. Available: {sorted(allowed)}")
    return mode


def _latest_factor_judge_run_id(universe_name: str) -> str:
    base = GOVERNANCE_OUTPUT_DIR / "fast_factor_judge" / str(universe_name)
    if not base.exists():
        return ""
    runs = [
        path for path in base.iterdir()
        if path.is_dir() and (path / "fast_factor_judge_manifest.csv").exists()
    ]
    if not runs:
        return ""
    return max(runs, key=lambda path: path.stat().st_mtime).name


def _factor_judge_config_status(universe_name: str, *, alpha_bundle: str | None = None) -> dict:
    configured_source = (
        GOVERNANCE_PRE_SCREEN_FACTOR_JUDGE_RUN_ID
        if str(alpha_bundle or "").strip() == "pre_screen_promote_bundle"
        else GOVERNANCE_FACTOR_JUDGE_RUN_ID
    )
    configured = str(configured_source or "").strip()
    latest = _latest_factor_judge_run_id(universe_name)
    stale = bool(configured and latest and configured != latest)
    status = {
        "configured_factor_judge_run_id": configured,
        "latest_factor_judge_run_id": latest,
        "factor_judge_config_status": "stale_factor_judge_config" if stale else "current_or_unavailable",
        "stale_factor_judge_config": stale,
    }
    if stale:
        print(
            "[WARN] stale_factor_judge_config: "
            f"configured_factor_judge_run_id={configured}, latest={latest}, universe={universe_name}, "
            f"alpha_bundle={alpha_bundle or ''}"
        )
    return status


def _read_feature_schema_columns() -> set[str]:
    try:
        import pyarrow.parquet as pq

        return set(pq.read_schema(FEATURE_DAILY_PARQUET).names)
    except Exception:
        return set()


def _ensure_governance_feature_columns(required_columns: set[str]) -> set[str]:
    """Rebuild the feature parquet once if newly-required governance columns are absent."""
    available_columns = _read_feature_schema_columns()
    missing = sorted(required_columns - available_columns)
    if not missing:
        return available_columns

    print("Governance feature parquet is missing required columns.")
    print(f"Missing columns: {missing}")
    print("Rebuilding feature parquet to include the latest governance factors...")

    from functions.feature_engineering import generate_daily_features_multi

    generate_daily_features_multi()
    available_columns = _read_feature_schema_columns()
    missing = sorted(required_columns - available_columns)
    if missing:
        raise ValueError(
            "Governance feature parquet is still missing required columns after rebuild: "
            f"{missing}"
        )
    print("Feature rebuild completed. Governance-required columns are now available.")
    return available_columns


def _candidate_generated_feature_columns(alpha_models: tuple[str, ...], *, model_feature_map=None) -> set[str]:
    """Return candidate factor columns generated at runtime, not stored in parquet."""
    available_columns = _read_feature_schema_columns()
    feature_map = model_feature_map or GOVERNANCE_ALPHA_MODEL_FEATURES
    columns = {
        feature_map[name]
        for name in alpha_models
        if name in feature_map
    }
    return {
        column
        for column in columns
        if column.startswith("cand_") and column not in available_columns
    }


def _load_governance_features(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    *,
    alpha_models: tuple[str, ...],
    allowed_instrument_types: tuple[str, ...],
    factor_spec=None,
    progress_callback=None,
) -> pd.DataFrame:
    """Load only the feature columns required by governance experiments."""
    _emit_progress(
        progress_callback,
        percent=18.0,
        step="load_features",
        message="preparing governance feature filters",
        detail=f"window={start_date.date()}..{end_date.date()}, alpha_models={len(alpha_models)}",
    )
    filters = [
        ("date", ">=", start_date - pd.Timedelta(days=60)),
        ("date", "<=", end_date),
    ]
    if allowed_instrument_types:
        load_instrument_types = tuple(dict.fromkeys((*allowed_instrument_types, "etf_fund")))
        filters.append(("instrument_type", "in", list(load_instrument_types)))
    feature_map = (
        dict(factor_spec.model_feature_map or {})
        if factor_spec is not None and factor_spec.uses_factor_cabinet
        else GOVERNANCE_ALPHA_MODEL_FEATURES
    )
    alpha_feature_columns = set(feature_map.values())
    generated_candidate_columns = _candidate_generated_feature_columns(alpha_models, model_feature_map=feature_map)
    required_columns = [
        column for column in _governance_feature_columns()
        if column not in alpha_feature_columns
    ]
    required_columns.extend(
        feature_map[name]
        for name in alpha_models
        if feature_map[name] not in generated_candidate_columns
    )
    required_columns = list(dict.fromkeys(required_columns))
    mandatory_columns = {
        "date",
        "symbol",
        "instrument_type",
        "open",
        "close",
        "amount",
        "volatility_20",
    }
    mandatory_columns.update(
        feature_map[name]
        for name in alpha_models
        if feature_map[name] not in generated_candidate_columns
    )
    _emit_progress(
        progress_callback,
        percent=24.0,
        step="feature_schema",
        message="checking governance feature columns",
        detail=f"mandatory_columns={len(mandatory_columns)}, generated_candidate_columns={len(generated_candidate_columns)}",
    )
    available_columns = _ensure_governance_feature_columns(mandatory_columns)
    required_columns = [column for column in required_columns if column in available_columns]
    _emit_progress(
        progress_callback,
        percent=32.0,
        step="read_feature_parquet",
        message="reading governance feature parquet",
        detail=f"columns={len(required_columns)}, filters={filters}",
    )
    data = pd.read_parquet(
        FEATURE_DAILY_PARQUET,
        columns=required_columns,
        filters=filters,
    )
    _emit_progress(
        progress_callback,
        percent=52.0,
        step="feature_parquet_loaded",
        message="governance feature parquet loaded",
        detail=f"rows={len(data)}, columns={len(data.columns)}",
    )
    if generated_candidate_columns:
        _emit_progress(
            progress_callback,
            percent=58.0,
            step="attach_candidate_cache",
            message="attaching materialized candidate factor cache",
            detail=f"generated_candidate_columns={len(generated_candidate_columns)}",
        )
        if factor_spec is not None and factor_spec.uses_factor_cabinet:
            data = attach_factor_cabinet_feature_cache(
                data,
                spec=factor_spec,
                start_date=start_date,
                end_date=end_date,
                feature_path=FEATURE_DAILY_PARQUET,
            )
        else:
            data = attach_pre_screen_candidate_factor_cache(
                data,
                start_date=start_date - pd.Timedelta(days=60),
                end_date=end_date,
                alpha_models=alpha_models,
                feature_path=FEATURE_DAILY_PARQUET,
            )
        still_missing = sorted(generated_candidate_columns - set(data.columns))
        if still_missing:
            raise ValueError(f"Candidate factor cache did not provide required columns: {still_missing}")
        _emit_progress(
            progress_callback,
            percent=66.0,
            step="candidate_cache_attached",
            message="generated candidate factor cache attached",
            detail=f"rows={len(data)}, columns={len(data.columns)}",
        )
    for column in ("instrument_type", "index_pool_codes"):
        if column in data.columns:
            data[column] = data[column].astype("category")
    _emit_progress(
        progress_callback,
        percent=70.0,
        step="features_ready",
        message="governance features ready",
        detail=f"rows={len(data)}, columns={len(data.columns)}",
    )
    return data


def _emit_progress(progress_callback, **payload) -> None:
    step = str(payload.get("step", ""))
    message = str(payload.get("message", ""))
    detail = str(payload.get("detail", ""))
    if step or message:
        suffix = f" | {detail}" if detail else ""
        print(f"[governance] {step}: {message}{suffix}", flush=True)
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass


def run_single_experiment(
    variant_name: str,
    alpha_bundle: str,
    universe_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
    safety_proxy_mode: str = SAFETY_PROXY_MODE,
    low_memory: bool = True,
    enable_shadow_portfolios: bool = True,
    show_live_monitor: bool = False,
    live_monitor=None,
    output_dir_suffix: str | None = None,
    initial_cash: float = GOVERNANCE_INITIAL_CASH,
    max_positions: int | None = None,
    capital_profile: dict | None = None,
    governance_control_mode: str = "normal",
    alpha_collapse_exit_enabled: bool = True,
    factor_source: str = FACTOR_SOURCE_LEGACY,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    progress_callback=None,
    strategy_logic_version: str = "production_v1",
    regime_overlay_mode_override: str | None = None,
    exit_mode_override: str | None = None,
    enable_market_regime_policy_override: bool | None = None,
    pit_mode: str = "research",
) -> dict[str, Path]:
    """运行单个治理实验"""
    _emit_progress(
        progress_callback,
        percent=4.0,
        step="resolve_factor_source",
        message="resolving governance factor source",
        detail=f"factor_source={factor_source}, alpha_bundle={alpha_bundle}",
    )
    variant_spec = get_governance_variant_spec(variant_name)
    universe_spec = get_universe_spec(universe_name)
    factor_spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
        alpha_bundle=alpha_bundle,
    )
    if factor_spec.uses_factor_cabinet:
        install_factor_source_model_map(factor_spec)
        effective_alpha_bundle = f"factor_cabinet_{factor_spec.factor_cabinet_run_id}"
        alpha_models = factor_spec.alpha_models
    else:
        effective_alpha_bundle = LEGACY_GOVERNANCE_ALPHA_BUNDLE
        get_alpha_bundle_spec(effective_alpha_bundle)
        alpha_models = ALPHA_BUNDLE_REGISTRY.get_alpha_model_names(effective_alpha_bundle)
    _emit_progress(
        progress_callback,
        percent=12.0,
        step="factor_source_resolved",
        message="governance factor source resolved",
        detail=(
            f"factor_source={factor_spec.factor_source}, "
            f"run_id={factor_spec.factor_cabinet_run_id}, alpha_models={len(alpha_models)}"
        ),
    )
    factor_judge_status = _factor_judge_config_status(universe_name, alpha_bundle=effective_alpha_bundle)

    output_dir = build_output_path(
        variant_name,
        factor_source_output_label(factor_spec),
        universe_name,
    )
    if _is_small_capital_profile(capital_profile):
        output_dir = output_dir / "small_capital_branch"
    requested_control_mode = _normalize_governance_control_mode(governance_control_mode)
    control_mode = requested_control_mode
    if variant_name == "governance_layer_validation" and requested_control_mode == "normal":
        control_mode = "factor_only"
    if variant_name == "governance_layer_validation" and control_mode == "factor_only":
        capital_profile = dict(capital_profile or {})
        capital_profile["retail_min_entry_matrix_score"] = min(
            float(capital_profile.get("retail_min_entry_matrix_score", 0.0) or 0.0),
            0.0,
        )
    if requested_control_mode != "normal":
        control_dir_names = {
            "factor_only": "ctrl_factor",
            "safe_factor_only": "ctrl_safe_factor",
            "paper_controls": "ctrl_paper",
        }
        output_dir = output_dir / control_dir_names.get(control_mode, f"ctrl_{control_mode}")
    if not bool(alpha_collapse_exit_enabled):
        output_dir = output_dir / "no_alpha_collapse_exit"
    if output_dir_suffix:
        safe_suffix = str(output_dir_suffix).strip().replace("\\", "_").replace("/", "_")
        if safe_suffix:
            output_dir = output_dir / safe_suffix
    if str(strategy_logic_version).strip().lower() != "production_v1":
        logic_dir = {"mainline_v2": "v2"}.get(
            str(strategy_logic_version).strip().lower(),
            "logic_custom",
        )
        output_dir = output_dir / logic_dir
    output_dir = dated_run_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    from functions.data.pit_level1_store import run_pit_preflight

    pit_audit = run_pit_preflight(
        mode=pit_mode,
        output_path=output_dir / "pit_runtime_audit.json",
    )

    print(f"\n{'=' * 60}")
    print("Running experiment:")
    print(f"  Variant: {variant_name}")
    print(f"  Alpha Bundle: {effective_alpha_bundle}")
    print(f"  Factor Source: {factor_spec.factor_source}")
    print(f"  Factor Cabinet Run ID: {factor_spec.factor_cabinet_run_id}")
    print(f"  Universe: {universe_name}")
    print(f"  Output: {output_dir}")
    print("=" * 60)

    # Load and normalize only the columns needed by this bundle.
    effective_start = pd.Timestamp(start_date or GOVERNANCE_START_DATE)
    effective_end = pd.Timestamp(end_date or GOVERNANCE_END_DATE)
    features = _load_governance_features(
        effective_start,
        effective_end,
        alpha_models=alpha_models,
        allowed_instrument_types=tuple(universe_spec.allowed_instrument_types),
        factor_spec=factor_spec,
        progress_callback=progress_callback,
    )
    if low_memory:
        _emit_progress(
            progress_callback,
            percent=72.0,
            step="prepare_features",
            message="normalizing governance feature frame",
            detail=f"rows={len(features)}, columns={len(features.columns)}",
        )
        features = _prepare_features(features, copy=False)

    # Build policy
    policy = RulesBasedPresidentPolicy(
        enable_sector_cap=variant_spec.enable_sector_cap,
        enable_safety_agent=variant_spec.enable_safety_agent,
        exit_mode=exit_mode_override or variant_spec.extra.get("exit_mode", "full"),
        risk_hard_gate_enabled=variant_spec.extra.get("risk_hard_gate_enabled", False),
    )

    _emit_progress(
        progress_callback,
        percent=76.0,
        step="build_runner",
        message="building governance backtest runner",
        detail=f"universe={universe_name}, variant={variant_name}",
    )
    runner = GovernanceBacktestRunner(
        features,
        initial_cash=float(initial_cash),
        safety_proxy_mode=safety_proxy_mode,
        output_dir=output_dir,
        alpha_models=alpha_models,
        prepared_features=low_memory,
        enable_shadow_portfolios=enable_shadow_portfolios,
        enable_reputation=variant_spec.enable_reputation,
        enable_sector_cap=variant_spec.enable_sector_cap,
        enable_safety_agent=variant_spec.enable_safety_agent,
        enable_market_regime_policy=(
            variant_spec.enable_market_regime_policy
            if enable_market_regime_policy_override is None
            else bool(enable_market_regime_policy_override)
        ),
        entry_confirmation_mode=variant_spec.extra.get("entry_confirmation_mode", "full"),
        selection_weight_mode=variant_spec.extra.get("selection_weight_mode", "reputation_weighted"),
        regime_overlay_mode=regime_overlay_mode_override or variant_spec.extra.get("regime_overlay_mode", "full"),
        risk_hard_gate_enabled=variant_spec.extra.get("risk_hard_gate_enabled", False),
        governance_variant=variant_name,
        universe_mode=universe_spec.mode,
        data_fingerprints={"feature_daily_parquet": file_fingerprint(FEATURE_DAILY_PARQUET)},
        policy=policy,
        target_index_codes=tuple(universe_spec.target_index_codes),
        require_constituents=universe_spec.require_constituents,
        allow_fallback=universe_spec.allow_fallback,
        allowed_instrument_types=tuple(universe_spec.allowed_instrument_types),
        enable_quality_filters=universe_spec.quality_filter_enabled,
        universe_name=universe_name,
        alpha_bundle=effective_alpha_bundle,
        max_positions=max_positions,
        capital_profile=capital_profile,
        governance_control_mode=control_mode,
        alpha_collapse_exit_enabled=bool(alpha_collapse_exit_enabled),
        factor_source_spec=factor_spec,
        strategy_logic_version=strategy_logic_version,
        pit_runtime_state=str(pit_audit["pit_runtime_state"]),
    )

    _emit_progress(
        progress_callback,
        percent=80.0,
        step="run_backtest",
        message="running governance backtest date loop",
        detail=f"start={effective_start.date()}, end={effective_end.date()}, max_days={max_days}",
    )
    saved = runner.run(
        start_date=effective_start,
        end_date=effective_end,
        max_days=max_days,
        show_progress=True,
        show_live_monitor=show_live_monitor,
        live_monitor=live_monitor,
        progress_callback=progress_callback,
    )
    _emit_progress(
        progress_callback,
        percent=94.0,
        step="save_metadata",
        message="saving governance experiment metadata",
        detail=f"output_dir={output_dir}",
    )

    # Save experiment metadata
    metadata = {
        "variant_name": variant_name,
        "alpha_bundle": effective_alpha_bundle,
        "legacy_alpha_bundle": LEGACY_GOVERNANCE_ALPHA_BUNDLE if factor_spec.factor_source == FACTOR_SOURCE_LEGACY else "",
        "factor_source": factor_spec.factor_source,
        "factor_cabinet_run_id": factor_spec.factor_cabinet_run_id,
        "factor_cabinet_path": factor_spec.factor_cabinet_path,
        "factor_count": factor_spec.factor_count,
        "role_distribution": factor_spec.role_distribution or {},
        "strict_entry_alpha_count": factor_spec.strict_entry_alpha_count,
        "proxy_entry_alpha_count": factor_spec.proxy_entry_alpha_count,
        "universe_name": universe_name,
        "start_date": str(effective_start),
        "end_date": str(effective_end),
        "output_dir": str(output_dir),
        "governance_control_mode": control_mode,
        "strategy_logic_version": str(strategy_logic_version),
        "alpha_collapse_exit_enabled": bool(alpha_collapse_exit_enabled),
        "output_dir_suffix": str(output_dir_suffix or ""),
        "alpha_models": list(alpha_models),
        "enable_reputation": variant_spec.enable_reputation,
        "enable_sector_cap": variant_spec.enable_sector_cap,
        "enable_safety_agent": variant_spec.enable_safety_agent,
        "enable_market_regime_policy": (
            variant_spec.enable_market_regime_policy
            if enable_market_regime_policy_override is None
            else bool(enable_market_regime_policy_override)
        ),
        "entry_confirmation_mode": variant_spec.extra.get("entry_confirmation_mode", "full"),
        "exit_mode": exit_mode_override or variant_spec.extra.get("exit_mode", "full"),
        "regime_overlay_mode": regime_overlay_mode_override or variant_spec.extra.get("regime_overlay_mode", "full"),
        "layer_added": variant_spec.extra.get("layer_added", ""),
        "universe_mode": universe_spec.mode,
        "require_constituents": universe_spec.require_constituents,
        "low_memory": low_memory,
        "initial_cash": float(initial_cash),
        "max_positions": max_positions,
        **factor_judge_status,
    }
    metadata_path = output_dir / "experiment_metadata.json"
    write_governance_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        metadata_path,
        encoding="utf-8",
    )
    _emit_progress(
        progress_callback,
        percent=100.0,
        step="complete",
        message="governance experiment complete",
        detail=f"output_dir={output_dir}",
    )

    del runner
    del features
    gc.collect()
    print(f"\nExperiment completed. Results saved to: {output_dir}")
    return saved


def run_alpha_ablation(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
    base_variant: str = "rules_based_president",
    bundles: list[str] | None = None,
) -> dict[str, dict[str, Path]]:
    """运行alpha因子消融实验"""
    if bundles is None:
        bundles = list_active_alpha_bundles()

    variant_spec = get_governance_variant_spec(base_variant)
    results = {}
    progress = ProgressTracker(len(bundles), "Alpha Ablation")
    for bundle_name in bundles:
        try:
            result = run_single_experiment(
                variant_name=base_variant,
                alpha_bundle=bundle_name,
                universe_name=variant_spec.universe_name,
                start_date=start_date,
                end_date=end_date,
                max_days=max_days,
            )
            results[bundle_name] = result
        except Exception as e:
            print(f"\nError running bundle '{bundle_name}': {e}")
            results[bundle_name] = {"error": str(e)}
        finally:
            gc.collect()
        progress.update(bundle_name)
    return results


def run_universe_ablation(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
    base_variant: str = "rules_based_president",
    universes: list[str] | None = None,
) -> dict[str, dict[str, Path]]:
    """运行股票池消融实验"""
    if universes is None:
        universes = list_active_universes()

    variant_spec = get_governance_variant_spec(base_variant)
    results = {}
    progress = ProgressTracker(len(universes), "Universe Ablation")
    for universe_name in universes:
        try:
            result = run_single_experiment(
                variant_name=base_variant,
                alpha_bundle=variant_spec.alpha_bundle,
                universe_name=universe_name,
                start_date=start_date,
                end_date=end_date,
                max_days=max_days,
            )
            results[universe_name] = result
        except Exception as e:
            print(f"\nError running universe '{universe_name}': {e}")
            results[universe_name] = {"error": str(e)}
        finally:
            gc.collect()
        progress.update(universe_name)
    return results


def run_experiment_plan(
    plan_path: str | Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    max_days: int | None = None,
) -> dict[str, dict[str, Path]]:
    """从JSON/YAML实验计划运行实验"""
    plan_path = Path(plan_path)
    if not plan_path.exists():
        raise FileNotFoundError(f"Experiment plan not found: {plan_path}")

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    experiments = plan.get("experiments", [])
    results = {}
    progress = ProgressTracker(len(experiments), "Experiment Plan")
    for exp in experiments:
        exp_name = exp.get("name", "unnamed")
        try:
            result = run_single_experiment(
                variant_name=exp["variant"],
                alpha_bundle=exp["alpha_bundle"],
                universe_name=exp["universe"],
                start_date=exp.get("start_date", start_date),
                end_date=exp.get("end_date", end_date),
                max_days=exp.get("max_days", max_days),
            )
            results[exp_name] = result
        except Exception as e:
            print(f"\nError running experiment '{exp_name}': {e}")
            results[exp_name] = {"error": str(e)}
        progress.update(exp_name)
    return results


def build_experiment_comparison_report(results: dict[str, dict[str, Path]]) -> pd.DataFrame:
    """构建实验比较报告"""
    rows = []
    for exp_name, result in results.items():
        if "error" in result:
            rows.append({"experiment": exp_name, "status": "error", "error": result["error"]})
            continue

        # Try to load governance summary
        summary_path = None
        for key, path in result.items():
            if isinstance(path, Path) and "governance_strategy_summary" in str(path):
                summary_path = path
                break

        if summary_path and summary_path.exists():
            try:
                summary = pd.read_csv(summary_path)
                if not summary.empty:
                    row = summary.iloc[0].to_dict()
                    row["experiment"] = exp_name
                    row["status"] = "completed"
                    rows.append(row)
            except Exception:
                rows.append({"experiment": exp_name, "status": "completed_no_summary"})
        else:
            rows.append({"experiment": exp_name, "status": "completed_no_summary"})

    return pd.DataFrame(rows)


def save_experiment_comparison_report(comparison: pd.DataFrame, name: str) -> Path:
    output_path = RESULT_DIR / "governance" / f"{name}_comparison_summary{run_suffix()}.csv"
    return write_governance_csv(comparison, output_path)


def run_registered_mainline_v2_suite(
    *,
    universe_name: str,
    start_date: str,
    end_date: str,
    max_days: int | None,
    factor_source: str,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    capital_profile: dict | None = None,
    pit_mode: str = "research",
    max_runtime_seconds: float | None = None,
) -> dict[str, dict[str, Path]]:
    """Run only the four pre-registered mainline comparisons."""
    specs = (
        ("production_v1", "production_v1", None, None, None),
        ("mainline_v2", "mainline_v2", None, None, None),
        ("mainline_v2_without_regime", "mainline_v2", "off", None, False),
        ("mainline_v2_simple_exit", "mainline_v2", None, "simple", None),
    )
    import time

    started = time.monotonic()
    results = {}
    for label, logic, regime_override, exit_override, regime_policy_override in specs:
        if max_runtime_seconds is not None and time.monotonic() - started >= float(max_runtime_seconds):
            raise TimeoutError(
                f"Registered mainline v2 suite exceeded {float(max_runtime_seconds):.1f}s before {label}"
            )
        results[label] = run_single_experiment(
            variant_name="rules_based_president",
            alpha_bundle=LEGACY_GOVERNANCE_ALPHA_BUNDLE,
            universe_name=universe_name,
            start_date=start_date,
            end_date=end_date,
            max_days=max_days,
            enable_shadow_portfolios=False,
            output_dir_suffix=f"registered_{label}",
            capital_profile=capital_profile,
            factor_source=factor_source,
            factor_cabinet_run_id=factor_cabinet_run_id,
            factor_cabinet_path=factor_cabinet_path,
            strategy_logic_version=logic,
            regime_overlay_mode_override=regime_override,
            exit_mode_override=exit_override,
            enable_market_regime_policy_override=regime_policy_override,
            pit_mode=pit_mode,
        )
    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Unified Governance Experiments")
    parser.add_argument(
        "--experiment",
        choices=["alpha_ablation", "universe_ablation", "mainline_v2_registered"],
        help="Experiment type to run",
    )
    parser.add_argument("--variant", type=str, help="Governance variant name")
    parser.add_argument("--alpha-bundle", type=str, help="Alpha bundle name")
    parser.add_argument("--universe", type=str, help="Universe name")
    parser.add_argument("--start-date", type=str, default=GOVERNANCE_START_DATE)
    parser.add_argument("--end-date", type=str, default=GOVERNANCE_END_DATE)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default=SAFETY_PROXY_MODE)
    parser.add_argument(
        "--governance-control-mode",
        choices=["normal", "factor_only", "paper_controls", "safe_factor_only"],
        default="normal",
        help="Governance control switch for stop-mode experiments.",
    )
    parser.add_argument(
        "--disable-alpha-collapse-exit",
        action="store_true",
        help="Record alpha-collapse exit as paper diagnostics but do not execute alpha_collapse_consensus sells.",
    )
    parser.add_argument(
        "--factor-source",
        choices=["legacy_bundle", "latest_factor_cabinet", "selected_factor_cabinet"],
        default="legacy_bundle",
    )
    parser.add_argument("--factor-cabinet-run-id", default="")
    parser.add_argument("--factor-cabinet-path", default="")
    parser.add_argument(
        "--strategy-logic-version",
        choices=["production_v1", "mainline_v2"],
        default="production_v1",
    )
    parser.add_argument("--experiment-plan", type=str, help="Path to experiment plan JSON file")
    parser.add_argument("--list-variants", action="store_true", help="List all governance variants")
    parser.add_argument("--list-bundles", action="store_true", help="List all alpha bundles")
    parser.add_argument("--list-universes", action="store_true", help="List all universes")
    parser.add_argument("--list-alphas", action="store_true", help="List all alpha factors")
    parser.add_argument("--validate", action="store_true", help="Validate all registries")
    return parser.parse_args()


def main():
    args = parse_args()

    # List commands
    if args.list_variants:
        print("\n=== Governance Variants ===")
        for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
            spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
            print(f"  {name}: {spec.description} [{spec.status}]")
        return

    if args.list_bundles:
        print("\n=== Alpha Bundles ===")
        for name in ALPHA_BUNDLE_REGISTRY.list_names():
            spec = ALPHA_BUNDLE_REGISTRY.get(name)
            print(f"  {name}: {spec.description} [{spec.status}] ({len(spec.alpha_names)} alphas)")
        return

    if args.list_universes:
        print("\n=== Universes ===")
        for name in UNIVERSE_REGISTRY.list_names():
            spec = UNIVERSE_REGISTRY.get(name)
            print(f"  {name}: {spec.description} [{spec.status}]")
        return

    if args.list_alphas:
        print("\n=== Alpha Factors ===")
        for name in ALPHA_REGISTRY.list_names():
            spec = ALPHA_REGISTRY.get(name)
            print(f"  {name}: {spec.description} [{spec.status}] (category={spec.category})")
        return

    if args.validate:
        print("\n=== Registry Validation ===")
        errors = UNIVERSE_REGISTRY.validate()
        errors.extend(ALPHA_REGISTRY.validate())
        errors.extend(GOVERNANCE_VARIANT_REGISTRY.validate())
        errors.extend(ALPHA_BUNDLE_REGISTRY.validate())
        if errors:
            print("Validation errors:")
            for error in errors:
                print(f"  - {error}")
        else:
            print("All registries validated successfully.")
        return

    # Run experiment plan
    if args.experiment_plan:
        print(f"\nRunning experiment plan: {args.experiment_plan}")
        results = run_experiment_plan(
            args.experiment_plan,
            start_date=args.start_date,
            end_date=args.end_date,
            max_days=args.max_days,
        )
        comparison = build_experiment_comparison_report(results)
        comparison_path = save_experiment_comparison_report(comparison, "experiment_plan")
        print("\n=== Experiment Comparison ===")
        print(comparison.to_string(index=False))
        print(f"Saved comparison summary: {comparison_path}")
        return

    # Run single experiment
    if args.variant and args.alpha_bundle and args.universe:
        run_single_experiment(
            variant_name=args.variant,
            alpha_bundle=args.alpha_bundle,
            universe_name=args.universe,
            start_date=args.start_date,
            end_date=args.end_date,
            max_days=args.max_days,
            safety_proxy_mode=args.safety_proxy_mode,
            governance_control_mode=args.governance_control_mode,
            alpha_collapse_exit_enabled=not bool(args.disable_alpha_collapse_exit),
            factor_source=args.factor_source,
            factor_cabinet_run_id=args.factor_cabinet_run_id,
            factor_cabinet_path=args.factor_cabinet_path,
            strategy_logic_version=args.strategy_logic_version,
        )
        return

    # Run ablation experiment
    if args.experiment:
        print(f"\nRunning {args.experiment}...")
        if args.experiment == "alpha_ablation":
            results = run_alpha_ablation(
                start_date=args.start_date,
                end_date=args.end_date,
                max_days=args.max_days,
            )
        elif args.experiment == "universe_ablation":
            results = run_universe_ablation(
                start_date=args.start_date,
                end_date=args.end_date,
                max_days=args.max_days,
            )
        elif args.experiment == "mainline_v2_registered":
            if not args.universe:
                raise ValueError("--universe is required for mainline_v2_registered")
            results = run_registered_mainline_v2_suite(
                universe_name=args.universe,
                start_date=args.start_date,
                end_date=args.end_date,
                max_days=args.max_days,
                factor_source=args.factor_source,
                factor_cabinet_run_id=args.factor_cabinet_run_id,
                factor_cabinet_path=args.factor_cabinet_path,
            )
        else:
            print(f"Experiment type '{args.experiment}' not yet implemented.")
            return

        comparison = build_experiment_comparison_report(results)
        comparison_path = save_experiment_comparison_report(comparison, args.experiment)
        print("\n=== Experiment Comparison ===")
        print(comparison.to_string(index=False))
        print(f"Saved comparison summary: {comparison_path}")
        return

    # Default: show help
    print("\nNo experiment specified. Use --help for usage information.")
    print("\nQuick start:")
    print("  python run_governance_experiments.py --list-variants")
    print("  python run_governance_experiments.py --list-bundles")
    print("  python run_governance_experiments.py --list-universes")
    print("  python run_governance_experiments.py --variant rules_based_president --alpha-bundle president_core_bundle --universe hs300_csi300_a500_strict")


if __name__ == "__main__":
    main()
