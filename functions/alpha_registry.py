# -*- coding: utf-8 -*-
"""
Alpha Registry - Alpha因子注册中心

职责：
- 注册所有可用的alpha因子
- 提供统一接口查询、启停、分组alpha因子
- 支持因子分组测试和因子组合

Alpha Spec 字段：
- alpha_name: 唯一标识符
- module_path: 因子实现所在的模块路径
- score_column: 因子分数列名
- input_columns: 输入列列表
- category: 因子类别 (rule / technical / research / ml / event / governance_support)
- horizon_days: 预测周期（天）
- supports_governance: 是否支持治理模式
- supports_strategy_selection: 是否支持策略选择模式
- description: 描述
- status: 状态 (active / experimental / deprecated / disabled)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlphaSpec:
    """Alpha因子规格定义"""
    alpha_name: str
    module_path: str
    score_column: str
    input_columns: list[str]
    category: str
    horizon_days: int
    supports_governance: bool
    supports_strategy_selection: bool
    description: str
    status: str = "active"
    # 扩展字段
    source: str = "technical"  # 来源: rule / technical / research / ml / event / placeholder
    ascending: bool = False  # 排序方向
    model_type: str | None = None  # ML模型类型
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于序列化"""
        return {
            "alpha_name": self.alpha_name,
            "module_path": self.module_path,
            "score_column": self.score_column,
            "input_columns": self.input_columns,
            "category": self.category,
            "horizon_days": self.horizon_days,
            "supports_governance": self.supports_governance,
            "supports_strategy_selection": self.supports_strategy_selection,
            "description": self.description,
            "status": self.status,
            "source": self.source,
            "ascending": self.ascending,
            "model_type": self.model_type,
        }


