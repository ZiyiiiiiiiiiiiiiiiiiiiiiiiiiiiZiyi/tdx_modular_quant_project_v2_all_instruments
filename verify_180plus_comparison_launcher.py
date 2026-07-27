from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "run_180plus_v2_v3_comparison.ps1"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    expect("$Project = $PSScriptRoot" in text, "comparison launcher resolves the project path without a Chinese-encoding dependency")
    expect("[switch]$DryRun" in text, "comparison launcher supports non-trading preflight")
    expect("mainline_v2" in text, "comparison includes the v2 control")
    expect("mainline_v3_cabinet_native" in text, "comparison includes the Cabinet Native attribution baseline")
    expect("mainline_v3_reliability_weighted" in text, "comparison includes the v3.1 reliability arm")
    expect("mainline_v3_monthly_lgbm_hybrid" in text, "comparison includes the monthly LightGBM arm")
    expect("--monthly-lgbm-maximum-weight" in text, "monthly ML ceiling is fixed in the comparison contract")
    expect("--no-governance-shadow-portfolios" in text, "slow shadow portfolios remain disabled")
    expect('"--max-positions", "5"' in text, "all comparison arms use the five-position account default")
    expect("--governance-control-mode\", \"factor_only" in text, "all arms share the same control mode")
    print("[PASS] fixed 180-plus comparison launcher contract completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
