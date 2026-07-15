"""Verify event revisions, cancellation, direction, and effective timing."""
from __future__ import annotations

import pandas as pd

from functions.factors.event_factor_builder import build_event_daily_features


def _event(event_id, event_type, effective, revision, *, cancelled=False, direction="positive"):
    known = pd.Timestamp(effective) - pd.Timedelta(hours=8)
    return {
        "symbol": "sh600000", "event_id": event_id, "event_type": event_type,
        "event_stage": "announced", "announcement_time": known, "known_at": known,
        "effective_from": pd.Timestamp(effective), "source": "verify",
        "source_document_id": f"doc-{event_id}-{revision}", "revision_id": revision,
        "downloaded_at": pd.Timestamp(effective), "direction": direction, "strength": 1.0,
        "cancelled": cancelled, "revision_of": "" if revision == "v1" else "v1",
    }


def main() -> int:
    events = pd.DataFrame([
        _event("buyback-1", "buyback", "2024-01-03", "v1"),
        _event("buyback-1", "buyback", "2024-01-08", "v2", cancelled=True),
        _event("forecast-1", "earnings_forecast", "2024-01-04", "v1", direction="negative"),
    ])
    calendar = pd.bdate_range("2024-01-02", "2024-01-15")
    out = build_event_daily_features(events, calendar)
    assert out.loc[out["trade_date"].lt(pd.Timestamp("2024-01-03")), "buyback_announcement"].eq(0).all()
    assert out.loc[out["trade_date"].ge(pd.Timestamp("2024-01-08")), "buyback_announcement"].eq(0).all()
    assert out["earnings_forecast_negative"].gt(0).any()
    assert not out["earnings_forecast_positive"].gt(0).any()
    print("[PASS] PIT event timing, revision cancellation, and forecast direction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
