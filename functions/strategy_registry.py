from __future__ import annotations

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
            name="position_managed_kelly",
            score_col="kelly_score",
            ascending=False,
            source="position_management",
            description="仓位管理组主控策略：技术信号先聚合胜率/盈亏比，再用保守凯利公式决定目标权重",
        ),
        StrategySpec(
            name="macd_trend",
            score_col="score_macd_trend",
            ascending=False,
            source="technical",
            description="MACD 12/26/9 trend strength score; candidates remain subject to position management and Kelly sizing.",
        ),
        StrategySpec(
            name="turtle_breakout",
            score_col="score_turtle_breakout",
            ascending=False,
            source="technical",
            description="Turtle breakout strategy using 20/55 day breakout and ATR risk controls; final sizing is Kelly managed.",
        ),
        StrategySpec(
            name="mean_reversion",
            score_col="score_mean_reversion",
            ascending=False,
            source="technical",
            description="Mean reversion strategy using 20 day z-score and Bollinger position; final sizing is Kelly managed.",
        ),
        StrategySpec(
            name="rsi_reversal",
            score_col="score_rsi_reversal",
            ascending=False,
            source="technical",
            description="RSI 6/14/24 reversal strategy with RSI14 as the primary auxiliary signal; final sizing is Kelly managed.",
        ),
        StrategySpec(
            name="grid_trading",
            score_col="score_grid_trading",
            ascending=False,
            source="technical",
            description="ATR adaptive grid-trading research strategy used as position-adjustment helper under Kelly management.",
        ),
        StrategySpec(
            name="alpha_hedge",
            score_col="score_alpha_hedge",
            ascending=False,
            source="research",
            description="Research-only alpha hedge proxy using cross-sectional excess return over volatility; no live shorting is assumed.",
        ),
        StrategySpec(
            name="event_driven",
            score_col="score_event_driven",
            ascending=False,
            source="research",
            description="Auditable event-driven score using market-cap jump/event tags plus recent momentum.",
        ),
        StrategySpec(
            name="eod_close_strength",
            score_col="score_eod_close_strength",
            ascending=False,
            source="technical",
            description="Daily-bar proxy for EOD close strength; not a substitute for minute-level closing-auction data.",
        ),
        StrategySpec(
            name="limit_up_follow",
            score_col="score_limit_up_follow",
            ascending=False,
            source="technical",
            description="Post-limit-up continuation research signal using the prior trading day's limit-up flag.",
        ),
        StrategySpec(
            name="macd_cross",
            score_col="score_macd_cross",
            ascending=False,
            source="technical",
            description="MACD histogram golden-cross signal, distinct from the existing continuous MACD trend score.",
        ),
        StrategySpec(
            name="ma_cross",
            score_col="score_ma_cross",
            ascending=False,
            source="technical",
            description="5/20 moving-average golden-cross signal controlled by Kelly position management.",
        ),
        StrategySpec(
            name="price_volume_breakout",
            score_col="score_price_volume_breakout",
            ascending=False,
            source="technical",
            description="Price breakout over the prior 20-day high confirmed by abnormal volume.",
        ),
        StrategySpec(
            name="consecutive_decline_rebound",
            score_col="score_consecutive_decline_rebound",
            ascending=False,
            source="technical",
            description="Oversold rebound after consecutive declines, with next-day execution.",
        ),
        StrategySpec(
            name="holiday_effect",
            score_col="score_holiday_effect",
            ascending=False,
            source="research",
            description="Pre-holiday calendar-gap effect using exchange-known future trading dates.",
        ),
        StrategySpec(
            name="kdj_oversold_cross",
            score_col="score_kdj_oversold_cross",
            ascending=False,
            source="technical",
            description="KDJ oversold golden-cross reversal signal.",
        ),
        StrategySpec(
            name="low_volume_pullback",
            score_col="score_low_volume_pullback",
            ascending=False,
            source="technical",
            description="Low-volume pullback above the 20-day moving average.",
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
