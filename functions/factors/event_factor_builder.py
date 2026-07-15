"""Structured event and event-proxy factor builder."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.data.pit_level2_store import validate_pit_level2_frame


EVENT_FACTOR_COLUMNS = [
    "earnings_forecast_positive",
    "earnings_forecast_negative",
    "dividend_or_bonus_plan",
    "buyback_announcement",
    "shareholder_increase",
    "shareholder_decrease",
    "st_risk_event",
    "limit_up_event",
    "limit_down_event",
    "limit_up_open_break",
    "consecutive_limit_up",
    "long_upper_shadow_event",
    "long_lower_shadow_event",
    "announcement_density",
    "volume_attention_spike",
    "turnover_attention_spike",
    "industry_heat_spread",
]


def build_event_daily_features(events: pd.DataFrame, trade_calendar, *, output_dir: str | Path | None = None) -> pd.DataFrame:
    if events is None:
        events = pd.DataFrame()
    calendar = pd.DataFrame({"trade_date": pd.to_datetime(pd.Series(trade_calendar), errors="coerce").dropna().sort_values().unique()})
    columns = ["stock_code", "trade_date", *EVENT_FACTOR_COLUMNS]
    if events.empty or calendar.empty:
        out = pd.DataFrame(columns=columns)
        _save_event_reports(out, events, output_dir)
        return out
    is_level2 = {"symbol", "event_id", "known_at", "effective_from"}.issubset(events.columns)
    if is_level2:
        audit = validate_pit_level2_frame(events, table_name="corporate_event_pit")
        failed = audit[~audit["passed"].fillna(False).astype(bool)]
        if not failed.empty:
            detail = "; ".join(f"{row.check}:{row.detail}" for row in failed.itertuples())
            raise ValueError(f"corporate_event_pit validation failed: {detail}")
        data = events.rename(
            columns={
                "symbol": "stock_code",
                "announcement_time": "publish_time",
                "effective_from": "available_date",
                "direction": "event_direction",
                "strength": "event_strength",
            }
        ).copy()
    else:
        data = events.copy()
    required = {"stock_code", "event_type"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Events missing columns: {missing}")
    data["stock_code"] = data["stock_code"].astype(str)
    data["event_date"] = pd.to_datetime(data.get("event_date"), errors="coerce")
    available = pd.to_datetime(data.get("available_date"), errors="coerce")
    publish = (
        pd.to_datetime(data.get("publish_time"), errors="coerce")
        if "publish_time" in data.columns
        else pd.Series(pd.NaT, index=data.index)
    )
    data["available_date"] = available.fillna(publish).fillna(data["event_date"])
    if is_level2 and data["available_date"].isna().any():
        raise ValueError("corporate_event_pit contains rows without effective_from")
    rows = []
    event_groups = (
        data.sort_values(["stock_code", "event_id", "available_date", "revision_id"])
        .groupby(["stock_code", "event_id"], sort=False)
        if "event_id" in data.columns
        else ((None, data),)
    )
    for _, revisions in event_groups:
        revisions = revisions.reset_index(drop=True)
        for revision_index, event in revisions.iterrows():
            if bool(event.get("cancelled", False)):
                continue
            next_effective = (
                pd.Timestamp(revisions.iloc[revision_index + 1]["available_date"])
                if revision_index + 1 < len(revisions) else None
            )
            rows.extend(_event_revision_rows(event, calendar, stop_before=next_effective))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=columns)
    if not out.empty:
        out = out.groupby(["stock_code", "trade_date"], as_index=False)[EVENT_FACTOR_COLUMNS].sum()
    for column in columns:
        if column not in out.columns:
            out[column] = pd.NA
    out = out[columns]
    _save_event_reports(out, data, output_dir)
    return out


def _event_revision_rows(event: pd.Series, calendar: pd.DataFrame, *, stop_before=None) -> list[pd.DataFrame]:
    rows = []
    if pd.isna(event.get("available_date")):
        return rows
    half_life = float(event.get("decay_half_life", 5) or 5)
    strength = float(event.get("event_strength", 1) or 1)
    stage_weight = {
        "plan": 0.7, "announced": 0.7, "implementation": 1.0,
        "progress": 0.8, "completed": 0.6,
    }.get(str(event.get("event_stage", "")).strip().lower(), 1.0)
    start = pd.Timestamp(event["available_date"])
    end = start + pd.Timedelta(days=max(30, half_life * 6))
    if stop_before is not None and pd.notna(stop_before):
        end = min(end, pd.Timestamp(stop_before) - pd.Timedelta(nanoseconds=1))
    window = calendar[(calendar["trade_date"] >= start) & (calendar["trade_date"] <= end)].copy()
    if window.empty:
        return rows
    day_index = range(len(window))
    decay = pd.Series(day_index, index=window.index).map(
        lambda x: 0.5 ** (float(x) / max(half_life, 1.0))
    )
    payload = pd.DataFrame({"stock_code": event["stock_code"], "trade_date": window["trade_date"]})
    for column in EVENT_FACTOR_COLUMNS:
        payload[column] = 0.0
    target = _event_column(str(event.get("event_type", "")), str(event.get("event_direction", "")))
    if target in payload.columns:
        payload[target] = strength * stage_weight * decay.to_numpy()
    rows.append(payload)
    return rows


def _event_column(event_type: str, direction: str) -> str:
    text = f"{event_type}|{direction}".lower()
    if "forecast" in text or "earnings_guidance" in text:
        return "earnings_forecast_negative" if any(
            token in text for token in ("negative", "down", "loss", "cut")
        ) else "earnings_forecast_positive"
    mapping = [
        ("dividend_or_bonus_plan", ("dividend", "bonus")),
        ("buyback_announcement", ("buyback",)),
        ("shareholder_increase", ("increase",)),
        ("shareholder_decrease", ("decrease",)),
        ("st_risk_event", ("st", "risk")),
        ("limit_up_open_break", ("limit_up_open_break",)),
        ("consecutive_limit_up", ("consecutive_limit_up",)),
        ("limit_up_event", ("limit_up",)),
        ("limit_down_event", ("limit_down",)),
        ("long_upper_shadow_event", ("upper_shadow",)),
        ("long_lower_shadow_event", ("lower_shadow",)),
        ("announcement_density", ("announcement",)),
        ("volume_attention_spike", ("volume_attention",)),
        ("turnover_attention_spike", ("turnover_attention",)),
        ("industry_heat_spread", ("industry_heat",)),
    ]
    for column, tokens in mapping:
        if any(token in text for token in tokens):
            return column
    return "announcement_density"


def _save_event_reports(features: pd.DataFrame, events: pd.DataFrame, output_dir: str | Path | None) -> None:
    if output_dir is None:
        return
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "event_rows": int(len(events)),
                "feature_rows": int(len(features)),
                "feature_columns": len(EVENT_FACTOR_COLUMNS),
            }
        ]
    ).to_csv(output / "event_feature_build_report.csv", index=False, encoding="utf-8-sig")
