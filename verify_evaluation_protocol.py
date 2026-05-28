# -*- coding: utf-8 -*-
import pandas as pd

from config import VALIDATION_MAX_ATTEMPTS
from functions.evaluation.evaluation_protocol import (
    build_protocol_snapshot,
    can_promote_to_test,
    default_protocol,
    validate_protocol,
)
from functions.evaluation.model_lifecycle import (
    freeze_candidate_for_test,
    register_research_idea,
    register_validation_attempt,
)
from functions.evaluation.walk_forward import build_walk_forward_splits, splits_to_frame


def verify_evaluation_protocol():
    failures: list[str] = []
    print("=== Verify evaluation protocol ===")

    protocol = default_protocol()
    snapshot = build_protocol_snapshot(protocol)
    required_snapshot_keys = {
        "train_periods",
        "validation_periods",
        "test_periods",
        "step_periods",
        "purge_periods",
        "embargo_periods",
        "validation_max_attempts",
        "test_lock_enabled",
    }
    missing_keys = sorted(required_snapshot_keys - set(snapshot))
    if missing_keys:
        failures.append(f"protocol snapshot missing keys: {missing_keys}")
        print(f"[FAIL] protocol snapshot missing keys: {missing_keys}")
    else:
        print("[PASS] protocol snapshot keys present")

    protocol_failures = validate_protocol(protocol)
    if protocol_failures:
        failures.extend(protocol_failures)
        print(f"[FAIL] protocol validation failures: {protocol_failures}")
    else:
        print("[PASS] protocol validation passed")

    dates = pd.bdate_range("2020-01-01", periods=500)
    splits = build_walk_forward_splits(dates, protocol)
    if not splits:
        failures.append("walk-forward splits should not be empty for 500 business days")
        print("[FAIL] walk-forward splits should not be empty for 500 business days")
    else:
        print(f"[PASS] walk-forward splits generated: {len(splits)}")
        split_frame = splits_to_frame(splits)
        if split_frame.empty:
            failures.append("split frame should not be empty")
            print("[FAIL] split frame should not be empty")
        else:
            print("[PASS] split frame generated")

        first_split = splits[0]
        train_end = pd.Timestamp(first_split.train_end)
        validation_start = pd.Timestamp(first_split.validation_start)
        test_start = pd.Timestamp(first_split.test_start)
        validation_end = pd.Timestamp(first_split.validation_end)

        purge_gap = len(pd.bdate_range(train_end, validation_start)) - 2
        embargo_gap = len(pd.bdate_range(validation_end, test_start)) - 2
        if purge_gap != protocol.purge_periods:
            failures.append(
                f"purge gap mismatch: expected {protocol.purge_periods}, got {purge_gap}"
            )
            print(f"[FAIL] purge gap mismatch: expected {protocol.purge_periods}, got {purge_gap}")
        else:
            print("[PASS] purge gap respected")

        if embargo_gap != protocol.embargo_periods:
            failures.append(
                f"embargo gap mismatch: expected {protocol.embargo_periods}, got {embargo_gap}"
            )
            print(f"[FAIL] embargo gap mismatch: expected {protocol.embargo_periods}, got {embargo_gap}")
        else:
            print("[PASS] embargo gap respected")

    idea = register_research_idea("idea_alpha", baseline_at_attempt_start="ml_xgboost")
    if idea.status != "active":
        failures.append(f"new idea should start active, got {idea.status}")
        print(f"[FAIL] new idea should start active, got {idea.status}")
    else:
        print("[PASS] new idea starts active")

    current_idea = idea
    last_attempt = None
    for _ in range(VALIDATION_MAX_ATTEMPTS):
        current_idea, last_attempt = register_validation_attempt(current_idea)
    if current_idea.validation_attempt_count != VALIDATION_MAX_ATTEMPTS:
        failures.append("validation attempt count did not increment as expected")
        print("[FAIL] validation attempt count did not increment as expected")
    else:
        print("[PASS] validation attempt count increments correctly")

    if current_idea.status != "attempt_limit_reached":
        failures.append(f"expected attempt_limit_reached, got {current_idea.status}")
        print(f"[FAIL] expected attempt_limit_reached, got {current_idea.status}")
    else:
        print("[PASS] attempt limit status reached")

    frozen_idea = freeze_candidate_for_test(idea)
    if not can_promote_to_test(frozen_idea, protocol):
        failures.append("frozen idea should be promotable to test")
        print("[FAIL] frozen idea should be promotable to test")
    else:
        print("[PASS] frozen idea promotable to test")

    if last_attempt is None or last_attempt.stage != "validation":
        failures.append("last attempt missing or wrong stage")
        print("[FAIL] last attempt missing or wrong stage")
    else:
        print("[PASS] validation attempt structure generated")

    print()
    if failures:
        print("Evaluation protocol verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Evaluation protocol verification passed.")


if __name__ == "__main__":
    verify_evaluation_protocol()
