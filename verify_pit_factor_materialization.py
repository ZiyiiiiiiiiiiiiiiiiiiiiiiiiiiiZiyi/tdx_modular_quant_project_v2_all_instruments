from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from functions.factors.pit_factor_materialization import attach_pit_level2_factors


def main() -> int:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        reports = []
        for index, period in enumerate(pd.period_range("2022Q2", "2024Q1", freq="Q"), start=1):
            report_period = period.end_time.normalize()
            known_at = report_period + pd.Timedelta(days=35)
            reports.append({
                "symbol": "000001.SZ", "report_period": report_period,
                "statement_type": "consolidated", "period_value_basis": "quarter",
                "known_at": known_at, "effective_from": known_at,
                "source": "smoke", "source_document_id": f"r{index}",
                "revision_id": "1", "downloaded_at": known_at,
                "revenue": 100 + index, "net_profit": 10 + index,
                "deducted_net_profit": 9 + index, "gross_profit": 40 + index,
                "operating_profit": 15 + index, "operating_cashflow": 12 + index,
                "capex": 2 + index / 10, "total_assets": 500 + index * 10,
                "total_equity": 250 + index * 5, "industry": "bank",
            })
        pd.DataFrame(reports).to_parquet(root / "financial_statement_pit.parquet", index=False)
        dates = pd.date_range("2024-05-06", periods=4, freq="B")
        valuation = pd.DataFrame({
            "symbol": "000001.SZ", "valuation_date": dates, "known_at": dates,
            "effective_from": dates, "source": "smoke",
            "source_document_id": [f"v{i}" for i in range(4)], "revision_id": "1",
            "downloaded_at": dates, "market_cap": 10000.0, "float_cap": 8000.0,
            "pe_ttm": 8.0, "pb_mrq": 0.9,
        })
        valuation.to_parquet(root / "valuation_daily_pit.parquet", index=False)
        event = pd.DataFrame([{
            "symbol": "000001.SZ", "event_id": "e1", "event_type": "buyback",
            "event_stage": "announced", "announcement_time": dates[0],
            "known_at": dates[0], "effective_from": dates[0], "source": "smoke",
            "source_document_id": "e1", "revision_id": "1", "downloaded_at": dates[0],
            "direction": "positive", "strength": 1.0, "cancelled": False,
            "revision_of": "",
        }])
        event.to_parquet(root / "corporate_event_pit.parquet", index=False)
        market = pd.DataFrame({"symbol": "000001.SZ", "date": dates, "close": np.arange(4) + 10.0})
        requested = {
            "cand_fund_earnings_yield_ttm", "cand_fund_roe_ttm_ind_neutral",
            "cand_fund_fcf_yield", "cand_event_buyback_announcement",
        }
        out = attach_pit_level2_factors(market, requested_columns=requested, root=root)
        missing = requested - set(out.columns)
        if missing or out[list(requested)].isna().all().any():
            print(f"[FAIL] missing or empty PIT factors: {sorted(missing)}")
            return 1
        if out.loc[out["date"].eq(dates[0]), "cand_event_buyback_announcement"].iloc[0] <= 0:
            print("[FAIL] buyback event was not materialized on effective date")
            return 1
    print("[PASS] PIT fundamental, valuation, and event factors materialized into runtime columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
