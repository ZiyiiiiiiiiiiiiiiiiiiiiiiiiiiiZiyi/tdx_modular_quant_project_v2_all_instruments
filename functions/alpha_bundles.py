# -*- coding: utf-8 -*-
"""
Alpha Bundles - Alpha组合机制

职责：
- 定义alpha因子的组合方式
- 支持按bundle组合alpha因子
- 提供不同的混合模式（blend mode）

Alpha Bundle Spec 字段：
- bundle_name: 唯一标识符
- alpha_names: alpha因子名称列表
- weighting_scheme: 权重方案
- blend_mode: 混合模式
- description: 描述
- status: 状态 (active / experimental / deprecated)

Blend 模式：
- equal_weight: 等权混合
- confidence_weighted: 置信度加权
- reputation_weighted: 声誉加权
- rank_ensemble: 排名集成
- stacked_meta_score: 堆叠元分数
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import (
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
    GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY,
    GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS,
)
from functions.alpha_registry import ALPHA_REGISTRY, get_alpha_spec


GOVERNANCE_ALPHA_MODEL_ALIASES = {
    "momentum": "momentum_20",
}


@dataclass(frozen=True)
class AlphaBundleSpec:
    """Alpha组合规格定义"""
    bundle_name: str
    alpha_names: list[str]
    weighting_scheme: str
    blend_mode: str
    description: str
    status: str = "active"
    # 扩展字段
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于序列化"""
        return {
            "bundle_name": self.bundle_name,
            "alpha_names": self.alpha_names,
            "weighting_scheme": self.weighting_scheme,
            "blend_mode": self.blend_mode,
            "description": self.description,
            "status": self.status,
        }

    def get_score_columns(self) -> list[str]:
        """获取bundle中所有alpha的score列名"""
        columns = []
        for name in self.alpha_names:
            try:
                spec = get_alpha_spec(name)
                columns.append(spec.score_column)
            except KeyError:
                feature_column = GOVERNANCE_ALPHA_MODEL_FEATURES.get(name)
                if feature_column:
                    columns.append(feature_column)
        return columns


