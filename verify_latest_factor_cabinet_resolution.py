from pathlib import Path

from functions.decision_council.factor_source import resolve_factor_source


def main() -> int:
    spec = resolve_factor_source(factor_source="latest_factor_cabinet")
    latest = max(
        [path for path in Path("results/factor_cabinet").iterdir() if (path / "factor_cabinet.json").exists()],
        key=lambda path: (path / "factor_cabinet.json").stat().st_mtime,
    )
    assert spec.factor_cabinet_run_id == latest.name, (spec.factor_cabinet_run_id, latest.name)
    assert spec.factor_cabinet_path.endswith(str(latest / "factor_cabinet.json")), spec.factor_cabinet_path
    assert spec.factor_count > 0
    stale = min(
        [path for path in Path("results/factor_cabinet").iterdir() if (path / "factor_cabinet.json").exists()],
        key=lambda path: (path / "factor_cabinet.json").stat().st_mtime,
    )
    with_stale_web_fields = resolve_factor_source(
        factor_source="latest_factor_cabinet",
        factor_cabinet_run_id=stale.name,
        factor_cabinet_path=stale / "factor_cabinet.json",
    )
    assert with_stale_web_fields.factor_cabinet_run_id == latest.name
    assert with_stale_web_fields.factor_cabinet_path.endswith(str(latest / "factor_cabinet.json"))
    print("[PASS] latest_factor_cabinet resolves to newest factor_cabinet.json")
    print("[PASS] latest_factor_cabinet ignores stale Web run_id/path fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
