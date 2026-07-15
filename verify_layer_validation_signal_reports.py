"""Verify fixed-horizon L0/L1/L2/L3 layer-validation reports."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.decision_council.layer_validation_audit import build_layer_validation_reports


def main() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        part = root / "cg_202401.csv"
        rows = []
        dates = pd.bdate_range("2024-01-02", periods=6)
        for date in dates[:3]:
            for rank, symbol in enumerate(("a", "b", "c", "d"), start=1):
                rows.append({
                    "decision_id": f"gov_{date:%Y%m%d}",
                    "signal_date": date,
                    "symbol": symbol,
                    "candidate_rank": rank,
                    "primary_score": 1.0 - rank / 10.0,
                    "entry_alpha_score": 0.9 - rank / 10.0,
                    "entry_timing_score": rank / 10.0,
                    "entry_liquidity_score": 0.5,
                    "entry_matrix_score": 0.7,
                    "final_entry_score": 0.6,
                    "p_win_10d_calibrated": 0.5,
                    "entry_confirmed": rank <= 2,
                    "mainline_v2_entry_confirmed": rank <= 2,
                    "state_machine_role_pass": rank <= 3,
                    "cooldown_active": False,
                    "position_state": "building",
                    "entry_block_reason": "confirmed" if rank <= 2 else "rank",
                })
        pd.DataFrame(rows).to_csv(part, index=False)

        histories = {}
        history_dates = pd.bdate_range("2024-01-02", periods=30)
        for offset, symbol in enumerate(("a", "b", "c", "d"), start=1):
            slope = 5 - offset
            histories[symbol] = pd.DataFrame({
                "date": history_dates,
                "close": [100.0 + slope * day for day in range(len(history_dates))],
            })
        executions = pd.DataFrame([{
            "signal_date": dates[0],
            "trade_date": dates[1],
            "symbol": "a",
            "side": "buy",
            "execution_status": "filled",
            "order_id": "buy_a",
            "decision_id": "gov_buy_a",
            "reason": "entry",
            "price": 100.0,
            "executed_shares": 100.0,
        }])
        reports = build_layer_validation_reports(
            [part],
            close_history_getter=lambda symbol: histories[symbol],
            execution_ledger=executions,
        )
        detail = reports["governance_layer_validation_candidate_detail"]
        variants = reports["governance_layer_validation_variant_report"]
        scores = reports["governance_layer_validation_score_report"]
        trade_review = reports["governance_layer_validation_trade_review"]
        execution_gap = reports["governance_layer_validation_execution_gap"]
        assert len(detail) == 12
        assert int(detail["l3_executed_buy"].sum()) == 1
        assert detail["forward_return_5d"].notna().all()
        assert set(variants["variant"]) >= {
            "L1_current_role_confirmation", "L2_primary_top3",
            "L2_primary_entry_alpha_top3", "L3_executed_buy",
        }
        duplicate = variants[
            (variants["variant"] == "L2_primary_entry_alpha_top3")
            & (variants["horizon_days"] == 5)
        ].iloc[0]
        assert not bool(duplicate["distinct_selection"])
        assert duplicate["identical_to"] in {"L1_current_role_confirmation", "L2_primary_top3"}
        primary = scores[(scores["score"] == "primary_score") & (scores["horizon_days"] == 5)]
        assert len(primary) == 1 and float(primary.iloc[0]["mean_daily_rank_ic"]) > 0.0
        assert len(trade_review) == 1 and bool(trade_review.iloc[0]["candidate_found"])
        assert float(trade_review.iloc[0]["primary_rank"]) == 1.0
        assert float(trade_review.iloc[0]["gap_to_best_5d"]) == 0.0
        assert len(execution_gap) == 1 and int(execution_gap.iloc[0]["executed_buy_count"]) == 1

        empty_reports = build_layer_validation_reports(
            [],
            close_history_getter=lambda symbol: pd.DataFrame(),
            execution_ledger=pd.DataFrame(),
        )
        for name, frame in empty_reports.items():
            assert list(frame.columns), f"empty layer report has no schema: {name}"
    print("[PASS] layer validation L0/L1/L2/L3 reports")


if __name__ == "__main__":
    main()
