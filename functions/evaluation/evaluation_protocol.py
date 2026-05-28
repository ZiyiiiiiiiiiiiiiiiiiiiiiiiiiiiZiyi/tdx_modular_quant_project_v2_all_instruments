# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass

from config import (
    TEST_LOCK_ENABLED,
    VALIDATION_MAX_ATTEMPTS,
    WALK_FORWARD_EMBARGO_PERIODS,
    WALK_FORWARD_PURGE_PERIODS,
    WALK_FORWARD_STEP_PERIODS,
    WALK_FORWARD_TEST_PERIODS,
    WALK_FORWARD_TRAIN_PERIODS,
    WALK_FORWARD_VALIDATION_PERIODS,
)


@dataclass(frozen=True)
class EvaluationProtocol:
    train_periods: int
    validation_periods: int
    test_periods: int
    step_periods: int
    purge_periods: int
    embargo_periods: int
    validation_max_attempts: int
    test_lock_enabled: bool


def default_protocol():
    return EvaluationProtocol(
        train_periods=WALK_FORWARD_TRAIN_PERIODS,
        validation_periods=WALK_FORWARD_VALIDATION_PERIODS,
        test_periods=WALK_FORWARD_TEST_PERIODS,
        step_periods=WALK_FORWARD_STEP_PERIODS,
        purge_periods=WALK_FORWARD_PURGE_PERIODS,
        embargo_periods=WALK_FORWARD_EMBARGO_PERIODS,
        validation_max_attempts=VALIDATION_MAX_ATTEMPTS,
        test_lock_enabled=TEST_LOCK_ENABLED,
    )


def build_protocol_snapshot(protocol=None):
    protocol = protocol or default_protocol()
    return asdict(protocol)


def validate_protocol(protocol=None):
    protocol = protocol or default_protocol()
    failures = []
    numeric_fields = [
        "train_periods",
        "validation_periods",
        "test_periods",
        "step_periods",
        "purge_periods",
        "embargo_periods",
        "validation_max_attempts",
    ]
    for field_name in numeric_fields:
        value = getattr(protocol, field_name)
        if not isinstance(value, int) or value <= 0:
            failures.append(f"{field_name} must be a positive integer")

    if protocol.step_periods > protocol.validation_periods:
        failures.append("step_periods cannot exceed validation_periods")
    if protocol.purge_periods >= protocol.train_periods:
        failures.append("purge_periods must be smaller than train_periods")
    if protocol.validation_max_attempts < 1:
        failures.append("validation_max_attempts must be at least 1")

    return failures


def can_promote_to_test(idea_state, protocol=None):
    protocol = protocol or default_protocol()
    if not protocol.test_lock_enabled:
        return True
    return idea_state.status == "frozen_for_test"