class AlphaBundleRegistry:
    """Alpha组合注册中心"""

    def __init__(self):
        self._specs: dict[str, AlphaBundleSpec] = {}
        self._register_builtins()

    def _register_builtins(self):
        """注册内置alpha组合"""

        # 1. baseline_technical_bundle - 基线技术因子组合
        self.register(AlphaBundleSpec(
            bundle_name="baseline_technical_bundle",
            alpha_names=[
                "macd_trend",
                "turtle_breakout",
                "mean_reversion",
                "rsi_reversal",
                "grid_trading",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="基线技术因子组合：5个经典技术策略因子",
            status="active",
        ))

        # 2. event_research_bundle - 事件研究组合
        self.register(AlphaBundleSpec(
            bundle_name="event_research_bundle",
            alpha_names=[
                "event_driven",
                "alpha_hedge",
                "holiday_effect",
                "limit_up_follow",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="事件研究组合：事件驱动+alpha对冲+节假日效应+涨停后续",
            status="active",
        ))

        # 3. ml_bundle - ML因子组合
        self.register(AlphaBundleSpec(
            bundle_name="ml_bundle",
            alpha_names=[
                "ml_elasticnet",
                "ml_xgboost",
                "ml_lightgbm",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="ML因子组合：ElasticNet+XGBoost+LightGBM集成",
            status="experimental",
        ))

        # 4. president_core_bundle - 主线核心组合（当前main.py使用的alpha）
        self.register(AlphaBundleSpec(
            bundle_name="president_core_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "ma_break",
                "orderflow_amount_shock",
                "orderflow_close_drive",
                "orderflow_accumulation",
                "orderflow_efficiency",
                "macd_trend",
                "mean_reversion",
                "rsi_reversal",
                "turtle_breakout",
                "alpha_hedge",
                "event_driven",
                "grid_trading",
                "eod_close_strength",
                "limit_up_follow",
                "macd_cross",
                "ma_cross",
                "price_volume_breakout",
                "consecutive_decline_rebound",
                "holiday_effect",
                "kdj_oversold_cross",
                "low_volume_pullback",
            ],
            weighting_scheme="reputation",
            blend_mode="reputation_weighted",
            description="主线核心组合：19个alpha因子，声誉加权",
            status="active",
        ))

        # 5. full_alpha_bundle - 全alpha组合
        self.register(AlphaBundleSpec(
            bundle_name="full_alpha_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "ma_break",
                "orderflow_amount_shock",
                "orderflow_close_drive",
                "orderflow_accumulation",
                "orderflow_efficiency",
                "macd_trend",
                "mean_reversion",
                "rsi_reversal",
                "turtle_breakout",
                "alpha_hedge",
                "event_driven",
                "grid_trading",
                "eod_close_strength",
                "limit_up_follow",
                "macd_cross",
                "ma_cross",
                "price_volume_breakout",
                "consecutive_decline_rebound",
                "holiday_effect",
                "kdj_oversold_cross",
                "low_volume_pullback",
                "ml_elasticnet",
                "ml_xgboost",
                "ml_lightgbm",
                "ml_alpha",
            ],
            weighting_scheme="reputation",
            blend_mode="reputation_weighted",
            description="全alpha组合：包含所有可用alpha因子",
            status="experimental",
        ))

        # 6. research_alpha_bundle - 研究alpha组合
        self.register(AlphaBundleSpec(
            bundle_name="research_alpha_bundle",
            alpha_names=[
                "alpha_hedge",
                "event_driven",
                "holiday_effect",
                "orderflow_amount_shock",
                "orderflow_close_drive",
                "orderflow_accumulation",
                "orderflow_efficiency",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="研究alpha组合：研究型+事件型+仓位管理因子",
            status="active",
        ))

        # 7. low_turnover_bundle - 低换手率组合
        self.register(AlphaBundleSpec(
            bundle_name="low_turnover_bundle",
            alpha_names=[
                "mom_lowvol",
                "low_vol",
                "mean_reversion",
                "low_volume_pullback",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="低换手率组合：选择低波动、低换手的因子",
            status="experimental",
        ))

        # 8. high_selectivity_bundle - 高选择性组合
        self.register(AlphaBundleSpec(
            bundle_name="high_selectivity_bundle",
            alpha_names=[
                "macd_cross",
                "rsi_reversal",
                "low_volume_pullback",
                "limit_up_follow",
            ],
            weighting_scheme="equal",
            blend_mode="rank_ensemble",
            description="高选择性组合：V6正式候选策略因子",
            status="experimental",
        ))

        self.register(AlphaBundleSpec(
            bundle_name="validation_core_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "orderflow_amount_shock",
                "orderflow_efficiency",
                "price_volume_breakout",
                "turtle_breakout",
                "mean_reversion",
                "kdj_oversold_cross",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description=(
                "Layer-validation core bundle: compact equal-weight set for isolating "
                "whether the base entry signal has positive expectancy before reputation, "
                "shadow weighting, or regime-specific overlays are added."
            ),
            status="active",
            extra={
                "purpose": "causal_layer_validation",
                "modules": "momentum,low_vol,orderflow,breakout,reversal",
                "expected_use": "short-to-medium diagnostic runs",
            },
        ))

        formal_defensive_alpha_names = [
            "limit_up_follow",
            "mean_reversion",
            "rsi_reversal",
            "macd_trend",
            "orderflow_amount_shock",
            "grid_trading",
            "consecutive_decline_rebound",
            "kdj_oversold_cross",
            "alpha_hedge",
            "event_driven",
        ]
        self.register(AlphaBundleSpec(
            bundle_name="formal_defensive_bundle",
            alpha_names=formal_defensive_alpha_names,
            weighting_scheme="factor_judged",
            blend_mode="reputation_weighted",
            description=(
                "Defensive retest bundle for the legacy formal governance factors. "
                "The 2026-07-02 large-pool judge rejected all formal factors, so this "
                "bundle is retained only as a conservative formal-factor control."
            ),
            status="active",
            extra={
                "purpose": "formal_factor_defensive_control",
                "judge_run_id": "run20260701_201606_233579",
                "admission_note": "All governance_formal factors were reject_or_rework in the 2026-07-02 judge.",
            },
        ))

        self.register(AlphaBundleSpec(
            bundle_name="judged_core_bundle",
            alpha_names=formal_defensive_alpha_names,
            weighting_scheme="factor_judged",
            blend_mode="reputation_weighted",
            description=(
                "Deprecated compatibility alias for formal_defensive_bundle. "
                "Do not treat this as the 2026-07-02 promote-candidate bundle."
            ),
            status="deprecated",
            extra={
                "purpose": "compatibility_alias",
                "replacement_bundle": "formal_defensive_bundle",
                "judge_run_id": "run20260701_005947_289780",
                "admission_note": "Compatibility only; use formal_defensive_bundle or pre_screen_promote_bundle explicitly.",
            },
        ))

        self.register(AlphaBundleSpec(
            bundle_name="pre_screen_promote_bundle",
            alpha_names=list(GOVERNANCE_PRE_SCREEN_SELECTED_ALPHA_MODELS),
            weighting_scheme="factor_judged",
            blend_mode="reputation_weighted",
            description=(
                "2026-07-02 fast-judge promote candidate bundle selected from the "
                "486 promote + 114 watchlist pool. Non-selected candidates remain "
                "observe-only until a new judge run promotes them."
            ),
            status="active",
            extra={
                "purpose": "pre_screen_promote_candidate_mainline_test",
                "judge_run_id": GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY["judge_run_id"],
                "selected_count": GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY["selected_count"],
                "watchlist_policy": GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY["watchlist_policy"],
                "style_only_policy": GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY["style_only_policy"],
                "indispensable_exceptions": GOVERNANCE_PRE_SCREEN_FACTOR_OBSERVATION_POLICY["indispensable_exceptions"],
            },
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diversified_pre_screen_bundle_v2",
            alpha_names=list(GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2),
            weighting_scheme="factor_judged",
            blend_mode="reputation_weighted",
            description=(
                "Tradable diversified v2 bundle: fixed selection from the 486 promote "
                "+ 114 watchlist pre-screen pool with module, family, correlation, "
                "and state-machine role constraints. The list is static so normal "
                "runs do not re-select the 600-candidate pool."
            ),
            status="active",
            extra={
                "purpose": "tradable_diversified_pre_screen_v2",
                "source_pool": "486 promote_candidate + 114 watchlist",
                "role_map": GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
                "admission_note": "Static v2 admission list; validation checks membership and diversity before trading retest.",
            },
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_trend_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "ma_break",
                "macd_trend",
                "turtle_breakout",
                "macd_cross",
                "ma_cross",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: trend and momentum factors only.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module": "trend"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_reversal_bundle",
            alpha_names=[
                "mean_reversion",
                "rsi_reversal",
                "kdj_oversold_cross",
                "consecutive_decline_rebound",
                "low_volume_pullback",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: reversal and pullback factors only.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module": "reversal_pullback"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_orderflow_bundle",
            alpha_names=[
                "orderflow_amount_shock",
                "orderflow_close_drive",
                "orderflow_accumulation",
                "orderflow_efficiency",
                "eod_close_strength",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: order-flow and close-strength factors only.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module": "orderflow"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_breakout_bundle",
            alpha_names=[
                "price_volume_breakout",
                "turtle_breakout",
                "limit_up_follow",
                "ma_break",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: breakout and limit-up follow factors only.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module": "breakout"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_core_minus_trend_bundle",
            alpha_names=[
                "orderflow_amount_shock",
                "orderflow_efficiency",
                "price_volume_breakout",
                "mean_reversion",
                "kdj_oversold_cross",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: validation core without trend factors.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module_removed": "trend"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_core_minus_reversal_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "orderflow_amount_shock",
                "orderflow_efficiency",
                "price_volume_breakout",
                "turtle_breakout",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: validation core without reversal factors.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module_removed": "reversal_pullback"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_core_minus_orderflow_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "price_volume_breakout",
                "turtle_breakout",
                "mean_reversion",
                "kdj_oversold_cross",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: validation core without order-flow factors.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module_removed": "orderflow"},
        ))

        self.register(AlphaBundleSpec(
            bundle_name="diagnostic_core_minus_breakout_bundle",
            alpha_names=[
                "momentum",
                "mom_lowvol",
                "orderflow_amount_shock",
                "orderflow_efficiency",
                "mean_reversion",
                "kdj_oversold_cross",
            ],
            weighting_scheme="equal",
            blend_mode="equal_weight",
            description="Enhanced diagnostic bundle: validation core without breakout factors.",
            status="active",
            extra={"purpose": "enhanced_module_diagnostics", "module_removed": "breakout"},
        ))

    def register(self, spec: AlphaBundleSpec) -> None:
        """注册一个alpha组合"""
        if spec.bundle_name in self._specs:
            raise ValueError(f"Alpha bundle '{spec.bundle_name}' already registered")
        # 验证所有alpha因子都已注册
        for alpha_name in spec.alpha_names:
            if alpha_name not in ALPHA_REGISTRY._specs and alpha_name not in GOVERNANCE_ALPHA_MODEL_FEATURES:
                raise ValueError(f"Alpha bundle '{spec.bundle_name}' references unknown alpha '{alpha_name}'")
        self._specs[spec.bundle_name] = spec

    def get(self, name: str) -> AlphaBundleSpec:
        """获取alpha组合规格"""
        if name not in self._specs:
            available = sorted(self._specs.keys())
            raise KeyError(f"Unknown alpha bundle '{name}'. Available: {available}")
        return self._specs[name]

    def list_names(self, *, status: str | None = None) -> list[str]:
        """列出alpha组合名称"""
        if status is None:
            return sorted(self._specs.keys())
        return sorted(name for name, spec in self._specs.items() if spec.status == status)

    def list_active(self) -> list[str]:
        """列出所有active状态的alpha组合"""
        return self.list_names(status="active")

    def get_alpha_specs(self, bundle_name: str) -> list:
        """获取bundle中所有alpha的规格"""
        bundle = self.get(bundle_name)
        specs = []
        for alpha_name in bundle.alpha_names:
            try:
                specs.append(get_alpha_spec(alpha_name))
            except KeyError:
                pass
        return specs

    def get_score_columns(self, bundle_name: str) -> list[str]:
        """获取bundle中所有alpha的score列名"""
        return self.get(bundle_name).get_score_columns()

    def get_alpha_model_names(self, bundle_name: str) -> tuple[str, ...]:
        """获取bundle中的alpha模型名称（用于治理模式）"""
        bundle = self.get(bundle_name)
        resolved = []
        unsupported = []
        for alpha_name in bundle.alpha_names:
            model_name = GOVERNANCE_ALPHA_MODEL_ALIASES.get(alpha_name, alpha_name)
            if model_name not in GOVERNANCE_ALPHA_MODEL_FEATURES:
                unsupported.append(alpha_name)
                continue
            if model_name not in resolved:
                resolved.append(model_name)
        if unsupported:
            raise ValueError(
                f"Alpha bundle '{bundle_name}' contains models that are not available "
                f"in the governance feature pipeline: {unsupported}"
            )
        if not resolved:
            raise ValueError(f"Alpha bundle '{bundle_name}' has no runnable governance models")
        return tuple(resolved)

    def to_dataframe(self):
        """转换为DataFrame，用于报告"""
        import pandas as pd
        rows = []
        for spec in self._specs.values():
            rows.append({
                "bundle_name": spec.bundle_name,
                "alpha_count": len(spec.alpha_names),
                "alpha_names": ", ".join(spec.alpha_names),
                "weighting_scheme": spec.weighting_scheme,
                "blend_mode": spec.blend_mode,
                "description": spec.description,
                "status": spec.status,
            })
        return pd.DataFrame(rows)

    def validate(self) -> list[str]:
        """验证所有注册的alpha组合"""
        errors = []
        valid_blend_modes = {
            "equal_weight", "confidence_weighted", "reputation_weighted",
            "rank_ensemble", "stacked_meta_score"
        }
        for name, spec in self._specs.items():
            if not spec.bundle_name:
                errors.append("Alpha bundle spec missing bundle_name")
            if spec.blend_mode not in valid_blend_modes:
                errors.append(f"Bundle '{name}' has invalid blend_mode '{spec.blend_mode}'")
            if not spec.alpha_names:
                errors.append(f"Bundle '{name}' has no alpha factors")
            if spec.status == "active":
                try:
                    self.get_alpha_model_names(name)
                except ValueError as exc:
                    errors.append(str(exc))
        return errors


# 全局单例
ALPHA_BUNDLE_REGISTRY = AlphaBundleRegistry()


def get_alpha_bundle_spec(name: str) -> AlphaBundleSpec:
    """获取alpha组合规格（便捷函数）"""
    return ALPHA_BUNDLE_REGISTRY.get(name)


def list_alpha_bundle_names(*, status: str | None = None) -> list[str]:
    """列出alpha组合名称（便捷函数）"""
    return ALPHA_BUNDLE_REGISTRY.list_names(status=status)


def list_active_alpha_bundles() -> list[str]:
    """列出active状态的alpha组合（便捷函数）"""
    return ALPHA_BUNDLE_REGISTRY.list_active()
