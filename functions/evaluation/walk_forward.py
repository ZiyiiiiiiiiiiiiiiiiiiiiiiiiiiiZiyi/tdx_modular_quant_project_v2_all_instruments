# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass

import pandas as pd

from functions.evaluation.evaluation_protocol import default_protocol


@dataclass(frozen=True)
class WalkForwardSplit:
    split_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    purge_periods: int
    embargo_periods: int


def build_walk_forward_splits(dates, protocol=None):
    protocol = protocol or default_protocol()
    unique_dates = pd.Index(pd.to_datetime(pd.Series(dates).dropna().unique())).sort_values()
    required = (
        protocol.train_periods
        + protocol.purge_periods
        + protocol.validation_periods
        + protocol.embargo_periods
        + protocol.test_periods
    )
    if len(unique_dates) < required:
        return []

    splits = []
    start_idx = 0
    split_number = 1
    while True:
        train_start_idx = start_idx
        train_end_idx = train_start_idx + protocol.train_periods - 1
        validation_start_idx = train_end_idx + 1 + protocol.purge_periods
        validation_end_idx = validation_start_idx + protocol.validation_periods - 1
        test_start_idx = validation_end_idx + 1 + protocol.embargo_periods
        test_end_idx = test_start_idx + protocol.test_periods - 1

        if test_end_idx >= len(unique_dates):
            break

        split = WalkForwardSplit(
            split_id=f"wf_{split_number:03d}",
            train_start=unique_dates[train_start_idx].date().isoformat(),
            train_end=unique_dates[train_end_idx].date().isoformat(),
            validation_start=unique_dates[validation_start_idx].date().isoformat(),
            validation_end=unique_dates[validation_end_idx].date().isoformat(),
            test_start=unique_dates[test_start_idx].date().isoformat(),
            test_end=unique_dates[test_end_idx].date().isoformat(),
            purge_periods=protocol.purge_periods,
            embargo_periods=protocol.embargo_periods,
        )
        splits.append(split)
        split_number += 1
        start_idx += protocol.step_periods

    return splits


def splits_to_frame(splits):
    return pd.DataFrame([asdict(item) for item in splits])