class AlphaRegistry:
    """Alpha因子注册中心"""

    def __init__(self):
        self._specs: dict[str, AlphaSpec] = {}
        self._register_builtins()

    def _register_builtins(self):
        """注册内置alpha因子"""

        # ========== Rule Alpha ==========
        self.register(AlphaSpec(
            alpha_name="momentum",
            module_path="functions.strategy_registry",
            score_column="ret_20",
            input_columns=["ret_20"],
            category="rule_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="20日收益率动量因子",
            source="rule",
        ))

        self.register(AlphaSpec(
            alpha_name="reversal",
            module_path="functions.strategy_registry",
            score_column="ret_5",
            input_columns=["ret_5"],
            category="rule_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="5日收益率反转因子",
            source="rule",
            ascending=True,
        ))

        self.register(AlphaSpec(
            alpha_name="low_vol",
            module_path="functions.strategy_registry",
            score_column="volatility_20",
            input_columns=["volatility_20"],
            category="rule_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="20日低波动因子",
            source="rule",
            ascending=True,
        ))

        self.register(AlphaSpec(
            alpha_name="volume_extreme",
            module_path="functions.strategy_registry",
            score_column="volume_ma_20",
            input_columns=["volume_ma_20"],
            category="rule_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="20日成交量均值因子",
            source="rule",
        ))

        self.register(AlphaSpec(
            alpha_name="ma_break",
            module_path="functions.strategy_registry",
            score_column="close_to_ma20",
            input_columns=["close_to_ma20"],
            category="rule_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="收盘价相对20日均线偏离因子",
            source="rule",
        ))

        self.register(AlphaSpec(
            alpha_name="kline_shape",
            module_path="functions.strategy_registry",
            score_column="amplitude",
            input_columns=["amplitude"],
            category="rule_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="日内振幅因子",
            source="rule",
        ))

        self.register(AlphaSpec(
            alpha_name="mom_lowvol",
            module_path="functions.strategy_registry",
            score_column="score_mom_lowvol",
            input_columns=["ret_20", "volatility_20"],
            category="rule_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="动量-低波动复合因子",
            source="rule",
        ))

        # ========== Technical Alpha ==========
        self.register(AlphaSpec(
            alpha_name="macd_trend",
            module_path="functions.strategy_signal_generators",
            score_column="score_macd_trend",
            input_columns=["close", "volume"],
            category="technical_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="MACD 12/26/9趋势强度因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="turtle_breakout",
            module_path="functions.strategy_signal_generators",
            score_column="score_turtle_breakout",
            input_columns=["high", "low", "close", "volume"],
            category="technical_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="海龟突破策略因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="mean_reversion",
            module_path="functions.strategy_signal_generators",
            score_column="score_mean_reversion",
            input_columns=["close", "volume"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="均值回归策略因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="rsi_reversal",
            module_path="functions.strategy_signal_generators",
            score_column="score_rsi_reversal",
            input_columns=["close", "high", "low"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="RSI 6/14/24反转策略因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="grid_trading",
            module_path="functions.strategy_signal_generators",
            score_column="score_grid_trading",
            input_columns=["close", "high", "low", "volume"],
            category="technical_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="ATR自适应网格交易因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="eod_close_strength",
            module_path="functions.strategy_signal_generators",
            score_column="score_eod_close_strength",
            input_columns=["close", "high", "low", "volume"],
            category="technical_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="尾盘强度因子（日线代理）",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="limit_up_follow",
            module_path="functions.strategy_signal_generators",
            score_column="score_limit_up_follow",
            input_columns=["close", "rough_limit_up"],
            category="technical_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="涨停板后续因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="macd_cross",
            module_path="functions.strategy_signal_generators",
            score_column="score_macd_cross",
            input_columns=["close", "volume"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="MACD柱状图金叉信号因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="ma_cross",
            module_path="functions.strategy_signal_generators",
            score_column="score_ma_cross",
            input_columns=["close"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="5/20均线金叉信号因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="price_volume_breakout",
            module_path="functions.strategy_signal_generators",
            score_column="score_price_volume_breakout",
            input_columns=["close", "high", "volume", "amount"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="价量突破因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="consecutive_decline_rebound",
            module_path="functions.strategy_signal_generators",
            score_column="score_consecutive_decline_rebound",
            input_columns=["close", "ret_5"],
            category="technical_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="连续下跌反弹因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="kdj_oversold_cross",
            module_path="functions.strategy_signal_generators",
            score_column="score_kdj_oversold_cross",
            input_columns=["close", "high", "low"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="KDJ超卖金叉反转因子",
            source="technical",
        ))

        self.register(AlphaSpec(
            alpha_name="low_volume_pullback",
            module_path="functions.strategy_signal_generators",
            score_column="score_low_volume_pullback",
            input_columns=["close", "volume", "ret_5"],
            category="technical_alpha",
            horizon_days=10,
            supports_governance=True,
            supports_strategy_selection=True,
            description="低量回踩因子",
            source="technical",
        ))

        # ========== Research Alpha ==========
        self.register(AlphaSpec(
            alpha_name="alpha_hedge",
            module_path="functions.event_and_hedge",
            score_column="score_alpha_hedge",
            input_columns=["close", "volatility_20", "ret_20"],
            category="research_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="研究型alpha对冲因子（截面超额收益/波动率）",
            source="research",
        ))

        self.register(AlphaSpec(
            alpha_name="event_driven",
            module_path="functions.event_statistics",
            score_column="score_event_driven",
            input_columns=["close", "amount", "abnormal_jump"],
            category="event_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="事件驱动因子（市值跳变/事件标签+近期动量）",
            source="research",
        ))

        self.register(AlphaSpec(
            alpha_name="holiday_effect",
            module_path="functions.strategy_signal_generators",
            score_column="score_holiday_effect",
            input_columns=["close"],
            category="research_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=True,
            description="节假日效应因子",
            source="research",
        ))

        # ========== Position Management ==========
        self.register(AlphaSpec(
            alpha_name="position_managed_kelly",
            module_path="functions.position_managed_selection",
            score_column="kelly_score",
            input_columns=["ret_20", "volatility_20", "score_mom_lowvol"],
            category="governance_support_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="仓位管理组主控策略：凯利公式决定目标权重",
            source="position_management",
        ))

        # ========== ML Alpha ==========
        self.register(AlphaSpec(
            alpha_name="ml_elasticnet",
            module_path="functions.factors.factor_ml",
            score_column="score_ml",
            input_columns=["ret_20", "volatility_20", "close_to_ma20", "amount_ratio_20"],
            category="ml_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="ElasticNet机器学习综合分数",
            source="ml",
            model_type="elasticnet",
        ))

        self.register(AlphaSpec(
            alpha_name="ml_xgboost",
            module_path="functions.factors.factor_ml",
            score_column="score_ml",
            input_columns=["ret_20", "volatility_20", "close_to_ma20", "amount_ratio_20"],
            category="ml_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="XGBoost机器学习综合分数",
            source="ml",
            model_type="xgboost",
        ))

        self.register(AlphaSpec(
            alpha_name="ml_lightgbm",
            module_path="functions.factors.factor_ml",
            score_column="score_ml",
            input_columns=["ret_20", "volatility_20", "close_to_ma20", "amount_ratio_20"],
            category="ml_alpha",
            horizon_days=20,
            supports_governance=True,
            supports_strategy_selection=True,
            description="LightGBM机器学习综合分数",
            source="ml",
            model_type="lightgbm",
        ))

        # ========== Governance Support Alpha ==========
        self.register(AlphaSpec(
            alpha_name="ml_alpha",
            module_path="functions.decision_council.ml_alpha_models",
            score_column="score_ml_alpha",
            input_columns=["ret_20", "volatility_20", "close_to_ma20", "amount_ratio_20", "sector_parent_heat"],
            category="governance_support_alpha",
            horizon_days=5,
            supports_governance=True,
            supports_strategy_selection=False,
            description="治理模式专用ML alpha（LightGBM+TabNet集成）",
            source="ml",
            status="active",
        ))

    def register(self, spec: AlphaSpec) -> None:
        """注册一个alpha因子"""
        if spec.alpha_name in self._specs:
            raise ValueError(f"Alpha '{spec.alpha_name}' already registered")
        self._specs[spec.alpha_name] = spec

    def get(self, name: str) -> AlphaSpec:
        """获取alpha因子规格"""
        if name not in self._specs:
            available = sorted(self._specs.keys())
            raise KeyError(f"Unknown alpha '{name}'. Available: {available}")
        return self._specs[name]

    def list_names(self, *, status: str | None = None, category: str | None = None) -> list[str]:
        """列出alpha因子名称"""
        result = []
        for name, spec in self._specs.items():
            if status is not None and spec.status != status:
                continue
            if category is not None and spec.category != category:
                continue
            result.append(name)
        return sorted(result)

    def list_active(self) -> list[str]:
        """列出所有active状态的alpha因子"""
        return self.list_names(status="active")

    def list_by_category(self, category: str) -> list[str]:
        """按类别列出alpha因子"""
        return self.list_names(category=category)

    def list_governance_compatible(self) -> list[str]:
        """列出支持治理模式的alpha因子"""
        return sorted(
            name for name, spec in self._specs.items()
            if spec.supports_governance and spec.status == "active"
        )

    def list_strategy_selection_compatible(self) -> list[str]:
        """列出支持策略选择模式的alpha因子"""
        return sorted(
            name for name, spec in self._specs.items()
            if spec.supports_strategy_selection and spec.status == "active"
        )

    def get_score_columns(self, names: list[str] | None = None) -> list[str]:
        """获取alpha因子的score列名"""
        if names is None:
            names = self.list_active()
        return [self._specs[name].score_column for name in names if name in self._specs]

    def get_input_columns(self, names: list[str] | None = None) -> list[str]:
        """获取alpha因子的输入列名（去重）"""
        if names is None:
            names = self.list_active()
        columns = set()
        for name in names:
            if name in self._specs:
                columns.update(self._specs[name].input_columns)
        return sorted(columns)

    def to_dataframe(self):
        """转换为DataFrame，用于报告"""
        import pandas as pd
        return pd.DataFrame([spec.to_dict() for spec in self._specs.values()])

    def validate(self) -> list[str]:
        """验证所有注册的alpha因子"""
        errors = []
        valid_categories = {
            "rule_alpha", "technical_alpha", "research_alpha",
            "ml_alpha", "event_alpha", "governance_support_alpha"
        }
        for name, spec in self._specs.items():
            if not spec.alpha_name:
                errors.append("Alpha spec missing alpha_name")
            if spec.category not in valid_categories:
                errors.append(f"Alpha '{name}' has invalid category '{spec.category}'")
            if not spec.score_column:
                errors.append(f"Alpha '{name}' missing score_column")
        return errors


# 全局单例
ALPHA_REGISTRY = AlphaRegistry()


def get_alpha_spec(name: str) -> AlphaSpec:
    """获取alpha因子规格（便捷函数）"""
    return ALPHA_REGISTRY.get(name)


def list_alpha_names(*, status: str | None = None, category: str | None = None) -> list[str]:
    """列出alpha因子名称（便捷函数）"""
    return ALPHA_REGISTRY.list_names(status=status, category=category)


def list_active_alphas() -> list[str]:
    """列出active状态的alpha因子（便捷函数）"""
    return ALPHA_REGISTRY.list_active()


def list_governance_alphas() -> list[str]:
    """列出支持治理模式的alpha因子（便捷函数）"""
    return ALPHA_REGISTRY.list_governance_compatible()
