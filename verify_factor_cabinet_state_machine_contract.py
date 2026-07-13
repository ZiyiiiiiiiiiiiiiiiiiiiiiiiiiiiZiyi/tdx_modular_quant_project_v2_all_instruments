"""Standalone contract checks for isolated factor-cabinet runtime metadata."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pandas as pd

import config
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_SELECTED_CABINET,
    install_factor_source_model_map,
    list_factor_cabinet_runs,
    resolve_factor_source,
)
from functions.decision_council.proposals import _attach_state_machine_alpha_evidence


def _spec():
    runs = list_factor_cabinet_runs()
    assert runs, "No factor_cabinet runs found"
    return resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=str(runs[0]["run_id"]),
    )


def check_cabinet_context_is_complete_and_uses_cabinet_metadata() -> None:
    spec = _spec()
    context = spec.runtime_context()
    assert len(context.alpha_models) == spec.factor_count
    name = context.alpha_models[0]
    payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    row = next(item for item in payload["factors"] if item["factor_name"] == name)
    assert context.module_map[name] == row["module"]
    assert context.family_map[name] == row["family"]
    assert context.role_map[name]
    print("[PASS] cabinet module/family/role context matches factor_cabinet.json")


def check_cabinet_roles_do_not_fall_back_to_name_inference() -> None:
    spec = _spec()
    context = spec.runtime_context()
    names = list(context.alpha_models[:3])
    proposals = pd.DataFrame({
        "symbol": ["000001"] * 3,
        "model_name": names,
        "predicted_return_5d": [0.01, 0.02, 0.03],
        "reputation_weight": [1.0, 1.0, 1.0],
    })
    combined = pd.DataFrame({"symbol": ["000001"]})
    evidence = _attach_state_machine_alpha_evidence(combined, proposals, runtime_context=context)
    expected_modules = len({context.module_map[name] for name in names})
    assert int(evidence.loc[0, "alpha_active_module_count"]) == expected_modules
    print("[PASS] state-machine diversity evidence uses cabinet module metadata")


def check_invalid_cabinet_fails_closed() -> None:
    spec = _spec()
    payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    payload["factors"][0]["role"] = ""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "factor_cabinet.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            resolve_factor_source(
                factor_source=FACTOR_SOURCE_SELECTED_CABINET,
                factor_cabinet_path=path,
            )
        except ValueError:
            print("[PASS] invalid cabinet role fails closed")
            return
    raise AssertionError("cabinet with missing role was accepted")


def check_same_process_does_not_mutate_global_gate() -> None:
    before = dict(config.GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE)
    spec = _spec()
    install_factor_source_model_map(spec)
    assert dict(config.GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE) == before
    print("[PASS] cabinet resolution does not mutate global diversity gate")


def check_latest_cabinet_cannot_silently_skip_invalid_newest() -> None:
    spec = _spec()
    payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        valid = root / "older" / "factor_cabinet.json"
        invalid = root / "newer" / "factor_cabinet.json"
        valid.parent.mkdir()
        invalid.parent.mkdir()
        valid.write_text(json.dumps(payload), encoding="utf-8")
        payload["factors"][0]["role"] = "not_a_role"
        invalid.write_text(json.dumps(payload), encoding="utf-8")
        time.sleep(0.01)
        invalid.touch()
        try:
            resolve_factor_source(factor_source="latest_factor_cabinet", root=root)
        except ValueError:
            print("[PASS] latest cabinet fails instead of silently selecting an older valid cabinet")
            return
    raise AssertionError("invalid newest cabinet silently fell back to older cabinet")


if __name__ == "__main__":
    check_cabinet_context_is_complete_and_uses_cabinet_metadata()
    check_cabinet_roles_do_not_fall_back_to_name_inference()
    check_invalid_cabinet_fails_closed()
    check_same_process_does_not_mutate_global_gate()
    check_latest_cabinet_cannot_silently_skip_invalid_newest()
    print("factor_cabinet_state_machine_contract verification passed")
