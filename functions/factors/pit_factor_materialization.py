"""Attach PIT Level-2 factors to a bounded market-data frame."""
from __future__ import annotations

import pandas as pd

from functions.data.fundamental_pit_loader import build_pit_fundamental_daily
from functions.data.pit_level2_store import DEFAULT_PIT_LEVEL2_ROOT, load_pit_level2_table
from functions.factors.event_factor_builder import build_event_daily_features
from functions.factors.fundamental_pit_factors import append_daily_fundamental_factors
from functions.factors.pit_factor_registry import (
    PIT_FACTOR_SPECS,
    append_pit_factor_aliases,
    pit_factor_raw_columns,
)


def attach_pit_level2_factors(
    frame: pd.DataFrame,
    *,
    requested_columns,
    root=DEFAULT_PIT_LEVEL2_ROOT,
) -> pd.DataFrame:
    requested = set(requested_columns) & set(pit_factor_raw_columns())
    if not requested or frame is None or frame.empty:
        return frame
    if not {"symbol", "date"}.issubset(frame.columns):
        raise ValueError("PIT factor materialization requires symbol and date columns")
    data = frame.copy()
    data["symbol"] = data["symbol"].astype(str)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    families = {
        spec["family"] for spec in PIT_FACTOR_SPECS if spec["raw_column"] in requested
    }
    if families - {"event"}:
        data = _attach_fundamental(data, root=root)
    if "event" in families:
        data = _attach_events(data, root=root)
    data = append_pit_factor_aliases(data)
    for column in requested:
        if column not in data.columns:
            data[column] = float("nan")
    missing = sorted(requested - set(data.columns))
    if missing:
        raise ValueError(f"PIT Level-2 factor materialization did not produce: {missing}")
    return data


def _attach_fundamental(data: pd.DataFrame, *, root) -> pd.DataFrame:
    symbols = set(data["symbol"].dropna().astype(str).unique())
    dates = data["date"].dropna()
    start, end = dates.min(), dates.max()
    symbol_values = sorted(symbols)
    reports = load_pit_level2_table(
        "financial_statement_pit", root=root, required=True,
        filters=[
            ("symbol", "in", symbol_values),
            ("effective_from", "<=", end),
            ("report_period", ">=", start - pd.DateOffset(years=4)),
        ],
    )
    daily, _ = build_pit_fundamental_daily(reports, sorted(dates.unique()))
    daily = daily.rename(columns={"stock_code": "symbol", "trade_date": "date"})
    daily["symbol"] = daily["symbol"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    valuations = load_pit_level2_table(
        "valuation_daily_pit", root=root, required=True,
        filters=[
            ("symbol", "in", symbol_values),
            ("effective_from", ">=", start),
            ("effective_from", "<=", end),
        ],
    )
    valuations["symbol"] = valuations["symbol"].astype(str)
    valuations["date"] = pd.to_datetime(valuations["effective_from"], errors="coerce").dt.normalize()
    valuation_cols = ["symbol", "date", "market_cap", "float_cap", "pe_ttm", "pb_mrq"]
    valuations = valuations.sort_values(["symbol", "date", "known_at", "revision_id"]).drop_duplicates(
        ["symbol", "date"], keep="last"
    )[valuation_cols]
    daily = daily.merge(valuations, on=["symbol", "date"], how="left", suffixes=("", "_valuation"))
    if "market_cap_valuation" in daily.columns:
        if "market_cap" in daily.columns:
            daily["market_cap"] = daily["market_cap_valuation"].where(
                daily["market_cap_valuation"].notna(), daily["market_cap"]
            )
        else:
            daily["market_cap"] = daily["market_cap_valuation"]
        daily = daily.drop(columns=["market_cap_valuation"])
    if "sector_parent" in data.columns:
        classification = data[["symbol", "date", "sector_parent"]].drop_duplicates(["symbol", "date"])
        daily = daily.merge(classification, on=["symbol", "date"], how="left")
        sector = daily["sector_parent"].fillna("").astype(str).str.strip()
        if "industry" not in daily.columns:
            daily["industry"] = sector
        else:
            industry = daily["industry"].fillna("").astype(str).str.strip()
            daily["industry"] = industry.where(industry.ne(""), sector)
    daily = append_daily_fundamental_factors(daily)
    factor_cols = [spec["source_column"] for spec in PIT_FACTOR_SPECS if spec["family"] != "event"]
    keep = ["symbol", "date", *[column for column in dict.fromkeys(factor_cols) if column in daily.columns]]
    return data.merge(daily[keep], on=["symbol", "date"], how="left")


def _attach_events(data: pd.DataFrame, *, root) -> pd.DataFrame:
    symbols = set(data["symbol"].dropna().astype(str).unique())
    dates = data["date"].dropna()
    start, end = dates.min(), dates.max()
    events = load_pit_level2_table(
        "corporate_event_pit", root=root, required=True,
        filters=[
            ("symbol", "in", sorted(symbols)),
            ("effective_from", ">=", start - pd.Timedelta(days=180)),
            ("effective_from", "<=", end),
        ],
    )
    daily = build_event_daily_features(events, sorted(dates.unique()))
    daily = daily.rename(columns={"stock_code": "symbol", "trade_date": "date"})
    daily["symbol"] = daily["symbol"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    factor_cols = [spec["source_column"] for spec in PIT_FACTOR_SPECS if spec["family"] == "event"]
    keep = ["symbol", "date", *[column for column in dict.fromkeys(factor_cols) if column in daily.columns]]
    result = data.merge(daily[keep], on=["symbol", "date"], how="left")
    for column in factor_cols:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
    return result
