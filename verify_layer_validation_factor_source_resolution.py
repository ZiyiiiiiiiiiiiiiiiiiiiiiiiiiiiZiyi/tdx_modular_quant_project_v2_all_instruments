from types import SimpleNamespace

from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_LEGACY,
    LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    resolve_factor_source,
)


def _args(factor_source: str) -> SimpleNamespace:
    return SimpleNamespace(
        governance_universes=["hs300_strict"],
        capital_profile="small_capital_branch",
        initial_cash=None,
        max_positions=None,
        min_cash_buffer=None,
        capital_usage_mode=None,
        governance_start_date="2021-01-04",
        governance_end_date="2021-01-04",
        governance_max_days=1,
        no_live_monitor=True,
        governance_control_mode="normal",
        disable_alpha_collapse_exit=False,
        factor_source=factor_source,
        factor_cabinet_run_id="",
        factor_cabinet_path="",
    )


def _capture_layer_validation_call(factor_source: str) -> dict:
    import main
    import run_governance_experiments

    calls: list[dict] = []
    original = run_governance_experiments.run_single_experiment

    def fake_run_single_experiment(**kwargs):
        spec = resolve_factor_source(
            factor_source=kwargs.get("factor_source"),
            factor_cabinet_run_id=kwargs.get("factor_cabinet_run_id", ""),
            factor_cabinet_path=kwargs.get("factor_cabinet_path", ""),
            alpha_bundle=kwargs.get("alpha_bundle"),
        )
        row = dict(kwargs)
        row["resolved_factor_source"] = spec.factor_source
        row["resolved_factor_cabinet_run_id"] = spec.factor_cabinet_run_id
        row["resolved_factor_count"] = spec.factor_count
        calls.append(row)
        return {}

    try:
        run_governance_experiments.run_single_experiment = fake_run_single_experiment
        main.run_governance_layer_validation_from_main(_args(factor_source))
    finally:
        run_governance_experiments.run_single_experiment = original

    assert calls, "layer validation did not call run_single_experiment"
    return calls[0]


def check_layer_validation_latest_cabinet() -> None:
    call = _capture_layer_validation_call(FACTOR_SOURCE_LATEST_CABINET)
    assert call["factor_source"] == FACTOR_SOURCE_LATEST_CABINET
    assert call["alpha_bundle"] == LEGACY_GOVERNANCE_ALPHA_BUNDLE
    assert call["resolved_factor_source"] == FACTOR_SOURCE_LATEST_CABINET
    assert call["resolved_factor_cabinet_run_id"]
    assert call["resolved_factor_count"] > 0
    print("[PASS] layer validation + latest_factor_cabinet loads factor_cabinet")


def check_layer_validation_legacy_bundle() -> None:
    call = _capture_layer_validation_call(FACTOR_SOURCE_LEGACY)
    assert call["factor_source"] == FACTOR_SOURCE_LEGACY
    assert call["alpha_bundle"] == LEGACY_GOVERNANCE_ALPHA_BUNDLE
    assert call["resolved_factor_source"] == FACTOR_SOURCE_LEGACY
    assert call["resolved_factor_cabinet_run_id"] == ""
    print("[PASS] layer validation + legacy_bundle uses diversified_pre_screen_bundle_v2")


def check_validation_core_cannot_masquerade_as_legacy() -> None:
    try:
        resolve_factor_source(
            factor_source=FACTOR_SOURCE_LEGACY,
            alpha_bundle="validation_core_bundle",
        )
    except ValueError as exc:
        assert "legacy_bundle governance source is currently restricted" in str(exc)
        print("[PASS] validation_core_bundle cannot masquerade as legacy_bundle")
        return
    raise AssertionError("validation_core_bundle unexpectedly resolved as legacy_bundle")


def main() -> int:
    check_layer_validation_latest_cabinet()
    check_layer_validation_legacy_bundle()
    check_validation_core_cannot_masquerade_as_legacy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
