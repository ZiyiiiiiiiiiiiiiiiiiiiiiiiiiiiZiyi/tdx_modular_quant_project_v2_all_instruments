"""Validate the completed frozen Phase-6 evidence product."""

import json
from pathlib import Path


path = Path(
    "results/decision_council/derived_products/run20260804_221302/"
    "phase6_controlled_evidence_20260805.json"
)
payload = json.loads(path.read_text(encoding="utf-8"))
capital = payload["capital_matrix"]
ablations = {row["experiment"]: row for row in payload["ablations"]}
checks = {
    "four completed capital rows": len(capital) == 4
    and all(int(row["trading_days"]) == 82 for row in capital),
    "single frozen code fingerprint": payload["all_code_fingerprints_equal"]
    and len(payload["code_fingerprints"]) == 1,
    "independent control is deterministic": payload["control_determinism"]["passed"],
    "capital efficiency declines across tested levels": all(
        capital[i]["total_return"] > capital[i + 1]["total_return"]
        for i in range(len(capital) - 1)
    ),
    "larger profiles violate exposure floor every day": all(
        int(row["exposure_floor_violation_days"]) == 82 for row in capital[1:]
    ),
    "optional overlay remained unauthorized": payload["overlay_transmission"][
        "authorized_days"
    ]
    == 0,
    "optional overlay did not change NAV": payload["overlay_transmission"][
        "nav_path_equal"
    ],
    "family reserve one worsened return": ablations["family_reserve_one"][
        "total_return"
    ]
    < ablations["control"]["total_return"],
    "family ablation changed buy path": payload["family_reserve_transmission"][
        "buy_key_overlap"
    ]["jaccard"]
    < 0.25,
}
for name, passed in checks.items():
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
raise SystemExit(0 if all(checks.values()) else 1)
