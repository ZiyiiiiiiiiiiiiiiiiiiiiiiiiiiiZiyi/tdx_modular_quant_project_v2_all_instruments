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
    data_coverage_contract_verified: bool = False
    coverage_window_start: str = ""
    coverage_window_end: str = ""
    authorized_role_daily_coverage: dict[str, dict[str, Any]] | None = None
    coverage_failures: list[str] | None = None
    size_factor_pit_proxy_rows: int = 0
    size_factor_pit_proxy_dates: int = 0
    size_factor_pit_proxy_max_age_sessions: int = 0

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
    feature_frame: pd.DataFrame | None = None,
    decision_start=None,
    decision_end=None,
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

    coverage_verified = False
    coverage_start = ""
    coverage_end = ""
    role_coverage: dict[str, dict[str, Any]] = {}
    coverage_failures: list[str] = []
    proxy_rows = 0
    proxy_dates = 0
    proxy_max_age = 0
    if (
        spec.uses_factor_cabinet
        and feature_frame is not None
        and decision_start is not None
        and decision_end is not None
    ):
        coverage_verified = True
        coverage_start = pd.Timestamp(decision_start).strftime("%Y-%m-%d")
        coverage_end = pd.Timestamp(decision_end).strftime("%Y-%m-%d")
        role_coverage, coverage_failures = _audit_authorized_role_daily_coverage(
            feature_frame,
            context=context,
            decision_start=decision_start,
            decision_end=decision_end,
        )
        if coverage_failures:
            fallback_detected = True
            fallback_reason = "authorized_factor_daily_coverage_incomplete"
        window_dates = pd.to_datetime(feature_frame["date"], errors="coerce")
        proxy_window = feature_frame.loc[window_dates.between(pd.Timestamp(decision_start), pd.Timestamp(decision_end), inclusive="both")]
        if "factor_size_pit_proxy_used" in proxy_window.columns:
            proxy_used = proxy_window["factor_size_pit_proxy_used"].fillna(False).astype(bool)
            proxy_rows = int(proxy_used.sum())
            if proxy_rows:
                proxy_dates = int(pd.to_datetime(proxy_window.loc[proxy_used, "date"], errors="coerce").nunique())
                if "factor_size_pit_proxy_age_sessions" in proxy_window.columns:
                    proxy_max_age = int(
                        pd.to_numeric(
                            proxy_window.loc[proxy_used, "factor_size_pit_proxy_age_sessions"],
                            errors="coerce",
                        ).max()
                        or 0
                    )

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
        data_coverage_contract_verified=coverage_verified,
        coverage_window_start=coverage_start,
        coverage_window_end=coverage_end,
        authorized_role_daily_coverage=role_coverage,
        coverage_failures=coverage_failures,
        size_factor_pit_proxy_rows=proxy_rows,
        size_factor_pit_proxy_dates=proxy_dates,
        size_factor_pit_proxy_max_age_sessions=proxy_max_age,
    )


def _audit_authorized_role_daily_coverage(
    feature_frame: pd.DataFrame,
    *,
    context,
    decision_start,
    decision_end,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Verify that every trade-authorized factor role remains observable.

    Schema availability is insufficient: a column can exist while its entire
    cross-section is NaN after an upstream data source stops.  Entry authority
    is currently granted only to the strict ``entry_alpha`` role.  Proxy entry
    factors remain diagnostic unless a future immutable run contract grants
    them trading authority explicitly.
    """
    data = feature_frame
    if "date" not in data.columns:
        return {}, ["feature_frame_missing_date"]
    dates = pd.to_datetime(data["date"], errors="coerce")
    start = pd.Timestamp(decision_start)
    end = pd.Timestamp(decision_end)
    window = data.loc[dates.between(start, end, inclusive="both")].copy()
    window["date"] = pd.to_datetime(window["date"], errors="coerce")
    observed_dates = pd.Index(window["date"].dropna().drop_duplicates().sort_values())
    if observed_dates.empty:
        return {}, [f"no_observed_feature_dates:{start.date()}:{end.date()}"]

    model_feature_map = dict(getattr(context, "model_feature_map", {}) or {})
    primary_roles = dict(getattr(context, "primary_role_map", {}) or {})
    family_map = dict(getattr(context, "family_map", {}) or {})
    authorized_roles = {"entry_alpha"}
    output: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for role in sorted(authorized_roles):
        models = [name for name in model_feature_map if str(primary_roles.get(name, "")) == role]
        columns = [model_feature_map[name] for name in models]
        if not models:
            failures.append(f"authorized_role_has_no_models:{role}")
            output[role] = {"configured_model_count": 0, "invalid_dates": []}
            continue
        missing = sorted(column for column in columns if column not in window.columns)
        invalid_dates: list[str] = []
        daily_active_models: list[int] = []
        daily_active_families: list[int] = []
        daily_valid_rows: list[int] = []
        for date in observed_dates:
            day = window.loc[window["date"].eq(date)]
            active = 0
            active_names: list[str] = []
            valid_rows = pd.Series(False, index=day.index)
            for model_name, column in zip(models, columns):
                if column not in day.columns:
                    continue
                numeric = pd.to_numeric(day[column], errors="coerce")
                finite = numeric.notna()
                if bool(finite.any()):
                    active += 1
                    active_names.append(model_name)
                    valid_rows = valid_rows | finite
            daily_active_models.append(active)
            daily_active_families.append(
                len({str(family_map.get(name, "unknown")) for name in active_names})
            )
            daily_valid_rows.append(int(valid_rows.sum()))
            if active <= 0 or int(valid_rows.sum()) <= 0:
                invalid_dates.append(pd.Timestamp(date).strftime("%Y-%m-%d"))
        output[role] = {
            "configured_model_count": len(models),
            "configured_family_count": len(
                {str(family_map.get(name, "unknown")) for name in models}
            ),
            "configured_columns": columns,
            "missing_columns": missing,
            "observed_date_count": len(observed_dates),
            "minimum_active_model_count": min(daily_active_models, default=0),
            "minimum_active_family_count": min(daily_active_families, default=0),
            "minimum_valid_cross_section_rows": min(daily_valid_rows, default=0),
            "first_invalid_date": invalid_dates[0] if invalid_dates else "",
            "last_valid_date": (
                max(
                    pd.Timestamp(date)
                    for date, active, rows in zip(observed_dates, daily_active_models, daily_valid_rows)
                    if active > 0 and rows > 0
                ).strftime("%Y-%m-%d")
                if any(active > 0 and rows > 0 for active, rows in zip(daily_active_models, daily_valid_rows))
                else ""
            ),
            "invalid_dates": invalid_dates,
        }
        if missing:
            failures.append(f"authorized_role_missing_columns:{role}:{','.join(missing)}")
        if invalid_dates:
            failures.append(
                f"authorized_role_has_zero_daily_coverage:{role}:"
                f"{invalid_dates[0]}:{invalid_dates[-1]}:{len(invalid_dates)}"
            )
    return output, failures


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
