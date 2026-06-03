# -*- coding: utf-8 -*-
"""Versioned execution-model declaration used by reports and manifests."""
from dataclasses import asdict, dataclass

from config import (
    DATA_RESOLUTION_REQUIRED,
    EXECUTION_FEASIBILITY_RULE,
    EXECUTION_MODEL_VERSION,
    EXECUTION_PRICE_RULE,
    FALLBACK_PRICE_RULE,
    ORDER_TIME_RULE,
    SIGNAL_TIME_RULE,
)


@dataclass(frozen=True)
class ExecutionModelSpec:
    execution_model_version: str
    signal_time_rule: str
    order_time_rule: str
    execution_price_rule: str
    execution_feasibility_rule: str
    fallback_price_rule: str
    data_resolution_required: str


def default_execution_model() -> ExecutionModelSpec:
    return ExecutionModelSpec(
        execution_model_version=EXECUTION_MODEL_VERSION,
        signal_time_rule=SIGNAL_TIME_RULE,
        order_time_rule=ORDER_TIME_RULE,
        execution_price_rule=EXECUTION_PRICE_RULE,
        execution_feasibility_rule=EXECUTION_FEASIBILITY_RULE,
        fallback_price_rule=FALLBACK_PRICE_RULE,
        data_resolution_required=DATA_RESOLUTION_REQUIRED,
    )


def execution_model_snapshot() -> dict:
    return asdict(default_execution_model())
