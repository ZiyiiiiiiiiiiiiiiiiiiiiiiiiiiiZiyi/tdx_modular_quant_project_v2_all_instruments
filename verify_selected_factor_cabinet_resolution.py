import json
import tempfile
from pathlib import Path

from functions.decision_council.factor_source import resolve_factor_source


def main() -> int:
    run_id = "run20260713_213546_273503"
    if not (Path("results/factor_cabinet") / run_id / "factor_cabinet.json").exists():
        runs = sorted(path.name for path in Path("results/factor_cabinet").iterdir() if (path / "factor_cabinet.json").exists())
        run_id = runs[-1]
    spec = resolve_factor_source(factor_source="selected_factor_cabinet", factor_cabinet_run_id=run_id)
    assert spec.factor_cabinet_run_id == run_id
    assert spec.factor_cabinet_path.endswith(f"{run_id}\\factor_cabinet.json") or spec.factor_cabinet_path.endswith(f"{run_id}/factor_cabinet.json")
    assert spec.factor_count > 0, spec.factor_count
    expected_passthrough = {
        "score_orderflow_close_drive",
        "score_orderflow_efficiency",
        "score_price_volume_breakout",
        "score_turtle_breakout",
    }
    assert expected_passthrough <= set(spec.model_feature_map.values())
    with tempfile.TemporaryDirectory() as tmp:
        mismatch_path = Path(tmp) / "factor_cabinet.json"
        payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
        payload["run_id"] = "different_run_id"
        mismatch_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            resolve_factor_source(
                factor_source="selected_factor_cabinet",
                factor_cabinet_run_id=run_id,
                factor_cabinet_path=mismatch_path,
            )
        except ValueError as exc:
            assert "run_id/path mismatch" in str(exc)
        else:
            raise AssertionError("selected cabinet accepted a mismatched run_id/path")
        invalid_payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
        invalid_payload["run_id"] = run_id
        invalid_payload["factors"][0]["raw_column"] = "score_unapproved_legacy_factor"
        mismatch_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
        try:
            resolve_factor_source(
                factor_source="selected_factor_cabinet",
                factor_cabinet_run_id=run_id,
                factor_cabinet_path=mismatch_path,
            )
        except ValueError as exc:
            assert "invalid runtime metadata" in str(exc)
        else:
            raise AssertionError("selected cabinet accepted an unapproved score_* column")
    print("[PASS] selected_factor_cabinet resolves the requested run_id")
    print("[PASS] selected_factor_cabinet rejects run_id/path mismatch")
    print("[PASS] selected_factor_cabinet permits only approved score_* passthrough columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
