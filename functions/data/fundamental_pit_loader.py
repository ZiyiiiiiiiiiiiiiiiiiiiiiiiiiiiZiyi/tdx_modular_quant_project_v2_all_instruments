"""Point-in-time fundamental data expansion.

Financial reports are usable only from available_date, falling back to
publish_date. Rows without both dates are kept out of formal PIT expansion.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_COLUMNS = [
    "stock_code",
    "trade_date",
    "report_period",
    "publish_date",
    "available_date",
    "revenue",
    "net_profit",
    "deducted_net_profit",
    "operating_cashflow",
    "total_assets",
    "total_equity",
    "total_liabilities",
    "market_cap",
    "industry",
]


def build_pit_fundamental_daily(
    reports: pd.DataFrame,
    trade_calendar,
    *,
    output_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Expand report rows to daily PIT rows without future leakage."""
    if reports is None:
        reports = pd.DataFrame()
    data = reports.copy()
    if data.empty:
        daily = pd.DataFrame(columns=BASE_COLUMNS)
        reports_out = _quality_reports(data, daily)
        _save_reports(reports_out, output_dir)
        return daily, reports_out
    required = {"stock_code", "report_period"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"Fundamental reports missing columns: {missing}")
    data["stock_code"] = data["stock_code"].astype(str)
    data["report_period"] = pd.to_datetime(data["report_period"], errors="coerce")
    data["publish_date"] = pd.to_datetime(data.get("publish_date"), errors="coerce")
    data["available_date"] = pd.to_datetime(data.get("available_date"), errors="coerce")
    data["_effective_available_date"] = data["available_date"].fillna(data["publish_date"])
    usable = data.dropna(subset=["stock_code", "report_period", "_effective_available_date"]).copy()
    calendar = pd.DataFrame({"trade_date": pd.to_datetime(pd.Series(trade_calendar), errors="coerce").dropna().sort_values().unique()})
    if calendar.empty or usable.empty:
        daily = pd.DataFrame(columns=BASE_COLUMNS)
        reports_out = _quality_reports(data, daily)
        _save_reports(reports_out, output_dir)
        return daily, reports_out
    rows = []
    for stock_code, group in usable.sort_values(["stock_code", "_effective_available_date", "report_period"]).groupby("stock_code", sort=False):
        events = group.copy()
        stock_calendar = calendar[calendar["trade_date"] >= events["_effective_available_date"].min()].copy()
        merged = pd.merge_asof(
            stock_calendar.sort_values("trade_date"),
            events.sort_values("_effective_available_date"),
            left_on="trade_date",
            right_on="_effective_available_date",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["stock_code"] = stock_code
        rows.append(merged)
    daily = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=BASE_COLUMNS)
    daily["available_date"] = daily.get("available_date").fillna(daily.get("publish_date"))
    for column in BASE_COLUMNS:
        if column not in daily.columns:
            daily[column] = pd.NA
    daily = daily[BASE_COLUMNS].copy()
    reports_out = _quality_reports(data, daily)
    _save_reports(reports_out, output_dir)
    return daily, reports_out


def _quality_reports(raw: pd.DataFrame, daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    missing_publish = raw[
        pd.to_datetime(raw.get("publish_date"), errors="coerce").isna()
        & pd.to_datetime(raw.get("available_date"), errors="coerce").isna()
    ].copy() if not raw.empty else pd.DataFrame()
    if not daily.empty:
        future_rows = daily[pd.to_datetime(daily["trade_date"]) < pd.to_datetime(daily["available_date"])].copy()
        coverage = (
            daily.groupby("trade_date", dropna=False)
            .agg(stock_count=("stock_code", "nunique"), row_count=("stock_code", "count"))
            .reset_index()
        )
    else:
        future_rows = pd.DataFrame()
        coverage = pd.DataFrame(columns=["trade_date", "stock_count", "row_count"])
    sanity = pd.DataFrame(
        [
            {
                "daily_rows": int(len(daily)),
                "missing_publish_or_available_rows": int(len(missing_publish)),
                "future_leakage_rows": int(len(future_rows)),
                "pit_pass": bool(len(future_rows) == 0),
            }
        ]
    )
    return {
        "pit_coverage_report": coverage,
        "pit_missing_publish_date": missing_publish,
        "pit_sanity_check": sanity,
    }


def _save_reports(reports: dict[str, pd.DataFrame], output_dir: str | Path | None) -> None:
    if output_dir is None:
        return
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, frame in reports.items():
        frame.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
