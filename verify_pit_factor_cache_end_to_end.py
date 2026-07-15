from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pandas as pd
import pyarrow.parquet as pq

from functions.decision_council.candidate_factor_cache import candidate_factor_source_columns
from functions.decision_council.factor_cabinet_feature_cache import build_factor_cabinet_feature_cache


def main() -> int:
    source_path = Path("data/processed/tdx_daily_features.parquet")
    available = set(pq.read_schema(source_path).names)
    columns = [column for column in candidate_factor_source_columns() if column in available]
    if "sector_parent" in available and "sector_parent" not in columns:
        columns.append("sector_parent")
    selector = pd.read_parquet(
        source_path,
        columns=["symbol", "instrument_type"],
        filters=[("date", ">=", pd.Timestamp("2024-01-01")), ("date", "<=", pd.Timestamp("2024-01-05"))],
    )
    symbols = sorted(
        selector.loc[
            selector["instrument_type"].eq("stock")
            & selector["symbol"].astype(str).str.startswith(("sh", "sz")),
            "symbol",
        ].astype(str).unique()
    )[:20]
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        feature = pd.read_parquet(
            source_path,
            columns=columns,
            filters=[
                ("date", ">=", pd.Timestamp("2023-01-01")),
                ("date", "<=", pd.Timestamp("2024-06-07")),
                ("symbol", "in", symbols),
            ],
        )
        feature_path = root / "features.parquet"
        feature.to_parquet(feature_path, index=False)
        run_id = f"pit_cache_smoke_{root.name}"
        cabinet_dir = root / run_id
        cabinet_dir.mkdir()
        factors = [
            ("rsi_slope_5", "cand_rsi_slope_5", "timing_filter", "rsi", "rsi_slope"),
            ("fund_earnings_yield_ttm", "cand_fund_earnings_yield_ttm", "entry_alpha", "fundamental", "valuation"),
            ("fund_fcf_yield", "cand_fund_fcf_yield", "hold_validation", "fundamental", "cashflow"),
            ("fund_roe_ttm_ind_neutral", "cand_fund_roe_ttm_ind_neutral", "hold_validation", "fundamental", "profitability"),
            ("event_earnings_forecast_positive", "cand_event_earnings_forecast_positive", "timing_filter", "event", "event"),
        ]
        payload = {
            "run_id": run_id,
            "factors": [
                {"factor_name": name, "raw_column": raw, "role": role, "module": module, "family": family}
                for name, raw, role, module, family in factors
            ],
        }
        cabinet_path = cabinet_dir / "factor_cabinet.json"
        cabinet_path.write_text(json.dumps(payload), encoding="utf-8")
        cache_path, manifest_path = build_factor_cabinet_feature_cache(
            factor_source="selected_factor_cabinet",
            factor_cabinet_run_id=run_id,
            factor_cabinet_path=str(cabinet_path),
            start_date="2024-06-03",
            end_date="2024-06-07",
            feature_path=feature_path,
        )
        cache = pd.read_parquet(cache_path)
        raw_columns = {item[1] for item in factors}
        if raw_columns - set(cache.columns) or cache.empty:
            print("[FAIL] end-to-end cabinet cache omitted PIT/RSI runtime columns")
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("factor_cabinet_run_id") != run_id or int(manifest.get("row_count", 0)) != len(cache):
            print("[FAIL] end-to-end cabinet cache manifest is inconsistent")
            return 1
    print(f"[PASS] selected cabinet -> PIT/RSI cache end-to-end rows={len(cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
