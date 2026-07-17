"""Read a post-decision price tail that is isolated from strategy decisions."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_audit_price_history(
    feature_path: str | Path,
    *,
    decision_start,
    decision_end,
    horizon_days: int = 20,
    allowed_instrument_types=(),
) -> pd.DataFrame:
    """Load nominal closes through the requested outcome horizon.

    The returned frame must be passed only to post-run audit builders.  The
    decision runner continues to receive the bounded feature frame, preventing
    future observations from entering candidate construction or execution.
    """
    path = Path(feature_path)
    start = pd.Timestamp(decision_start).normalize()
    end = pd.Timestamp(decision_end).normalize()
    horizon = max(int(horizon_days), 1)
    probe_days = max(45, horizon * 3)
    sessions = pd.DatetimeIndex([])
    probe_end = end
    for _ in range(6):
        probe_end = end + pd.Timedelta(days=probe_days)
        observed = pd.read_parquet(
            path,
            columns=["date"],
            filters=[("date", ">", end), ("date", "<=", probe_end)],
        )
        sessions = pd.DatetimeIndex(
            pd.to_datetime(observed["date"], errors="coerce")
            .dropna()
            .drop_duplicates()
            .sort_values()
        )
        if len(sessions) >= horizon:
            probe_end = pd.Timestamp(sessions[horizon - 1])
            break
        probe_days *= 2
    if len(sessions) and len(sessions) < horizon:
        probe_end = pd.Timestamp(sessions[-1])

    try:
        import pyarrow.parquet as pq

        available = set(pq.read_schema(path).names)
    except Exception:
        available = {"date", "symbol", "close", "close_nominal", "instrument_type"}
    price_column = "close_nominal" if "close_nominal" in available else "close"
    columns = ["date", "symbol", price_column]
    filters = [("date", ">=", start), ("date", "<=", probe_end)]
    if allowed_instrument_types and "instrument_type" in available:
        columns.append("instrument_type")
        load_types = tuple(dict.fromkeys((*allowed_instrument_types, "etf_fund")))
        filters.append(("instrument_type", "in", list(load_types)))
    prices = pd.read_parquet(path, columns=columns, filters=filters)
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["symbol"] = prices["symbol"].astype(str)
    prices["close"] = pd.to_numeric(prices[price_column], errors="coerce")
    prices = (
        prices[["date", "symbol", "close"]]
        .dropna(subset=["date", "symbol", "close"])
        .drop_duplicates(["date", "symbol"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    prices.attrs.update({
        "decision_start": str(start.date()),
        "decision_end": str(end.date()),
        "audit_end": str(pd.Timestamp(probe_end).date()),
        "requested_horizon_days": horizon,
        "available_future_sessions": int(len(sessions)),
    })
    return prices

