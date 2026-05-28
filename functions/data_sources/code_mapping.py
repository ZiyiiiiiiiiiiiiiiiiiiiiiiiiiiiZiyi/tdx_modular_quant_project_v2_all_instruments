# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import CODE_MAPPING_CSV


REQUIRED_CODE_MAPPING_COLUMNS = [
    "source_name",
    "external_code",
    "market",
    "code",
    "symbol",
    "mapping_status",
]


def normalize_external_code(external_code):
    return str(external_code).strip().upper()


def parse_external_symbol(external_code, market=None, code=None):
    raw = normalize_external_code(external_code)
    compact = raw.replace(".", "").replace("_", "").replace("-", "")
    parsed_market = str(market or "").strip().lower()
    parsed_code = str(code or "").strip()
    if compact[:2] in {"SH", "SZ", "BJ"} and compact[2:].isdigit():
        parsed_market = parsed_market or compact[:2].lower()
        parsed_code = parsed_code or compact[2:]
    elif compact[-2:] in {"SH", "SZ", "BJ"} and compact[:-2].isdigit():
        parsed_market = parsed_market or compact[-2:].lower()
        parsed_code = parsed_code or compact[:-2]
    parsed_code = parsed_code.zfill(6) if parsed_code else ""
    return parsed_market, parsed_code


def build_symbol(market, code):
    market_value = str(market).strip().lower()
    code_value = str(code).strip().zfill(6)
    return f"{market_value}{code_value}"


def build_code_mapping_frame(records, source_name):
    rows = []
    for record in records:
        external_code = normalize_external_code(
            record.get("external_code", record.get("code", ""))
        )
        market, code = parse_external_symbol(
            external_code,
            market=record.get("market"),
            code=record.get("code"),
        )
        if market and code:
            symbol = build_symbol(market, code)
            mapping_status = "mapped"
        else:
            symbol = None
            mapping_status = "missing_market_or_code"

        rows.append(
            {
                "source_name": source_name,
                "external_code": external_code,
                "market": market,
                "code": code,
                "symbol": symbol,
                "mapping_status": mapping_status,
            }
        )

    if not rows:
        return pd.DataFrame(columns=REQUIRED_CODE_MAPPING_COLUMNS)

    frame = pd.DataFrame(rows)
    return frame[REQUIRED_CODE_MAPPING_COLUMNS].copy()


def save_code_mapping_report(mapping_df, output_path=CODE_MAPPING_CSV):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    mapping_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file


def summarize_code_mapping(mapping_df):
    if mapping_df.empty:
        return {
            "rows": 0,
            "mapped_rows": 0,
            "unmapped_rows": 0,
        }

    mapped_mask = mapping_df["mapping_status"] == "mapped"
    return {
        "rows": int(len(mapping_df)),
        "mapped_rows": int(mapped_mask.sum()),
        "unmapped_rows": int((~mapped_mask).sum()),
    }
