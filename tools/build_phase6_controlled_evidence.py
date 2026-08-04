"""Build a compact evidence record for the frozen Phase-6 experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _runtime(output_dir: str) -> dict:
    payload = json.loads(
        (Path(output_dir) / "environment_manifest.json").read_text(encoding="utf-8")
    )
    return payload["runtime_identity"]


def _buy_keys(output_dir: str) -> set[str]:
    ledger = pd.read_csv(
        Path(output_dir) / "governance_execution_ledger.csv", low_memory=False
    )
    buys = ledger[ledger["side"].astype(str).eq("buy")]
    return set(buys["trade_date"].astype(str) + "|" + buys["symbol"].astype(str))


def _family_evidence(control_dir: str, reserve_dir: str) -> dict:
    def proposal_counts(path: str) -> dict:
        frame = pd.read_csv(
            Path(path) / "governance_action_proposal_ledger.csv", low_memory=False
        )
        selected = frame[frame["selected_by_plan"].fillna(False).astype(bool)]
        entries = selected[selected["action_type"].astype(str).eq("new_entry")]
        return {
            "proposal_rows": int(len(frame)),
            "selected_entry_thesis_counts": {
                str(k): int(v) for k, v in entries["thesis"].value_counts().items()
            },
        }

    left, right = _buy_keys(control_dir), _buy_keys(reserve_dir)
    return {
        "control": proposal_counts(control_dir),
        "family_reserve_one": proposal_counts(reserve_dir),
        "buy_key_overlap": {
            "control": len(left),
            "family_reserve_one": len(right),
            "shared": len(left & right),
            "jaccard": len(left & right) / len(left | right),
        },
    }


def _overlay_evidence(control_dir: str, overlay_dir: str) -> dict:
    control = pd.read_csv(
        Path(control_dir) / "governance_daily_result.csv", low_memory=False
    )
    overlay = pd.read_csv(
        Path(overlay_dir) / "governance_daily_result.csv", low_memory=False
    )
    return {
        "confirmed_state_days": {
            str(k): int(v)
            for k, v in overlay["regime_confirmed_label"].value_counts().items()
        },
        "es_budget_multiplier_min": float(overlay["regime_es_budget_multiplier"].min()),
        "es_budget_multiplier_max": float(overlay["regime_es_budget_multiplier"].max()),
        "authorized_days": int(
            overlay["optional_regime_overlay_authorized"].fillna(False).astype(bool).sum()
        ),
        "capped_days": int(
            overlay["regime_overlay_capped"].fillna(False).astype(bool).sum()
        ),
        "nav_path_equal": bool(
            pd.to_numeric(control["nominal_nav"], errors="coerce").equals(
                pd.to_numeric(overlay["nominal_nav"], errors="coerce")
            )
        ),
        "interpretation": "telemetry_changed_but_fail_closed_authority_prevented_trading_effect",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=Path, required=True)
    parser.add_argument("--overlap", type=Path, required=True)
    parser.add_argument("--ablations", type=Path, required=True)
    parser.add_argument("--determinism", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    capital = pd.read_csv(args.capital, low_memory=False)
    ablations = pd.read_csv(args.ablations, low_memory=False)
    dirs = dict(zip(ablations["experiment"], ablations["output_dir"]))
    runtimes = [_runtime(path) for path in capital["output_dir"]]
    code_fingerprints = sorted({str(item["code_fingerprint"]) for item in runtimes})
    payload = {
        "schema_version": "scap_phase6_controlled_evidence_v1",
        "decision_authority": "none_research_only",
        "capital_matrix": capital.to_dict("records"),
        "capital_buy_overlap": pd.read_csv(args.overlap).to_dict("records"),
        "ablations": ablations.to_dict("records"),
        "code_fingerprints": code_fingerprints,
        "all_code_fingerprints_equal": len(code_fingerprints) == 1,
        "control_determinism": json.loads(args.determinism.read_text(encoding="utf-8")),
        "overlay_transmission": _overlay_evidence(
            dirs["control"], dirs["state_overlay_full"]
        ),
        "family_reserve_transmission": _family_evidence(
            dirs["control"], dirs["family_reserve_one"]
        ),
        "conclusions": [
            "larger capital is diluted by non-scaling attainable exposure under this profile",
            "the optional regime overlay remained fail-closed and had no trading effect",
            "reducing thesis reserve from two to one changed the path and worsened results",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "code_fingerprint": code_fingerprints}))


if __name__ == "__main__":
    main()
