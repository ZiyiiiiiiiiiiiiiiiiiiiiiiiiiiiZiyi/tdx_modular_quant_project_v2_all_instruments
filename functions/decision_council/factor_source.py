"""Resolve governance factor-source inputs for legacy bundles and factor cabinets."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


FACTOR_SOURCE_LEGACY = "legacy_bundle"
FACTOR_SOURCE_LATEST_CABINET = "latest_factor_cabinet"
FACTOR_SOURCE_SELECTED_CABINET = "selected_factor_cabinet"
FACTOR_SOURCE_CHOICES = (
    FACTOR_SOURCE_LEGACY,
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_SELECTED_CABINET,
)
FACTOR_CABINET_ROOT = Path("results/factor_cabinet")
LEGACY_GOVERNANCE_ALPHA_BUNDLE = "diversified_pre_screen_bundle_v2"


@dataclass(frozen=True)
class FactorSourceSpec:
    factor_source: str = FACTOR_SOURCE_LEGACY
    alpha_bundle: str = LEGACY_GOVERNANCE_ALPHA_BUNDLE
    factor_cabinet_run_id: str = ""
    factor_cabinet_path: str = ""
    factor_count: int = 0
    role_distribution: dict[str, int] | None = None
    strict_entry_alpha_count: int = 0
    proxy_entry_alpha_count: int = 0
    timing_filter_count: int = 0
    risk_override_count: int = 0
    liquidity_filter_count: int = 0
    hold_validation_count: int = 0
    model_feature_map: dict[str, str] | None = None
    role_map: dict[str, str] | None = None

    @property
    def uses_factor_cabinet(self) -> bool:
        return self.factor_source in {FACTOR_SOURCE_LATEST_CABINET, FACTOR_SOURCE_SELECTED_CABINET}

    @property
    def alpha_models(self) -> tuple[str, ...]:
        return tuple((self.model_feature_map or {}).keys())

    def summary_dict(self) -> dict:
        return {
            "factor_source": self.factor_source,
            "factor_cabinet_run_id": self.factor_cabinet_run_id,
            "factor_cabinet_path": self.factor_cabinet_path,
            "factor_count": int(self.factor_count),
            "role_distribution": json.dumps(self.role_distribution or {}, ensure_ascii=False, sort_keys=True),
            "strict_entry_alpha_count": int(self.strict_entry_alpha_count),
            "proxy_entry_alpha_count": int(self.proxy_entry_alpha_count),
            "timing_filter_count": int(self.timing_filter_count),
            "risk_override_count": int(self.risk_override_count),
            "liquidity_filter_count": int(self.liquidity_filter_count),
            "hold_validation_count": int(self.hold_validation_count),
        }


def normalize_factor_source(value: str | None) -> str:
    source = str(value or FACTOR_SOURCE_LEGACY).strip()
    if source == "":
        source = FACTOR_SOURCE_LEGACY
    if source not in FACTOR_SOURCE_CHOICES:
        raise ValueError(f"Invalid factor_source={source!r}; expected one of {FACTOR_SOURCE_CHOICES}")
    return source


def list_factor_cabinet_runs(root: str | Path = FACTOR_CABINET_ROOT) -> list[dict]:
    base = Path(root)
    if not base.exists():
        return []
    rows = []
    for run_dir in base.iterdir():
        cabinet_path = run_dir / "factor_cabinet.json"
        if run_dir.is_dir() and cabinet_path.exists():
            try:
                spec = _spec_from_cabinet_path(cabinet_path, factor_source=FACTOR_SOURCE_SELECTED_CABINET)
                row = spec.summary_dict()
                row["run_id"] = spec.factor_cabinet_run_id
                row["path"] = spec.factor_cabinet_path
                row["last_write_time"] = cabinet_path.stat().st_mtime
                rows.append(row)
            except Exception:
                continue
    return sorted(rows, key=lambda row: float(row.get("last_write_time") or 0.0), reverse=True)


def latest_factor_cabinet_path(root: str | Path = FACTOR_CABINET_ROOT) -> Path:
    runs = list_factor_cabinet_runs(root)
    if not runs:
        raise FileNotFoundError(f"No factor_cabinet.json found under {Path(root)}")
    return Path(runs[0]["path"])


def resolve_factor_source(
    *,
    factor_source: str | None = None,
    factor_cabinet_run_id: str | None = None,
    factor_cabinet_path: str | Path | None = None,
    alpha_bundle: str | None = None,
    root: str | Path = FACTOR_CABINET_ROOT,
) -> FactorSourceSpec:
    source = normalize_factor_source(factor_source)
    if source == FACTOR_SOURCE_LEGACY:
        selected_bundle = str(alpha_bundle or LEGACY_GOVERNANCE_ALPHA_BUNDLE).strip()
        if selected_bundle != LEGACY_GOVERNANCE_ALPHA_BUNDLE:
            raise ValueError(
                "legacy_bundle governance source is currently restricted to "
                f"{LEGACY_GOVERNANCE_ALPHA_BUNDLE}; got {selected_bundle!r}"
            )
        return FactorSourceSpec(
            factor_source=FACTOR_SOURCE_LEGACY,
            alpha_bundle=LEGACY_GOVERNANCE_ALPHA_BUNDLE,
        )

    if factor_cabinet_path:
        path = Path(factor_cabinet_path)
    elif source == FACTOR_SOURCE_LATEST_CABINET:
        path = latest_factor_cabinet_path(root)
    else:
        run_id = str(factor_cabinet_run_id or "").strip()
        if not run_id:
            raise ValueError("selected_factor_cabinet requires factor_cabinet_run_id")
        path = Path(root) / run_id / "factor_cabinet.json"
    return _spec_from_cabinet_path(path, factor_source=source)


def install_factor_source_model_map(spec: FactorSourceSpec) -> None:
    if not spec.uses_factor_cabinet:
        return
    model_feature_map = dict(spec.model_feature_map or {})
    if not model_feature_map:
        raise ValueError("factor_cabinet source resolved without any model feature mappings")

    import config
    from functions.decision_council import candidate_factor_cache, proposals

    role_map = {
        name: (_normalize_state_machine_role(role),)
        for name, role in (spec.role_map or {}).items()
        if name and role
    }
    config.GOVERNANCE_ALPHA_MODEL_FEATURES.update(model_feature_map)
    config.GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP.update(role_map)
    proposals.MODEL_FEATURES.update(model_feature_map)
    proposals.GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP.update(role_map)
    candidate_factor_cache.GOVERNANCE_ALPHA_MODEL_FEATURES.update(model_feature_map)


def _normalize_state_machine_role(role: str) -> str:
    aliases = {
        "strict_entry_alpha": "entry_alpha",
        "entry_alpha_proxy": "entry_alpha",
        "proxy_entry_alpha": "entry_alpha",
        "liquidity_filter": "liquidity_guard",
    }
    return aliases.get(str(role).strip(), str(role).strip())


def _spec_from_cabinet_path(path: Path, *, factor_source: str) -> FactorSourceSpec:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"factor_cabinet.json not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    factors = payload.get("factors", [])
    frame = pd.DataFrame(factors)
    if frame.empty:
        raise ValueError(f"factor_cabinet has no factors: {path}")
    run_id = str(payload.get("run_id") or path.parent.name)
    role_series = frame.get("role", frame.get("cabinet_role", pd.Series(dtype=str))).fillna("").astype(str)
    role_distribution = {str(k): int(v) for k, v in role_series.value_counts().sort_index().items()}
    raw_column = frame.get("raw_column", pd.Series(dtype=str)).fillna("").astype(str)
    factor_name = frame.get("factor_name", pd.Series(dtype=str)).fillna("").astype(str)
    model_feature_map = {
        str(name): str(raw)
        for name, raw in zip(factor_name.tolist(), raw_column.tolist())
        if str(name).strip() and str(raw).strip()
    }
    role_map = {
        str(name): str(role)
        for name, role in zip(factor_name.tolist(), role_series.tolist())
        if str(name).strip() and str(role).strip()
    }
    strict_flags = frame.get("strict_entry_alpha", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    return FactorSourceSpec(
        factor_source=factor_source,
        alpha_bundle=f"factor_cabinet:{run_id}",
        factor_cabinet_run_id=run_id,
        factor_cabinet_path=str(path),
        factor_count=int(len(frame)),
        role_distribution=role_distribution,
        strict_entry_alpha_count=int(strict_flags.sum()),
        proxy_entry_alpha_count=int(role_distribution.get("entry_alpha_proxy", 0)),
        timing_filter_count=int(role_distribution.get("timing_filter", 0)),
        risk_override_count=int(role_distribution.get("risk_override", 0)),
        liquidity_filter_count=int(role_distribution.get("liquidity_filter", 0)),
        hold_validation_count=int(role_distribution.get("hold_validation", 0)),
        model_feature_map=model_feature_map,
        role_map=role_map,
    )
