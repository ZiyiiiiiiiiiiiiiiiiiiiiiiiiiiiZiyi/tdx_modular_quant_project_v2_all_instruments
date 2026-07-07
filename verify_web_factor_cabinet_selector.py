import main_launcher_web


def main() -> int:
    html = main_launcher_web._render_run_html()
    required = [
        "治理主线因子来源",
        "legacy_bundle",
        "latest_factor_cabinet",
        "selected_factor_cabinet",
        "因子柜选择",
        "116 factors",
        "strict_entry_alpha",
        "proxy_entry_alpha",
        "legacy: diversified_pre_screen_bundle_v2",
    ]
    for text in required:
        assert text in html, text
    assert "run20260705_142155_732885" in html or "run20260706_183553_702097" in html
    print("[PASS] web launcher exposes factor source and factor cabinet selector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
