from pathlib import Path

from functions.decision_council.factor_source import resolve_factor_source


def main() -> int:
    run_id = "run20260705_142155_732885"
    if not (Path("results/factor_cabinet") / run_id / "factor_cabinet.json").exists():
        runs = sorted(path.name for path in Path("results/factor_cabinet").iterdir() if (path / "factor_cabinet.json").exists())
        run_id = runs[-1]
    spec = resolve_factor_source(factor_source="selected_factor_cabinet", factor_cabinet_run_id=run_id)
    assert spec.factor_cabinet_run_id == run_id
    assert spec.factor_cabinet_path.endswith(f"{run_id}\\factor_cabinet.json") or spec.factor_cabinet_path.endswith(f"{run_id}/factor_cabinet.json")
    assert spec.factor_count == 116, spec.factor_count
    print("[PASS] selected_factor_cabinet resolves the requested run_id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
