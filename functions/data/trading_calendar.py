"""Exchange-session calendar backed by observed market dates."""
from __future__ import annotations

import pandas as pd


def bounded_observed_feature_end(
    feature_path,
    start_date,
    end_date,
    max_days: int | None,
) -> pd.Timestamp:
    """Return the last observed session needed for a bounded date loop."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if max_days is None:
        return end
    limit = int(max_days)
    if limit <= 0:
        raise ValueError("max_days must be a positive integer")

    probe_days = max(31, limit * 3)
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
        if len(sessions) >= limit:
            return min(end, pd.Timestamp(sessions[limit - 1]))
        if probe_end >= end:
            return end
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
