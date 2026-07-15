"""Verify CLI and Web layer-validation routes share factor-only defaults."""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    start = source.index("def _run_single_governance_variant(")
    end = source.index("\ndef run_registry_suite", start)
    direct = source[start:end]
    assert 'variant_name == "governance_layer_validation"' in direct
    assert 'control_mode = "factor_only"' in direct
    assert 'capital_profile["retail_min_entry_matrix_score"]' in direct
    assert "enable_market_regime_policy=variant_spec.enable_market_regime_policy" in direct
    assert '"mainline_v2": "v2"' in direct

    start = source.index("def run_governance_layer_validation_from_main(")
    end = source.index("\n\nLAYER_ABLATION_SUITE", start)
    web = source[start:end]
    assert "run_single_experiment(" in web
    assert "governance_control_mode=_governance_control_mode_from_args(args)" in web
    experiment_source = Path("run_governance_experiments.py").read_text(encoding="utf-8")
    assert 'if control_mode != "normal":' in experiment_source
    print("[PASS] CLI and Web layer-validation routes share the factor-only contract")


if __name__ == "__main__":
    main()
