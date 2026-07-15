"""Smoke-test report-period PIT factors and dangerous missing-value paths."""
from __future__ import annotations

import pandas as pd

from functions.data.fundamental_pit_loader import build_pit_fundamental_daily
from functions.factors.fundamental_pit_factors import (
    append_daily_fundamental_factors,
    prepare_financial_report_factors,
)


def _reports() -> pd.DataFrame:
    rows = []
    for year in (2022, 2023):
        revenue_ytd = profit_ytd = gross_ytd = operating_ytd = ocf_ytd = capex_ytd = 0.0
        for quarter, month in enumerate((3, 6, 9, 12), start=1):
            revenue_ytd += 90.0 + 10.0 * quarter
            profit_ytd += 9.0 + quarter
            gross_ytd += 30.0 + quarter
            operating_ytd += 12.0 + quarter
            ocf_ytd += 10.0 + quarter
            capex_ytd += 2.0 + 0.5 * quarter
            period = pd.Timestamp(year=year, month=month, day=31 if month in (3, 12) else 30)
            known_at = period + pd.Timedelta(days=45)
            rows.append({
                "symbol": "sh600000", "report_period": period, "statement_type": "quarterly",
                "period_value_basis": "ytd", "known_at": known_at,
                "effective_from": known_at.normalize() + pd.Timedelta(days=1),
                "source": "verify", "source_document_id": f"doc-{year}-{quarter}",
                "revision_id": "v1", "downloaded_at": known_at + pd.Timedelta(days=1),
                "revenue": revenue_ytd, "net_profit": profit_ytd,
                "deducted_net_profit": profit_ytd * 0.9, "gross_profit": gross_ytd,
                "operating_profit": operating_ytd, "operating_cashflow": ocf_ytd,
                "capex": capex_ytd, "total_assets": 180.0 + 10.0 * quarter + 20.0 * (year - 2022),
                "total_equity": 70.0 + 4.0 * quarter + 8.0 * (year - 2022),
                "industry": "industrial",
            })
    return pd.DataFrame(rows)


def main() -> int:
    prepared = prepare_financial_report_factors(_reports())
    latest = prepared.iloc[-1]
    assert abs(float(latest["revenue_ttm"]) - 460.0) < 1e-9, latest["revenue_ttm"]
    assert pd.notna(latest["roe_ttm"])
    calendar = pd.bdate_range("2024-02-15", "2024-03-15")
    daily, audit = build_pit_fundamental_daily(_reports(), calendar)
    assert bool(audit["pit_sanity_check"].iloc[0]["pit_pass"])
    daily["market_cap"] = 1000.0
    factored = append_daily_fundamental_factors(daily)
    assert factored["earnings_yield_ttm"].notna().any()
    missing_capex = _reports()
    missing_capex.loc[missing_capex.index[-1], "capex"] = pd.NA
    missing_prepared = prepare_financial_report_factors(missing_capex)
    assert pd.isna(missing_prepared.iloc[-1]["capex_ttm"])
    missing_daily, _ = build_pit_fundamental_daily(missing_capex, calendar)
    missing_daily["market_cap"] = 1000.0
    missing_factored = append_daily_fundamental_factors(missing_daily)
    assert missing_factored["fcf_yield"].isna().all(), "missing CAPEX was silently treated as zero"
    print("[PASS] PIT report replay, TTM factors, as-of expansion, and fail-closed CAPEX")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
