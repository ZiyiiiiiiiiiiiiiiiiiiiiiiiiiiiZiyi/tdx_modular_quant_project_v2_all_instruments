from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pandas as pd

from functions.factor_selection.factor_cabinet_builder import _load_v2, _select_by_role


def main() -> int:
    with TemporaryDirectory() as temporary:
        run = Path(temporary) / "run_test"
        run.mkdir()
        rows = pd.DataFrame([
            {
                "factor_name": "fund_earnings_yield_ttm",
                "raw_column": "cand_fund_earnings_yield_ttm",
                "new_decision": "promote_candidate", "new_role": "entry_alpha",
                "factor_type": "valuation", "factor_family": "valuation",
                "rank_ic": 0.02, "ic_ir": 0.2, "top_bottom_spread": 0.01,
                "coverage": 0.8, "positive_ic_ratio": 0.55,
            },
            {
                "factor_name": "event_buyback_announcement",
                "raw_column": "cand_event_buyback_announcement",
                "new_decision": "promote_candidate", "new_role": "timing_filter",
                "factor_type": "event", "factor_family": "event",
                "rank_ic": 0.01, "ic_ir": 0.12, "top_bottom_spread": 0.005,
                "coverage": 0.1, "positive_ic_ratio": 0.53,
            },
        ])
        rows.to_csv(run / "admitted_v2.csv", index=False)
        rows.iloc[0:0].to_csv(run / "watchlist_v2.csv", index=False)
        rows.to_csv(run / "appeal_summary.csv", index=False)
        (run / "artifact_manifest.json").write_text(json.dumps({
            "status": "complete", "run_kind": "production"
        }), encoding="utf-8")
        loaded = _load_v2(run)
        valuation = loaded[loaded["factor_name"].eq("fund_earnings_yield_ttm")].iloc[0]
        if valuation["cabinet_role"] != "proxy_entry_alpha":
            print("[FAIL] promoted PIT entry factor did not map to proxy_entry_alpha")
            return 1
        if valuation["role"] != "entry_alpha_proxy":
            print("[FAIL] promoted PIT entry factor lost its proxy role label")
            return 1
        loaded["cabinet_score"] = 1.0
        selected, _ = _select_by_role(loaded, min_factors=2, max_factors=10)
        if set(rows["factor_name"]) - set(selected["factor_name"]):
            print("[FAIL] promoted PIT factors were dropped from the cabinet selection")
            return 1
        if selected["factor_name"].duplicated().any():
            print("[FAIL] protected cabinet factors were duplicated")
            return 1
    print("[PASS] PIT appeal roles and protected cabinet selection are executable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
