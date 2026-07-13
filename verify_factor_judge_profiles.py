"""Verify Factor Judge v2 profile config and mapping."""
from __future__ import annotations

from pathlib import Path

from functions.decision_council.factor_judge_profiles import build_profile_mapping_report, load_factor_judge_profiles
from functions.decision_council.factor_pool_contract import load_factor_pool_contract


V1_SUMMARY = Path(
    "results/decision_council/fast_factor_judge/"
    "hs300_csi500_a500_strict/run20260704_004631_813799/fast_factor_summary.csv"
)


def main() -> int:
    profiles = load_factor_judge_profiles()
    required = {"price_fast", "technical_timing", "fundamental_medium", "event_decay"}
    missing = required - set(profiles)
    if missing:
        print(f"[FAIL] missing judge profiles: {sorted(missing)}")
        return 1
    print(f"[PASS] judge profiles loaded: {sorted(profiles)}")
    if not V1_SUMMARY.exists():
        print(f"[SKIP] v1 summary not found: {V1_SUMMARY}")
        return 0
    contract = load_factor_pool_contract(V1_SUMMARY)
    mapping, unmapped = build_profile_mapping_report(contract, profiles=profiles)
    out = Path("reports/verify_factor_judge_profiles")
    out.mkdir(parents=True, exist_ok=True)
    mapping.to_csv(out / "profile_mapping_report.csv", index=False, encoding="utf-8-sig")
    unmapped.to_csv(out / "unmapped_factors.csv", index=False, encoding="utf-8-sig")
    if mapping.empty or "judge_profile" not in mapping.columns:
        print("[FAIL] profile mapping report missing required columns")
        return 1
    mapped_count = int(mapping["judge_profile"].astype(str).ne("").sum())
    if mapped_count <= 0:
        print("[FAIL] no factors mapped to profiles")
        return 1
    print(f"[PASS] profile mapping generated: mapped={mapped_count}, unmapped={len(unmapped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
