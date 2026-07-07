from functions.decision_council.factor_source import LEGACY_GOVERNANCE_ALPHA_BUNDLE, resolve_factor_source


def main() -> int:
    spec = resolve_factor_source(factor_source="legacy_bundle", alpha_bundle=LEGACY_GOVERNANCE_ALPHA_BUNDLE)
    assert spec.factor_source == "legacy_bundle"
    assert spec.alpha_bundle == "diversified_pre_screen_bundle_v2"
    assert spec.factor_cabinet_path == ""
    html = __import__("main_launcher_web")._render_run_html()
    assert "legacy: diversified_pre_screen_bundle_v2" in html
    print("[PASS] legacy bundle is explicit and not mixed with factor_cabinet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
