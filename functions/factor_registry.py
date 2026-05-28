# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass

import pandas as pd

from config import FACTOR_REGISTRY_STATUS_DEFAULT


@dataclass(frozen=True)
class FactorSpec:
    factor_name: str
    module_path: str
    output_columns: tuple[str, ...]
    input_columns: tuple[str, ...]
    category: str
    status: str = FACTOR_REGISTRY_STATUS_DEFAULT
    supports_ml: bool = True


def default_factor_registry():
    specs = {
        "momentum_core": FactorSpec(
            factor_name="momentum_core",
            module_path="functions.feature_engineering",
            output_columns=("ret_1", "ret_5", "ret_10", "ret_20", "ret_60"),
            input_columns=("close",),
            category="price_return",
            status="stable",
        ),
        "moving_average_core": FactorSpec(
            factor_name="moving_average_core",
            module_path="functions.feature_engineering",
            output_columns=("ma_5", "ma_10", "ma_20", "ma_60", "ma_120"),
            input_columns=("close",),
            category="trend",
            status="stable",
        ),
        "volatility_core": FactorSpec(
            factor_name="volatility_core",
            module_path="functions.feature_engineering",
            output_columns=("volatility_10", "volatility_20", "volatility_60"),
            input_columns=("close",),
            category="risk",
            status="stable",
        ),
        "kline_shape_core": FactorSpec(
            factor_name="kline_shape_core",
            module_path="functions.feature_engineering",
            output_columns=("amplitude", "intraday_ret", "upper_shadow", "lower_shadow", "body_ratio"),
            input_columns=("open", "high", "low", "close"),
            category="pattern",
            status="stable",
        ),
        "amount_volume_core": FactorSpec(
            factor_name="amount_volume_core",
            module_path="functions.feature_engineering",
            output_columns=("amount_ma20", "amount_ratio_20", "volume_ma_5", "volume_ma_10", "volume_ma_20"),
            input_columns=("amount", "volume"),
            category="liquidity",
            status="stable",
        ),
        "ml_factor_score": FactorSpec(
            factor_name="ml_factor_score",
            module_path="functions.factors.factor_ml",
            output_columns=("score_ml",),
            input_columns=("close", "date", "symbol"),
            category="ml",
            status="experimental",
        ),
        "learning_factor_score": FactorSpec(
            factor_name="learning_factor_score",
            module_path="functions.factors.factor_learning",
            output_columns=("score_learning",),
            input_columns=("close", "date", "symbol"),
            category="ml",
            status="experimental",
        ),
    }
    return specs


def factor_registry_frame(registry=None):
    registry = registry or default_factor_registry()
    return pd.DataFrame([asdict(spec) for spec in registry.values()])


def get_factor_spec(factor_name, registry=None):
    registry = registry or default_factor_registry()
    return registry[factor_name]
