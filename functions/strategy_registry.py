from dataclasses import dataclass

from config import (
    ENABLE_LEARNING_STRATEGIES,
    ENABLE_PLACEHOLDER_STRATEGIES,
    ENABLE_QUANTUM_INSPIRED_STRATEGIES,
    LEARNING_STRATEGY_WHITELIST,
)
from functions.factors.factor_learning import LEARNING_STRATEGY_CONFIGS


@dataclass(frozen=True)
class StrategySpec:
    name: str
    score_col: str
    ascending: bool
    source: str
    description: str
    model_type: str | None = None


def _base_strategy_specs():
    return [
        StrategySpec(
            name="momentum",
            score_col="ret_20",
            ascending=False,
            source="rule",
            description="20日收益率 ret_20，从高到低选取",
        ),
        StrategySpec(
            name="reversal",
            score_col="ret_5",
            ascending=True,
            source="rule",
            description="5日收益率 ret_5，从低到高选取，短期反转",
        ),
        StrategySpec(
            name="low_vol",
            score_col="volatility_20",
            ascending=True,
            source="rule",
            description="20日波动率 volatility_20，从低到高选取，低波动",
        ),
        StrategySpec(
            name="volume_extreme",
            score_col="volume_ma_20",
            ascending=False,
            source="rule",
            description="20日成交量均值 volume_ma_20，从高到低选取",
        ),
        StrategySpec(
            name="ma_break",
            score_col="close_to_ma20",
            ascending=False,
            source="rule",
            description="收盘价相对20日均线偏离 close_to_ma20，从高到低选取",
        ),
        StrategySpec(
            name="kline_shape",
            score_col="amplitude",
            ascending=False,
            source="rule",
            description="日内振幅 amplitude，从高到低选取",
        ),
        StrategySpec(
            name="mom_lowvol",
            score_col="score_mom_lowvol",
            ascending=False,
            source="rule",
            description="20日收益率 ret_20 - 20日波动率 volatility_20",
        ),
        StrategySpec(
            name="ml_elasticnet",
            score_col="score_ml",
            ascending=False,
            source="ml",
            description="ElasticNet 机器学习综合分数 score_ml",
            model_type="elasticnet",
        ),
        StrategySpec(
            name="ml_xgboost",
            score_col="score_ml",
            ascending=False,
            source="ml",
            description="XGBoost 机器学习综合分数 score_ml",
            model_type="xgboost",
        ),
        StrategySpec(
            name="ml_lightgbm",
            score_col="score_ml",
            ascending=False,
            source="ml",
            description="LightGBM 机器学习综合分数 score_ml",
            model_type="lightgbm",
        ),
        StrategySpec(
            name="event_factor",
            score_col="ret_20",
            ascending=False,
            source="placeholder",
            description="占位事件因子：当前暂用 20日收益率 ret_20",
        ),
        StrategySpec(
            name="alternative_factor",
            score_col="ret_20",
            ascending=False,
            source="placeholder",
            description="占位另类因子：当前暂用 20日收益率 ret_20",
        ),
    ]


def _normalize_learning_whitelist(learning_strategy_whitelist):
    if not learning_strategy_whitelist:
        return None
    return {str(name) for name in learning_strategy_whitelist}


def build_strategy_registry(
    enable_learning_strategies=ENABLE_LEARNING_STRATEGIES,
    learning_strategy_whitelist=LEARNING_STRATEGY_WHITELIST,
    enable_placeholder_strategies=ENABLE_PLACEHOLDER_STRATEGIES,
    enable_quantum_inspired_strategies=ENABLE_QUANTUM_INSPIRED_STRATEGIES,
):
    registry = {spec.name: spec for spec in _base_strategy_specs()}
    if not enable_placeholder_strategies:
        registry = {name: spec for name, spec in registry.items() if spec.source != "placeholder"}

    if not enable_learning_strategies:
        return registry

    whitelist = _normalize_learning_whitelist(learning_strategy_whitelist)
    for strategy_name, config in LEARNING_STRATEGY_CONFIGS.items():
        if config["module"] == "quantum_inspired" and not enable_quantum_inspired_strategies:
            continue
        if whitelist is not None and strategy_name not in whitelist:
            continue
        registry[strategy_name] = StrategySpec(
            name=strategy_name,
            score_col="score_learning",
            ascending=False,
            source=config["module"],
            description=config["description"],
        )
    return registry


STRATEGY_REGISTRY = build_strategy_registry()
STRATEGY_FACTOR_DESCRIPTIONS = {
    strategy_name: spec.description
    for strategy_name, spec in STRATEGY_REGISTRY.items()
}


def get_strategy_spec(strategy_name):
    return STRATEGY_REGISTRY[strategy_name]


def list_strategy_names():
    return sorted(STRATEGY_REGISTRY)
