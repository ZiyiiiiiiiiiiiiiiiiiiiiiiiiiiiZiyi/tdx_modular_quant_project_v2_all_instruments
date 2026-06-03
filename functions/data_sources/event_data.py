# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import EVENT_DATA_PARQUET, EVENT_DATA_QUALITY_CSV
from functions.data_sources.code_mapping import build_code_mapping_frame


REQUIRED_EVENT_DATA_COLUMNS = [
    "source_name",
    "external_code",
    "symbol",
    "market",
    "code",
    "event_date",
    "event_type",
    "event_title",
    "notes",
]


def normalize_event_data(raw_df, source_name="manual_csv"):
    data = raw_df.copy()
    if data.empty:
        return pd.DataFrame(columns=REQUIRED_EVENT_DATA_COLUMNS)

    mapping_df = build_code_mapping_frame(data.to_dict("records"), source_name=source_name).reset_index(drop=True)
    data = data.reset_index(drop=True)
    normalized = pd.DataFrame(
        {
            "source_name": source_name,
            "external_code": mapping_df["external_code"],
            "symbol": mapping_df["symbol"],
            "market": mapping_df["market"],
            "code": mapping_df["code"],
            "event_date": pd.to_datetime(data.get("event_date"), errors="coerce"),
            "event_type": data.get("event_type", pd.Series(dtype=object)).fillna("").astype(str),
            "event_title": data.get("event_title", pd.Series(dtype=object)).fillna("").astype(str),
            "notes": data.get("notes", pd.Series(dtype=object)).fillna("").astype(str),
        }
    )
    return normalized[REQUIRED_EVENT_DATA_COLUMNS].copy()


def save_event_data(event_df, output_path=EVENT_DATA_PARQUET):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    event_df.to_parquet(output_file, index=False)
    return output_file


def save_event_data_quality_report(event_df, output_path=EVENT_DATA_QUALITY_CSV):
    report = pd.DataFrame(
        {
            "metric": ["rows", "symbol_count", "event_type_count"],
            "value": [
                int(len(event_df)),
                int(event_df["symbol"].dropna().nunique()) if not event_df.empty else 0,
                int(event_df["event_type"].replace("", pd.NA).dropna().nunique()) if not event_df.empty else 0,
            ],
        }
    )
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file
