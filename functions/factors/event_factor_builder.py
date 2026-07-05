"""Structured event and event-proxy factor builder."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


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
    required = {"stock_code", "event_type"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"Events missing columns: {missing}")
    data = events.copy()
    data["stock_code"] = data["stock_code"].astype(str)
    data["event_date"] = pd.to_datetime(data.get("event_date"), errors="coerce")
    available = pd.to_datetime(data.get("available_date"), errors="coerce")
    publish = (
        pd.to_datetime(data.get("publish_time"), errors="coerce")
        if "publish_time" in data.columns
        else pd.Series(pd.NaT, index=data.index)
    )
    data["available_date"] = available.fillna(publish).fillna(data["event_date"])
    rows = []
    for _, event in data.dropna(subset=["available_date"]).iterrows():
        half_life = float(event.get("decay_half_life", 5) or 5)
        strength = float(event.get("event_strength", 1) or 1)
        window = calendar[(calendar["trade_date"] >= event["available_date"]) & (calendar["trade_date"] <= event["available_date"] + pd.Timedelta(days=max(30, half_life * 6)))].copy()
        if window.empty:
            continue
        day_index = range(len(window))
        decay = pd.Series(day_index, index=window.index).map(lambda x: 0.5 ** (float(x) / max(half_life, 1.0)))
        payload = pd.DataFrame({"stock_code": event["stock_code"], "trade_date": window["trade_date"]})
        for column in EVENT_FACTOR_COLUMNS:
            payload[column] = 0.0
        target = _event_column(str(event.get("event_type", "")), str(event.get("event_direction", "")))
        if target in payload.columns:
            payload[target] = strength * decay.to_numpy()
        rows.append(payload)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=columns)
    if not out.empty:
        out = out.groupby(["stock_code", "trade_date"], as_index=False)[EVENT_FACTOR_COLUMNS].sum()
    for column in columns:
        if column not in out.columns:
            out[column] = pd.NA
    out = out[columns]
    _save_event_reports(out, data, output_dir)
    return out


def _event_column(event_type: str, direction: str) -> str:
    text = f"{event_type}|{direction}".lower()
    mapping = [
        ("earnings_forecast_positive", ("forecast", "positive")),
        ("earnings_forecast_negative", ("forecast", "negative")),
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
