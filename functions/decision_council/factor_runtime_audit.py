"""Runtime audit records for governance factor-source loading."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_LEGACY,
    FACTOR_SOURCE_SELECTED_CABINET,
    FactorSourceSpec,
)


@dataclass(frozen=True)
class FactorRuntimeAudit:
    factor_source: str
    factor_cabinet_run_id: str
    factor_cabinet_path: str
    loaded_factor_count: int
    loaded_factor_names: list[str]
    loaded_role_distribution: dict[str, int]
    fallback_detected: bool
    fallback_reason: str
    legacy_used: bool
    runtime_model_count: int = 0
    attached_feature_column_count: int = 0
    missing_feature_columns: list[str] | None = None
    missing_roles: list[str] | None = None
    missing_modules: list[str] | None = None
    missing_families: list[str] | None = None
    cabinet_manifest_hash: str = ""
    runtime_contract_verified: bool = False

    @property
    def factor_count(self) -> int:
        return int(self.loaded_factor_count)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["factor_count"] = int(self.loaded_factor_count)
        return data


def build_factor_runtime_audit(
    spec: FactorSourceSpec,
    *,
    requested_factor_source: str | None = None,
    available_columns=None,
) -> FactorRuntimeAudit:
    """Build an auditable runtime record from the resolved factor-source spec."""
    requested = str(requested_factor_source or spec.factor_source or "").strip()
    legacy_used = spec.factor_source == FACTOR_SOURCE_LEGACY
    cabinet_requested = requested in {FACTOR_SOURCE_LATEST_CABINET, FACTOR_SOURCE_SELECTED_CABINET}
    if cabinet_requested and legacy_used:
        raise RuntimeError(
            "factor_cabinet fallback blocked: requested "
            f"{requested!r}, but resolved source is legacy_bundle"
        )

    factor_names: list[str] = []
    role_distribution: dict[str, int] = {}
    fallback_detected = False
    fallback_reason = ""
    factor_count = int(spec.factor_count or 0)

    if spec.uses_factor_cabinet:
        cabinet_path = Path(spec.factor_cabinet_path)
        if not cabinet_path.exists():
            raise FileNotFoundError(
                "factor_cabinet fallback blocked: resolved cabinet path does not exist: "
                f"{cabinet_path}"
            )
        payload = json.loads(cabinet_path.read_text(encoding="utf-8"))
        factors = payload.get("factors", [])
        frame = pd.DataFrame(factors)
        if frame.empty:
            raise ValueError(f"factor_cabinet fallback blocked: cabinet has no factors: {cabinet_path}")
        name_series = frame.get("factor_name", pd.Series(dtype=str)).fillna("").astype(str)
        factor_names = [name for name in name_series.tolist() if name.strip()]
        role_source = frame["role"] if "role" in frame.columns else frame.get("cabinet_role", pd.Series(dtype=str))
        role_series = role_source.fillna("").astype(str).str.strip()
        role_distribution = {str(k): int(v) for k, v in role_series.value_counts().sort_index().items()}
        factor_count = int(len(frame))
        if factor_count <= 0:
            fallback_detected = True
            fallback_reason = "factor_cabinet_resolved_with_zero_loaded_factors"
    context = spec.runtime_context()
    runtime_models = list(context.alpha_models)
    role_map = context.role_map
    module_map = context.module_map
    family_map = context.family_map
    missing_roles = [name for name in runtime_models if name not in role_map]
    missing_modules = [name for name in runtime_models if name not in module_map]
    missing_families = [name for name in runtime_models if name not in family_map]
    expected_columns = set(context.model_feature_map.values())
    columns = set(available_columns) if available_columns is not None else set()
    runtime_contract_verified = available_columns is not None
    missing_columns = sorted(expected_columns - columns) if runtime_contract_verified else []
    if missing_roles or missing_modules or missing_families or missing_columns:
        fallback_detected = True
        fallback_reason = "runtime_contract_incomplete"

    return FactorRuntimeAudit(
        factor_source=spec.factor_source,
        factor_cabinet_run_id=str(spec.factor_cabinet_run_id or ""),
        factor_cabinet_path=str(spec.factor_cabinet_path or ""),
        loaded_factor_count=factor_count,
        loaded_factor_names=factor_names,
        loaded_role_distribution=role_distribution,
        fallback_detected=bool(fallback_detected),
        fallback_reason=fallback_reason,
        legacy_used=legacy_used,
        runtime_model_count=len(runtime_models),
        attached_feature_column_count=(len(expected_columns - set(missing_columns)) if runtime_contract_verified else 0),
        missing_feature_columns=missing_columns,
        missing_roles=missing_roles,
        missing_modules=missing_modules,
        missing_families=missing_families,
        cabinet_manifest_hash=spec.cabinet_manifest_hash,
        runtime_contract_verified=runtime_contract_verified,
    )


def save_factor_runtime_audit(audit: FactorRuntimeAudit, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "factor_runtime_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_factor_runtime_audit(audit: FactorRuntimeAudit) -> None:
    roles = audit.loaded_role_distribution or {}
    role_labels = (
        ("strict_entry_alpha", ("strict_entry_alpha", "entry_alpha")),
        ("proxy_entry_alpha", ("proxy_entry_alpha", "entry_alpha_proxy")),
        ("timing_filter", ("timing_filter",)),
        ("risk_override", ("risk_override",)),
        ("liquidity_filter", ("liquidity_filter",)),
        ("hold_validation", ("hold_validation",)),
    )
    print("")
    print("FACTOR SOURCE AUDIT")
    print("")
    print("factor_source:")
    print(audit.factor_source)
    print("")
    print("factor_cabinet_run_id:")
    print(audit.factor_cabinet_run_id)
    print("")
    print("factor_cabinet_path:")
    print(audit.factor_cabinet_path)
    print("")
    print("factor_count:")
    print(audit.factor_count)
    print("")
    for label, aliases in role_labels:
        print(f"{label}:")
        print(int(sum(roles.get(alias, 0) for alias in aliases)))
        print("")
    print("legacy_bundle_loaded:")
    print(bool(audit.legacy_used))
    print("")
    print("fallback_detected:")
    print(bool(audit.fallback_detected))
    if audit.fallback_reason:
        print("")
        print("fallback_reason:")
        print(audit.fallback_reason)
