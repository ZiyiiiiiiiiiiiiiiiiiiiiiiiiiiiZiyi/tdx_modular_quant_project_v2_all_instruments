# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import ADJUSTMENT_FACTORS_PARQUET, ADJUSTMENT_FACTORS_QUALITY_CSV
from functions.data_sources.code_mapping import build_code_mapping_frame


REQUIRED_ADJUSTMENT_FACTOR_COLUMNS = [
    "source_name",
    "symbol",
    "market",
    "code",
    "action_date",
    "action_type",
    "forward_factor",
    "backward_factor",
    "cash_dividend",
    "stock_dividend_ratio",
    "rights_issue_ratio",
    "rights_issue_price",
    "adj_factor_valid_from",
    "adj_factor_valid_to",
    "adj_factor_coverage_flag",
    "factor_source_validated",
]


def normalize_provider_adjustment_factors(raw_df, source_name="baostock_adjust_factor"):
    """Normalize factor values supplied by a data provider, without guessing them."""
    if raw_df.empty:
        return pd.DataFrame(columns=REQUIRED_ADJUSTMENT_FACTOR_COLUMNS)

    data = raw_df.reset_index(drop=True).copy()
    external_codes = data.get("external_code", data.get("code", pd.Series("", index=data.index)))
    mapping_source = pd.DataFrame({"external_code": external_codes})
    if "market" in data.columns:
        mapping_source["market"] = data["market"]
    if "symbol" in data.columns:
        mapping_source["market"] = data["symbol"].astype(str).str[:2]
        mapping_source["code"] = data["symbol"].astype(str).str[2:]
    mapping = build_code_mapping_frame(mapping_source.to_dict("records"), source_name)
    date_source = data.get("action_date", data.get("dividOperateDate", data.get("date")))
    forward_source = data.get("forward_factor", data.get("foreAdjustFactor"))
    backward_source = data.get("backward_factor", data.get("backAdjustFactor"))
    result = pd.DataFrame({
        "source_name": source_name,
        "symbol": mapping["symbol"],
        "market": mapping["market"],
        "code": mapping["code"],
        "action_date": pd.to_datetime(date_source, errors="coerce"),
        "action_type": data.get("action_type", pd.Series("provider_factor", index=data.index)),
        "forward_factor": pd.to_numeric(forward_source, errors="coerce"),
        "backward_factor": pd.to_numeric(backward_source, errors="coerce"),
        "cash_dividend": pd.to_numeric(data.get("cash_dividend"), errors="coerce"),
        "stock_dividend_ratio": pd.to_numeric(data.get("stock_dividend_ratio"), errors="coerce"),
        "rights_issue_ratio": pd.to_numeric(data.get("rights_issue_ratio"), errors="coerce"),
        "rights_issue_price": pd.to_numeric(data.get("rights_issue_price"), errors="coerce"),
    })
    coverage = _build_coverage_windows(result)
    result = result.merge(coverage, on="symbol", how="left")
    # Formal feature pricing consumes only the point-in-time backward factor.
    result["factor_source_validated"] = result["backward_factor"].gt(0)
    result["adj_factor_coverage_flag"] = result["action_date"].notna() & result["factor_source_validated"]
    return result[REQUIRED_ADJUSTMENT_FACTOR_COLUMNS].copy()


def build_adjustment_factors(actions_df):
    """Build only validated factors; event-only rows are not valid price factors."""
    if actions_df.empty:
        return pd.DataFrame(columns=REQUIRED_ADJUSTMENT_FACTOR_COLUMNS)
    data = actions_df.copy()
    if {"forward_factor", "backward_factor"}.issubset(data.columns):
        source_name = str(data["source_name"].iloc[0]) if "source_name" in data.columns else "provider"
        return normalize_provider_adjustment_factors(data, source_name=source_name)
    data["forward_factor"] = pd.NA
    data["backward_factor"] = pd.NA
    data["factor_source_validated"] = False
    data["adj_factor_coverage_flag"] = False
    data = data.merge(_build_coverage_windows(data), on="symbol", how="left")
    for col in REQUIRED_ADJUSTMENT_FACTOR_COLUMNS:
        if col not in data.columns:
            data[col] = pd.NA
    return data[REQUIRED_ADJUSTMENT_FACTOR_COLUMNS].copy()


def attach_adjustment_factors_to_daily(prices_df, factors_df):
    """Attach factor values available on or before each daily bar."""
    prices = prices_df.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    if factors_df.empty:
        prices["forward_factor"] = pd.NA
        prices["backward_factor"] = pd.NA
        prices["adj_factor_available"] = False
        return prices
    factors = factors_df[factors_df["factor_source_validated"].fillna(False)].copy()
    factors["action_date"] = pd.to_datetime(factors["action_date"], errors="coerce")
    factors = factors.dropna(subset=["symbol", "action_date"])
    if factors.empty:
        return attach_adjustment_factors_to_daily(prices, pd.DataFrame())
    attached_parts = []
    factor_columns = ["action_date", "forward_factor", "backward_factor"]
    factor_groups = {symbol: group.sort_values("action_date")[factor_columns]
                     for symbol, group in factors.groupby("symbol")}
    for symbol, bars in prices.groupby("symbol", sort=False):
        events = factor_groups.get(symbol)
        if events is None:
            part = bars.copy()
            part["forward_factor"] = pd.NA
            part["backward_factor"] = pd.NA
        else:
            part = pd.merge_asof(
                bars.sort_values("date"),
                events,
                left_on="date",
                right_on="action_date",
                direction="backward",
            ).drop(columns=["action_date"])
        attached_parts.append(part)
    attached = pd.concat(attached_parts, ignore_index=True)
    attached["adj_factor_available"] = attached["backward_factor"].notna()
    return attached.sort_values(["symbol", "date"]).reset_index(drop=True)


def _build_coverage_windows(data):
    return (
        data.groupby("symbol", dropna=False)
        .agg(
            adj_factor_valid_from=("action_date", "min"),
            adj_factor_valid_to=("action_date", "max"),
        )
        .reset_index()
    )


def save_adjustment_factors(factors_df, output_path=ADJUSTMENT_FACTORS_PARQUET):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    factors_df.to_parquet(output_file, index=False)
    return output_file


def build_adjustment_factors_quality_report(factors_df):
    if factors_df.empty:
        return pd.DataFrame(
            {
                "metric": [
                    "rows",
                    "symbol_count",
                    "missing_symbol_rows",
                    "missing_action_date_rows",
                    "coverage_true_rows",
                    "validated_factor_rows",
                ],
                "value": [0, 0, 0, 0, 0, 0],
            }
        )

    coverage_flag = factors_df["adj_factor_coverage_flag"].fillna(False)
    return pd.DataFrame(
        {
            "metric": [
                "rows",
                "symbol_count",
                "missing_symbol_rows",
                "missing_action_date_rows",
                "coverage_true_rows",
                "validated_factor_rows",
            ],
            "value": [
                int(len(factors_df)),
                int(factors_df["symbol"].dropna().nunique()),
                int(factors_df["symbol"].isna().sum()),
                int(factors_df["action_date"].isna().sum()),
                int(coverage_flag.sum()),
                int(factors_df["factor_source_validated"].fillna(False).sum()),
            ],
        }
    )


def save_adjustment_factors_quality_report(
    factors_df,
    output_path=ADJUSTMENT_FACTORS_QUALITY_CSV,
):
    report = build_adjustment_factors_quality_report(factors_df)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file
