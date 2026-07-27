"""Exchange-session calendar backed by observed market dates."""
from __future__ import annotations

import pandas as pd


def first_observed_feature_session(feature_path, start_date, end_date) -> pd.Timestamp:
    """Return the first stored market session within an inclusive window."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    observed = pd.read_parquet(
        feature_path,
        columns=["date"],
        filters=[("date", ">=", start), ("date", "<=", end)],
    )
    sessions = pd.to_datetime(observed["date"], errors="coerce").dropna()
    if sessions.empty:
        raise ValueError(f"No observed feature session in {start.date()}..{end.date()}")
    return pd.Timestamp(sessions.min()).normalize()


def bounded_observed_feature_end(
    feature_path,
    start_date,
    end_date,
    max_days: int | None,
) -> pd.Timestamp:
    """Return the last observed session needed for an inclusive date loop.

    Calendar month ends can fall on weekends or exchange holidays.  Returning
    the requested calendar date would incorrectly require PIT tables to cover
    non-trading days, so even unbounded windows are normalized to the last
    observed feature session inside the requested interval.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    limit = None if max_days is None else int(max_days)
    if limit is not None and limit <= 0:
        raise ValueError("max_days must be a positive integer")

    probe_days = max(31, (limit or 1) * 3)
    while True:
        probe_end = min(end, start + pd.Timedelta(days=probe_days))
        observed = pd.read_parquet(
            feature_path,
            columns=["date"],
            filters=[("date", ">=", start), ("date", "<=", probe_end)],
        )
        sessions = pd.DatetimeIndex(
            pd.to_datetime(observed["date"], errors="coerce").dropna().drop_duplicates().sort_values()
        )
        del observed
        if limit is not None and len(sessions) >= limit:
            return min(end, pd.Timestamp(sessions[limit - 1]))
        if probe_end >= end:
            if sessions.empty:
                raise ValueError(f"No observed feature session in {start.date()}..{end.date()}")
            return pd.Timestamp(sessions[-1]).normalize()
        probe_days *= 2


class TradingCalendar:
    def __init__(self, sessions) -> None:
        values = pd.to_datetime(pd.Series(sessions), errors="coerce").dropna().dt.normalize().unique()
        self.sessions = pd.DatetimeIndex(sorted(values))

    def next_session(self, date, *, required: bool = False):
        timestamp = pd.Timestamp(date).normalize()
        index = int(self.sessions.searchsorted(timestamp, side="right"))
        if index < len(self.sessions):
            return pd.Timestamp(self.sessions[index])
        if required:
            raise ValueError(f"No next trading session is available after {timestamp.date()}")
        return pd.NaT

    def previous_session(self, date, *, required: bool = False):
        timestamp = pd.Timestamp(date).normalize()
        index = int(self.sessions.searchsorted(timestamp, side="left")) - 1
        if index >= 0:
            return pd.Timestamp(self.sessions[index])
        if required:
            raise ValueError(f"No previous trading session is available before {timestamp.date()}")
        return pd.NaT

    def contains(self, date) -> bool:
        return pd.Timestamp(date).normalize() in self.sessions
