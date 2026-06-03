# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import (
    CORPORATE_ACTIONS_PARQUET,
    CORPORATE_ACTIONS_QUALITY_CSV,
    DEFAULT_CORPORATE_ACTIONS_SOURCE,
)
from functions.data_sources.code_mapping import build_code_mapping_frame


REQUIRED_CORPORATE_ACTION_COLUMNS = [
    "source_name",
    "external_code",
    "symbol",
    "market",
    "code",
    "action_date",
    "action_type",
    "cash_dividend",
    "stock_dividend_ratio",
    "rights_issue_ratio",
    "rights_issue_price",
    "notes",
]


def load_corporate_actions(source_path, source_name=DEFAULT_CORPORATE_ACTIONS_SOURCE):
    file_path = Path(source_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Corporate actions source not found: {file_path}")

    if file_path.suffix.lower() == ".csv":
        raw = pd.read_csv(file_path)
    elif file_path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(file_path)
    else:
        raise ValueError(f"Unsupported corporate actions source: {file_path.suffix}")

    return normalize_corporate_actions(raw, source_name=source_name)


def normalize_corporate_actions(raw_df, source_name=DEFAULT_CORPORATE_ACTIONS_SOURCE):
    data = raw_df.copy()
    if data.empty:
        return pd.DataFrame(columns=REQUIRED_CORPORATE_ACTION_COLUMNS)

    records = data.to_dict("records")
    mapping_df = build_code_mapping_frame(records, source_name=source_name)
    data = data.reset_index(drop=True)
    mapping_df = mapping_df.reset_index(drop=True)

    normalized = pd.DataFrame(
        {
            "source_name": source_name,
            "external_code": mapping_df["external_code"],
            "symbol": mapping_df["symbol"],
            "market": mapping_df["market"],
            "code": mapping_df["code"],
            "action_date": pd.to_datetime(data.get("action_date"), errors="coerce"),
            "action_type": data.get("action_type", pd.Series(dtype=object)).astype(str),
            "cash_dividend": pd.to_numeric(data.get("cash_dividend"), errors="coerce"),
            "stock_dividend_ratio": pd.to_numeric(data.get("stock_dividend_ratio"), errors="coerce"),
            "rights_issue_ratio": pd.to_numeric(data.get("rights_issue_ratio"), errors="coerce"),
            "rights_issue_price": pd.to_numeric(data.get("rights_issue_price"), errors="coerce"),
            "notes": data.get("notes", pd.Series(dtype=object)).fillna("").astype(str),
        }
    )

    for col in REQUIRED_CORPORATE_ACTION_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = pd.NA
    return normalized[REQUIRED_CORPORATE_ACTION_COLUMNS].copy()


def save_corporate_actions(actions_df, output_path=CORPORATE_ACTIONS_PARQUET):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    actions_df.to_parquet(output_file, index=False)
    return output_file


def build_corporate_actions_quality_report(actions_df):
    if actions_df.empty:
        return pd.DataFrame(
            {
                "metric": [
                    "rows",
                    "symbol_count",
                    "missing_symbol_rows",
                    "missing_action_date_rows",
                    "missing_action_type_rows",
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
                "missing_action_date_rows",
                "missing_action_type_rows",
            ],
            "value": [
                int(len(actions_df)),
                int(actions_df["symbol"].dropna().nunique()),
                int(actions_df["symbol"].isna().sum()),
                int(actions_df["action_date"].isna().sum()),
                int(actions_df["action_type"].astype(str).str.strip().eq("").sum()),
            ],
        }
    )


def save_corporate_actions_quality_report(
    actions_df,
    output_path=CORPORATE_ACTIONS_QUALITY_CSV,
):
    report = build_corporate_actions_quality_report(actions_df)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file
