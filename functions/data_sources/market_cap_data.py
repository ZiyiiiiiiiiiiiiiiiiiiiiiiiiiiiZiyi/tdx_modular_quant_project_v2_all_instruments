# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import MARKET_CAP_PARQUET, MARKET_CAP_QUALITY_CSV
from functions.data_sources.code_mapping import build_code_mapping_frame


REQUIRED_MARKET_CAP_COLUMNS = [
    "source_name",
    "external_code",
    "symbol",
    "market",
    "code",
    "date",
    "total_cap",
    "float_cap",
    "market_cap_jump_flag",
    "float_cap_jump_flag",
    "jump_event_type",
    "stabilized_total_cap",
    "stabilized_float_cap",
]


def normalize_market_cap_history(raw_df, source_name="manual_csv"):
    data = raw_df.copy()
    if data.empty:
        return pd.DataFrame(columns=REQUIRED_MARKET_CAP_COLUMNS)

    records = data.to_dict("records")
    mapping_df = build_code_mapping_frame(records, source_name=source_name).reset_index(drop=True)
    data = data.reset_index(drop=True)

    total_cap = pd.to_numeric(data.get("total_cap"), errors="coerce")
    float_cap = pd.to_numeric(data.get("float_cap"), errors="coerce")
    jump_event_type = data.get("jump_event_type", pd.Series(dtype=object)).fillna("").astype(str)

    normalized = pd.DataFrame(
        {
            "source_name": source_name,
            "external_code": mapping_df["external_code"],
            "symbol": mapping_df["symbol"],
            "market": mapping_df["market"],
            "code": mapping_df["code"],
            "date": pd.to_datetime(data.get("date"), errors="coerce"),
            "total_cap": total_cap,
            "float_cap": float_cap,
            "market_cap_jump_flag": _coerce_bool(
                data.get("market_cap_jump_flag"),
                index=data.index,
            ),
            "float_cap_jump_flag": _coerce_bool(
                data.get("float_cap_jump_flag"),
                index=data.index,
            ),
            "jump_event_type": jump_event_type,
            "stabilized_total_cap": pd.to_numeric(
                data.get("stabilized_total_cap", total_cap),
                errors="coerce",
            ),
            "stabilized_float_cap": pd.to_numeric(
                data.get("stabilized_float_cap", float_cap),
                errors="coerce",
            ),
        }
    )

    for col in REQUIRED_MARKET_CAP_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = pd.NA
    return normalized[REQUIRED_MARKET_CAP_COLUMNS].copy()


def detect_market_cap_jump_flags(market_cap_df, jump_ratio=0.30):
    if market_cap_df.empty:
        return market_cap_df.copy()

    frame = market_cap_df.sort_values(["symbol", "date"]).copy()
    total_prev = frame.groupby("symbol")["total_cap"].shift(1)
    float_prev = frame.groupby("symbol")["float_cap"].shift(1)

    total_ratio = (frame["total_cap"] - total_prev).abs() / total_prev.replace(0, pd.NA)
    float_ratio = (frame["float_cap"] - float_prev).abs() / float_prev.replace(0, pd.NA)

    frame["market_cap_jump_flag"] = frame["market_cap_jump_flag"] | total_ratio.ge(jump_ratio).fillna(False)
    frame["float_cap_jump_flag"] = frame["float_cap_jump_flag"] | float_ratio.ge(jump_ratio).fillna(False)
    return frame


def fill_stabilized_market_cap(market_cap_df):
    if market_cap_df.empty:
        return market_cap_df.copy()

    frame = market_cap_df.sort_values(["symbol", "date"]).copy()
    total_series = frame["stabilized_total_cap"].where(~frame["market_cap_jump_flag"], pd.NA)
    float_series = frame["stabilized_float_cap"].where(~frame["float_cap_jump_flag"], pd.NA)

    frame["stabilized_total_cap"] = (
        total_series.groupby(frame["symbol"]).ffill().fillna(frame["total_cap"])
    )
    frame["stabilized_float_cap"] = (
        float_series.groupby(frame["symbol"]).ffill().fillna(frame["float_cap"])
    )
    return frame


def save_market_cap_history(market_cap_df, output_path=MARKET_CAP_PARQUET):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    market_cap_df.to_parquet(output_file, index=False)
    return output_file


def build_market_cap_quality_report(market_cap_df):
    if market_cap_df.empty:
        return pd.DataFrame(
            {
                "metric": [
                    "rows",
                    "symbol_count",
                    "missing_symbol_rows",
                    "jump_rows",
                    "float_jump_rows",
                ],
                "value": [0, 0, 0, 0, 0],
            }
        )

    return pd.DataFrame(
        {
            "metric": [
                "rows",
                "symbol_count",
                "missing_symbol_rows",
                "jump_rows",
                "float_jump_rows",
            ],
            "value": [
                int(len(market_cap_df)),
                int(market_cap_df["symbol"].dropna().nunique()),
                int(market_cap_df["symbol"].isna().sum()),
                int(market_cap_df["market_cap_jump_flag"].fillna(False).sum()),
                int(market_cap_df["float_cap_jump_flag"].fillna(False).sum()),
            ],
        }
    )


def save_market_cap_quality_report(market_cap_df, output_path=MARKET_CAP_QUALITY_CSV):
    report = build_market_cap_quality_report(market_cap_df)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file


def _coerce_bool(series, index=None):
    if series is None:
        return pd.Series(False, index=index, dtype=bool)
    if not isinstance(series, pd.Series):
        series = pd.Series(series, index=index)
    elif index is not None:
        series = series.reindex(index)
    return series.fillna(False).astype(bool)
