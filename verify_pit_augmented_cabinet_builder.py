from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pandas as pd

from functions.factor_selection.factor_cabinet_builder import build_factor_cabinet
from functions.decision_council.factor_cabinet_pruner import build_factor_cabinet_pruned


def main() -> int:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        base_dir = root / "base_run"
        appeal_dir = root / "appeal_run"
        base_dir.mkdir()
        appeal_dir.mkdir()
        base_factors = [
            {"factor_name": f"old_{index}", "raw_column": f"cand_old_{index}",
             "role": role, "module": "legacy", "family": f"legacy_{index}",
             "strict_entry_alpha": role == "entry_alpha", "direction": "higher_better"}
            for index, role in enumerate(("entry_alpha", "timing_filter", "risk_override"), start=1)
        ]
        base_path = base_dir / "factor_cabinet.json"
        base_path.write_text(json.dumps({"run_id": "base_run", "factors": base_factors}), encoding="utf-8")
        rows = pd.DataFrame([
            {"factor_name": "fund_earnings_yield_ttm", "raw_column": "cand_fund_earnings_yield_ttm",
             "direction": "higher_better", "factor_type": "valuation", "factor_family": "valuation",
             "new_decision": "promote_candidate", "new_role": "entry_alpha", "rank_ic": 0.02,
             "ic_ir": 0.2, "top_bottom_spread": 0.01, "coverage": 0.8, "positive_ic_ratio": 0.55},
            {"factor_name": "rsi_overheat_14", "raw_column": "cand_rsi_overheat_14",
             "direction": "higher_better", "factor_type": "rsi", "factor_family": "rsi_overheat",
             "new_decision": "promote_candidate", "new_role": "risk_override", "rank_ic": 0.01,
             "ic_ir": 0.12, "top_bottom_spread": 0.0, "coverage": 0.8, "positive_ic_ratio": 0.52},
            {"factor_name": "event_buyback_announcement", "raw_column": "cand_event_buyback_announcement",
             "direction": "higher_better", "factor_type": "event", "factor_family": "event",
             "new_decision": "watchlist", "new_role": "timing_filter", "rank_ic": 0.01,
             "ic_ir": 0.1, "top_bottom_spread": 0.0, "coverage": 0.1, "positive_ic_ratio": 0.51},
        ])
        rows[rows["new_decision"].eq("promote_candidate")].to_csv(appeal_dir / "admitted_v2.csv", index=False)
        rows[rows["new_decision"].eq("watchlist")].to_csv(appeal_dir / "watchlist_v2.csv", index=False)
        rows.to_csv(appeal_dir / "appeal_summary.csv", index=False)
        (appeal_dir / "artifact_manifest.json").write_text(
            json.dumps({
                "artifact_type": "factor_appeal_composite",
                "artifact_version": "appeal_composite_v1",
                "run_id": "appeal_run",
                "status": "complete",
                "run_kind": "production",
                "source_artifacts": [
                    {
                        "artifact_type": "factor_appeal_judge",
                        "artifact_version": "v4_pit_level2_fundamental_event",
                    },
                    {
                        "artifact_type": "orderflow_parameter_research",
                        "artifact_version": "daily_ohlcv_proxy_grid_v1",
                    },
                ],
            }), encoding="utf-8"
        )
        saved = build_factor_cabinet(
            appeal_run_dir=appeal_dir,
            base_cabinet_path=base_path,
            output_root=root / "output",
            augmented_max_factors=10,
        )
        payload = json.loads(Path(saved["factor_cabinet_json"]).read_text(encoding="utf-8"))
        names = {row["factor_name"] for row in payload["factors"]}
        if not {row["factor_name"] for row in base_factors}.issubset(names):
            print("[FAIL] augmented cabinet removed a base factor")
            return 1
        if not {"fund_earnings_yield_ttm", "rsi_overheat_14"}.issubset(names):
            print("[FAIL] promoted PIT/RSI factors were not appended")
            return 1
        if "event_buyback_announcement" in names:
            print("[FAIL] watchlist event factor entered the executable cabinet")
            return 1
        if payload.get("generation_policy") != "pit_augmented_v2" or payload.get("base_factor_count") != 3:
            print("[FAIL] augmented cabinet provenance is incomplete")
            return 1
        if not payload.get("default_eligible") or saved.get("factor_cabinet") != saved.get("factor_cabinet_json"):
            print("[FAIL] complete appeal provenance or standard artifact alias is missing")
            return 1
        preservation = pd.read_csv(saved["base_cabinet_preservation_report"])
        if not preservation["preserved"].all():
            print("[FAIL] base preservation report detected a dropped factor")
            return 1
        family = pd.read_csv(saved["pit_family_inclusion_report"]).set_index("family")
        if family.loc["rsi", "selected_additions"] != 1 or bool(family["forced_inclusion"].any()):
            print("[FAIL] economic-family inclusion report is incorrect")
            return 1
        try:
            build_factor_cabinet_pruned(
                factor_source="selected_factor_cabinet",
                factor_cabinet_run_id=Path(saved["factor_cabinet_json"]).parent.name,
                factor_cabinet_path=str(saved["factor_cabinet_json"]),
                output_root=root / "pruned_blocked",
                report_root=root / "pruned_reports_blocked",
            )
        except FileNotFoundError as exc:
            if "cache-backed gap audit" not in str(exc):
                raise
        else:
            print("[FAIL] augmented cabinet pruning did not require cache-backed gap evidence")
            return 1
        pruned = build_factor_cabinet_pruned(
            factor_source="selected_factor_cabinet",
            factor_cabinet_run_id=Path(saved["factor_cabinet_json"]).parent.name,
            factor_cabinet_path=str(saved["factor_cabinet_json"]),
            output_root=root / "pruned",
            report_root=root / "pruned_reports",
            require_gap_metrics=False,
        )
        decisions = pd.read_csv(pruned["prune_decisions"])
        protected = set(
            decisions.loc[
                decisions["decision_reason"].eq("kept_augmented_family_representative"),
                "factor_name",
            ].astype(str)
        )
        if not {"fund_earnings_yield_ttm", "rsi_overheat_14"}.issubset(protected):
            print("[FAIL] pruner did not preserve evidence-backed family representatives")
            return 1
    print("[PASS] PIT augmented cabinet preserves base and adds only promoted evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
