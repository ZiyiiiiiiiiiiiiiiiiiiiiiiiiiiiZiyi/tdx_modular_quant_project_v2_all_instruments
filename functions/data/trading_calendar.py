"""Exchange-session calendar backed by observed market dates."""
from __future__ import annotations

import pandas as pd


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
