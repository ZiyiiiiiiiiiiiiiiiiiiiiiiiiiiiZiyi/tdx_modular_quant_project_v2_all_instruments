# -*- coding: utf-8 -*-
"""Shared date-window validation for selection, backtest, and reporting."""
from __future__ import annotations

import pandas as pd


def normalize_date_window(start_date=None, end_date=None):
    start = pd.Timestamp(start_date).normalize() if start_date is not None else None
    end = pd.Timestamp(end_date).normalize() if end_date is not None else None
    if start is not None and end is not None and start > end:
        raise ValueError(f"Invalid date window: start_date {start.date()} is after end_date {end.date()}")
    return start, end


def filter_date_window(df, date_col, start_date=None, end_date=None):
    """Return a copy strictly limited to the configured inclusive date window."""
    start, end = normalize_date_window(start_date, end_date)
    data = df.copy()
    if date_col not in data.columns:
        if data.empty:
            return data
        raise ValueError(f"Date-window filtering requires column: {date_col}")
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    if data[date_col].isna().any():
        raise ValueError(f"Column {date_col} contains invalid dates")
    if start is not None:
        data = data[data[date_col] >= start]
    if end is not None:
        data = data[data[date_col] <= end]
    return data.copy()


def assert_date_window(df, date_col, start_date=None, end_date=None, label="data"):
    """Fail when a non-empty artifact contains rows outside its configured window."""
    start, end = normalize_date_window(start_date, end_date)
    if df.empty:
        return
    if date_col not in df.columns:
        raise ValueError(f"{label} is missing required date column: {date_col}")
    dates = pd.to_datetime(df[date_col], errors="coerce")
    if dates.isna().any():
        raise ValueError(f"{label} contains invalid values in {date_col}")
    actual_start = dates.min().normalize()
    actual_end = dates.max().normalize()
    if start is not None and actual_start < start:
        raise ValueError(
            f"{label} starts at {actual_start.date()}, before configured start {start.date()}"
        )
    if end is not None and actual_end > end:
        raise ValueError(
            f"{label} ends at {actual_end.date()}, after configured end {end.date()}"
        )


def window_identity(start_date=None, end_date=None):
    start, end = normalize_date_window(start_date, end_date)
    return {
        "start_date": start.date().isoformat() if start is not None else None,
        "end_date": end.date().isoformat() if end is not None else None,
    }


def generate_calendar_windows(start_date, end_date, *, window_months: int, step_months: int):
    start, end = normalize_date_window(start_date, end_date)
    if start is None or end is None:
        raise ValueError("generate_calendar_windows requires explicit start_date and end_date")
    if int(window_months) <= 0 or int(step_months) <= 0:
        raise ValueError("window_months and step_months must be positive")

    windows = []
    cursor = start
    while cursor <= end:
        window_end = (cursor + pd.DateOffset(months=int(window_months))) - pd.Timedelta(days=1)
        if window_end > end:
            window_end = end
        windows.append(
            {
                "window_id": f"{cursor.date().isoformat()}__{window_end.date().isoformat()}",
                "start_date": cursor.date().isoformat(),
                "end_date": window_end.date().isoformat(),
            }
        )
        next_cursor = cursor + pd.DateOffset(months=int(step_months))
        next_cursor = pd.Timestamp(next_cursor).normalize()
        if next_cursor <= cursor:
            raise ValueError("step_months did not advance the rolling window cursor")
        cursor = next_cursor
        if cursor > end:
            break
    return windows
