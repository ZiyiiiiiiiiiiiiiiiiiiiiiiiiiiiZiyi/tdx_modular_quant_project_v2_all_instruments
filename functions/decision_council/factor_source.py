"""Resolve governance factor-source inputs for legacy bundles and factor cabinets."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

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
_CABINET_ROLES = frozenset({
    "entry_alpha", "entry_alpha_proxy", "timing_filter", "risk_override",
    "liquidity_filter", "hold_validation", "sell_trigger",
})

# These four appeal-judge factors are materialized by the main feature pipeline
# under their established score columns. Keep this allowlist narrow: arbitrary
# legacy score columns must not enter a factor cabinet unnoticed.
FACTOR_CABINET_PASSTHROUGH_COLUMNS = frozenset({
    "score_orderflow_close_drive",
    "score_orderflow_efficiency",
    "score_price_volume_breakout",
    "score_turtle_breakout",
})


def is_factor_cabinet_runtime_column(column: object) -> bool:
    value = str(column or "").strip()
    return value.startswith("cand_") or value in FACTOR_CABINET_PASSTHROUGH_COLUMNS


@dataclass(frozen=True)
class FactorRuntimeContext:
    """Immutable factor metadata used by one governance run only."""

    factor_source: str
    cabinet_run_id: str
    cabinet_manifest_hash: str
    model_feature_map: object
    role_map: object
    module_map: object
    family_map: object
    strict_entry_alpha_map: object
    diversity_gate: object
    direction_map: object = None

    @property
    def alpha_models(self) -> tuple[str, ...]:
        return tuple(self.model_feature_map)


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
    module_map: dict[str, str] | None = None
    family_map: dict[str, str] | None = None
    strict_entry_alpha_map: dict[str, bool] | None = None
    direction_map: dict[str, str] | None = None
    cabinet_manifest_hash: str = ""

    @property
    def uses_factor_cabinet(self) -> bool:
        return self.factor_source in {FACTOR_SOURCE_LATEST_CABINET, FACTOR_SOURCE_SELECTED_CABINET}

    @property
    def alpha_models(self) -> tuple[str, ...]:
        return tuple((self.model_feature_map or {}).keys())

    def runtime_context(self) -> FactorRuntimeContext:
        """Return per-run metadata without mutating process-wide configuration."""
        if self.uses_factor_cabinet:
            missing = [
                name for name in self.alpha_models
                if name not in (self.role_map or {})
                or name not in (self.module_map or {})
                or name not in (self.family_map or {})
            ]
            if missing:
                raise ValueError(f"factor_cabinet runtime metadata missing for models: {missing[:10]}")
            from config import GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE
            gate = dict(GOVERNANCE_STATE_MACHINE_DIVERSITY_GATE)
            # Cabinets without sell-trigger factors cannot satisfy a positive sell vote.
            if "sell_trigger" not in set((self.role_map or {}).values()):
                gate["min_sell_trigger_votes"] = 0
            return FactorRuntimeContext(
                factor_source=self.factor_source,
                cabinet_run_id=self.factor_cabinet_run_id,
                cabinet_manifest_hash=self.cabinet_manifest_hash,
                model_feature_map=MappingProxyType(dict(self.model_feature_map or {})),
                role_map=MappingProxyType({name: (_normalize_state_machine_role(role),) for name, role in (self.role_map or {}).items()}),
                module_map=MappingProxyType(dict(self.module_map or {})),
                family_map=MappingProxyType(dict(self.family_map or {})),
                strict_entry_alpha_map=MappingProxyType(dict(self.strict_entry_alpha_map or {})),
                diversity_gate=MappingProxyType(gate),
                direction_map=MappingProxyType(dict(self.direction_map or {})),
            )
        return FactorRuntimeContext(
            factor_source=self.factor_source,
            cabinet_run_id="",
            cabinet_manifest_hash="",
            model_feature_map=MappingProxyType({}), role_map=MappingProxyType({}),
            module_map=MappingProxyType({}), family_map=MappingProxyType({}),
            strict_entry_alpha_map=MappingProxyType({}), diversity_gate=MappingProxyType({}),
            direction_map=MappingProxyType({}),
        )

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
    base = Path(root)
    candidates = [
        run_dir / "factor_cabinet.json"
        for run_dir in base.iterdir()
        if run_dir.is_dir() and (run_dir / "factor_cabinet.json").exists()
    ] if base.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No factor_cabinet.json found under {Path(root)}")
    # Do not use the UI listing here: it intentionally omits malformed entries.
    # The newest artifact must either validate or fail; selecting an older cabinet
    # would be an unreported fallback.
    return max(candidates, key=lambda path: path.stat().st_mtime)


def factor_source_output_label(spec: FactorSourceSpec) -> str:
    """Return a short, collision-resistant output-path component.

    Cabinet run ids are intentionally descriptive and can be long enough to
    push Windows result artifact paths past the traditional 260-character
    boundary.  The full run id remains in metadata and runtime audit files;
    this label is used only for the directory component.
    """
    if not spec.uses_factor_cabinet:
        return str(spec.alpha_bundle or LEGACY_GOVERNANCE_ALPHA_BUNDLE)
    run_id = str(spec.factor_cabinet_run_id or "factor_cabinet")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    return f"cab_{digest}"


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

    if source == FACTOR_SOURCE_LATEST_CABINET:
        # Stale Web form fields must never pin an automatic-latest request to
        # an older cabinet. Explicit paths belong to selected mode only.
        path = latest_factor_cabinet_path(root)
    else:
        requested_run_id = str(factor_cabinet_run_id or "").strip()
        if not requested_run_id:
            raise ValueError("selected_factor_cabinet requires factor_cabinet_run_id")
        path = (
            Path(factor_cabinet_path)
            if factor_cabinet_path
            else Path(root) / requested_run_id / "factor_cabinet.json"
        )
        spec = _spec_from_cabinet_path(path, factor_source=source)
        if spec.factor_cabinet_run_id != requested_run_id:
            raise ValueError(
                "selected_factor_cabinet run_id/path mismatch: "
                f"requested {requested_run_id!r}, loaded {spec.factor_cabinet_run_id!r} from {path}"
            )
        return spec
    return _spec_from_cabinet_path(path, factor_source=source)


def install_factor_source_model_map(spec: FactorSourceSpec) -> None:
    """Compatibility shim. Cabinet callers must pass ``runtime_context`` instead.

    Keeping this function side-effect free prevents one Web task from altering the
    next task in the same Python process.
    """
    if not spec.uses_factor_cabinet:
        return None
    spec.runtime_context()
    return None


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
    required_columns = {"factor_name", "raw_column", "role", "module", "family"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"factor_cabinet missing required columns: {missing_columns}")
    role_series = frame["role"].fillna("").astype(str).str.strip()
    role_distribution = {str(k): int(v) for k, v in role_series.value_counts().sort_index().items()}
    raw_column = frame["raw_column"].fillna("").astype(str).str.strip()
    factor_name = frame["factor_name"].fillna("").astype(str).str.strip()
    module_series = frame["module"].fillna("").astype(str).str.strip()
    family_series = frame["family"].fillna("").astype(str).str.strip()
    if "direction" in frame.columns:
        direction_series = frame["direction"].fillna("higher_better").astype(str).str.strip()
        direction_series = direction_series.where(direction_series.ne(""), "higher_better")
    else:
        direction_series = pd.Series("higher_better", index=frame.index)
    invalid_directions = ~direction_series.isin({"higher_better", "lower_better"})
    if invalid_directions.any():
        raise ValueError(
            "factor_cabinet contains invalid directions: "
            f"{sorted(direction_series[invalid_directions].unique().tolist())}"
        )
    valid_runtime_column = raw_column.map(is_factor_cabinet_runtime_column)
    invalid = frame.loc[
        factor_name.eq("") | raw_column.eq("") | ~valid_runtime_column
        | role_series.eq("") | ~role_series.isin(_CABINET_ROLES)
        | module_series.eq("") | family_series.eq(""),
        ["factor_name", "raw_column", "role", "module", "family"],
    ]
    if not invalid.empty:
        raise ValueError(f"factor_cabinet contains invalid runtime metadata: {invalid.head(5).to_dict('records')}")
    if factor_name.duplicated().any() or raw_column.duplicated().any():
        raise ValueError("factor_cabinet requires unique factor_name and raw_column values")
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
    module_map = {str(name): str(module) for name, module in zip(factor_name.tolist(), module_series.tolist())}
    family_map = {str(name): str(family) for name, family in zip(factor_name.tolist(), family_series.tolist())}
    direction_map = {
        str(name): str(direction)
        for name, direction in zip(factor_name.tolist(), direction_series.tolist())
    }
    strict_flags = frame.get("strict_entry_alpha", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    strict_map = {str(name): bool(flag) for name, flag in zip(factor_name.tolist(), strict_flags.tolist())}
    invalid_strict = [name for name, flag in strict_map.items() if flag and role_map.get(name) != "entry_alpha"]
    if invalid_strict:
        raise ValueError(f"strict_entry_alpha requires role=entry_alpha: {invalid_strict[:10]}")
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
        module_map=module_map,
        family_map=family_map,
        direction_map=direction_map,
        strict_entry_alpha_map=strict_map,
        cabinet_manifest_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
