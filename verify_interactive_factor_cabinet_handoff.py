import argparse
import json
import tempfile
from pathlib import Path

from main import _apply_runtime_profile, _pin_runtime_factor_cabinet, _require_completed_research_output


def main() -> int:
    bounded_args = argparse.Namespace(
        governance_max_days=None,
        governance_shadow_portfolios=None,
        governance_start_date="2024-01-01",
        governance_end_date="2024-12-31",
    )
    bounded_runtime, bounded_profile, _ = _apply_runtime_profile(
        bounded_args,
        "full",
        ["factor_appeal_judge", "orderflow_parameter_research", "factor_cabinet"],
    )
    assert bounded_profile == "full"
    assert bounded_runtime.governance_max_days == 180
    runtime_args = argparse.Namespace(
        factor_source="latest_factor_cabinet",
        factor_cabinet_run_id="stale_run",
        factor_cabinet_path="stale_path",
    )
    with tempfile.TemporaryDirectory() as tmp:
        cabinet_path = Path(tmp) / "pruned_run_test" / "factor_cabinet.json"
        cabinet_path.parent.mkdir()
        cabinet_path.write_text(json.dumps({
            "run_id": "pruned_run_test",
            "factors": [{"factor_name": "factor_a"}],
        }), encoding="utf-8")
        resolved = _pin_runtime_factor_cabinet(
            runtime_args,
            {"factor_cabinet_json": cabinet_path},
        )
        assert resolved == cabinet_path.resolve()
        assert runtime_args.factor_source == "selected_factor_cabinet"
        assert runtime_args.factor_cabinet_run_id == "pruned_run_test"
        assert runtime_args.factor_cabinet_path == str(cabinet_path.resolve())

        try:
            _pin_runtime_factor_cabinet(runtime_args, {
                "factor_cabinet": cabinet_path,
                "factor_cabinet_json": cabinet_path.parent / "other.json",
            })
        except RuntimeError as exc:
            assert "conflicting artifact paths" in str(exc)
        else:
            raise AssertionError("conflicting cabinet artifact aliases were accepted")

    try:
        _pin_runtime_factor_cabinet(runtime_args, {})
    except RuntimeError as exc:
        assert "did not return" in str(exc)
    else:
        raise AssertionError("missing cabinet artifact was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "appeal"
        output_dir.mkdir()
        manifest_path = output_dir / "artifact_manifest.json"
        manifest_path.write_text(json.dumps({
            "artifact_type": "factor_appeal_judge",
            "status": "complete",
            "run_kind": "production",
        }), encoding="utf-8")
        assert _require_completed_research_output(
            {"output_dir": output_dir, "artifact_manifest": manifest_path},
            task_name="factor_appeal_judge",
            artifact_type="factor_appeal_judge",
        ) == output_dir.resolve()
        manifest_path.write_text(json.dumps({
            "artifact_type": "factor_appeal_judge",
            "status": "incomplete",
            "run_kind": "production",
        }), encoding="utf-8")
        try:
            _require_completed_research_output(
                {"output_dir": output_dir},
                task_name="factor_appeal_judge",
                artifact_type="factor_appeal_judge",
            )
        except RuntimeError as exc:
            assert "not complete" in str(exc)
        else:
            raise AssertionError("incomplete research artifact was accepted")

    source = Path("main.py").read_text(encoding="utf-8")
    assert "pruned_saved = run_factor_cabinet_prune_from_main(runtime_args)" in source
    assert "_pin_runtime_factor_cabinet(runtime_args, pruned_saved)" in source
    pre_gap = source.index('if "factor_cabinet_gap_report" in tasks and "factor_cabinet_prune" in tasks:')
    prune = source.index('if "factor_cabinet_prune" in tasks:', pre_gap)
    cache = source.index('if "factor_cabinet_feature_cache" in tasks:', prune)
    assert pre_gap < prune < cache
    print("[PASS] build/prune output is pinned for downstream cache and audit tasks")
    print("[PASS] combined gap/prune/cache flow audits the source before pruning")
    print("[PASS] missing cabinet handoff fails closed")
    print("[PASS] legacy artifact key is accepted and conflicting aliases fail closed")
    print("[PASS] downstream research handoff requires a completed production manifest")
    print("[PASS] blank max_days is bounded to 180 for factor research tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
