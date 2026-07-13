"""Fail-closed storage facade for Level-1 point-in-time A-share data."""
from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

from functions.data.pit_data_contract import PIT_LEVEL1_SCHEMAS, pit_asof, validate_pit_frame


DEFAULT_PIT_ROOT = Path("data/processed/pit_level1")


class PitDataUnavailableError(RuntimeError):
    pass


def pit_table_path(table_name: str, *, root: str | Path = DEFAULT_PIT_ROOT) -> Path:
    if table_name not in PIT_LEVEL1_SCHEMAS:
        raise KeyError(f"Unknown PIT table: {table_name}")
    return Path(root) / f"{table_name}.parquet"


def load_pit_table(
    table_name: str,
    *,
    root: str | Path = DEFAULT_PIT_ROOT,
    required: bool = True,
) -> pd.DataFrame:
    path = pit_table_path(table_name, root=root)
    if not path.exists():
        if required:
            raise PitDataUnavailableError(f"Required PIT table is unavailable: {path}")
        return pd.DataFrame(columns=PIT_LEVEL1_SCHEMAS[table_name])
    data = pd.read_parquet(path)
    audit = validate_pit_frame(data, table_name=table_name)
    failed = audit[~audit["passed"].fillna(False).astype(bool)]
    if not failed.empty:
        detail = "; ".join(f"{row.check}:{row.detail}" for row in failed.itertuples())
        raise PitDataUnavailableError(f"PIT validation failed for {path}: {detail}")
    return data


def load_pit_snapshot(
    table_name: str,
    *,
    as_of,
    effective_on=None,
    root: str | Path = DEFAULT_PIT_ROOT,
) -> pd.DataFrame:
    return pit_asof(
        load_pit_table(table_name, root=root, required=True),
        as_of=as_of,
        effective_on=effective_on,
    )


def pit_store_status(*, root: str | Path = DEFAULT_PIT_ROOT) -> pd.DataFrame:
    rows = []
    for table_name in PIT_LEVEL1_SCHEMAS:
        path = pit_table_path(table_name, root=root)
        manifest_path = path.with_suffix(".manifest.json")
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
        rows.append({
            "table_name": table_name,
            "path": str(path),
            "available": path.exists(),
            "status": "available" if path.exists() else "unavailable",
            "manifest_path": str(manifest_path),
            "manifest_available": manifest_path.exists(),
            "formal_eligible": bool(path.exists() and manifest.get("formal_eligible", False)),
        })
    return pd.DataFrame(rows)


def run_pit_preflight(
    *,
    mode: str = "research",
    root: str | Path = DEFAULT_PIT_ROOT,
    output_path: str | Path | None = None,
) -> dict:
    normalized_mode = str(mode or "research").strip().lower()
    if normalized_mode not in {"off", "research", "formal"}:
        raise ValueError(f"Invalid PIT mode={mode!r}; expected off, research, or formal")
    status = pit_store_status(root=root)
    missing = status.loc[~status["available"], "table_name"].astype(str).tolist()
    formal_ineligible = status.loc[
        status["available"] & ~status["formal_eligible"], "table_name"
    ].astype(str).tolist()
    runtime_state = (
        "disabled"
        if normalized_mode == "off"
        else ("degraded" if missing else ("research_only" if formal_ineligible else "available"))
    )
    payload = {
        "pit_mode": normalized_mode,
        "pit_runtime_state": runtime_state,
        "pit_root": str(Path(root)),
        "available_table_count": int(status["available"].sum()),
        "required_table_count": int(len(status)),
        "missing_tables": missing,
        "formal_ineligible_tables": formal_ineligible,
        "formal_pass": bool(not missing and not formal_ineligible),
    }
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if normalized_mode == "formal" and (missing or formal_ineligible):
        raise PitDataUnavailableError(
            f"Formal PIT preflight failed; missing tables: {missing}; "
            f"formal-ineligible tables: {formal_ineligible}"
        )
    return payload
