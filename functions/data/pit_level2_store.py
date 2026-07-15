"""Fail-closed Financial/Event PIT Level-2 storage and validation."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


DEFAULT_PIT_LEVEL2_ROOT = Path("data/processed/pit_level2")

PIT_LEVEL2_SCHEMAS = {
    "financial_statement_pit": (
        "symbol", "report_period", "statement_type", "period_value_basis", "known_at", "effective_from",
        "source", "source_document_id", "revision_id", "downloaded_at",
        "revenue", "net_profit", "deducted_net_profit", "gross_profit",
        "operating_profit", "operating_cashflow", "capex", "total_assets",
        "total_equity", "industry",
    ),
    "valuation_daily_pit": (
        "symbol", "valuation_date", "known_at", "effective_from", "source",
        "source_document_id", "revision_id", "downloaded_at", "market_cap",
        "float_cap", "pe_ttm", "pb_mrq",
    ),
    "corporate_event_pit": (
        "symbol", "event_id", "event_type", "event_stage", "announcement_time",
        "known_at", "effective_from", "source", "source_document_id", "revision_id",
        "downloaded_at", "direction", "strength", "cancelled", "revision_of",
    ),
}


class PitLevel2UnavailableError(RuntimeError):
    pass


def pit_level2_table_path(
    table_name: str,
    *,
    root: str | Path = DEFAULT_PIT_LEVEL2_ROOT,
) -> Path:
    if table_name not in PIT_LEVEL2_SCHEMAS:
        raise KeyError(f"Unknown PIT Level-2 table: {table_name}")
    return Path(root) / f"{table_name}.parquet"


def validate_pit_level2_frame(frame: pd.DataFrame, *, table_name: str) -> pd.DataFrame:
    if table_name not in PIT_LEVEL2_SCHEMAS:
        raise KeyError(f"Unknown PIT Level-2 table: {table_name}")
    required = set(PIT_LEVEL2_SCHEMAS[table_name])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{table_name} missing required columns: {missing}")
    data = frame.copy()
    datetime_columns = [
        column for column in (
            "report_period", "valuation_date", "announcement_time", "known_at",
            "effective_from", "downloaded_at",
        ) if column in data.columns
    ]
    for column in datetime_columns:
        data[column] = pd.to_datetime(data[column], errors="coerce")
    identity = {
        "financial_statement_pit": ["symbol", "report_period", "statement_type", "revision_id"],
        "valuation_daily_pit": ["symbol", "valuation_date", "revision_id"],
        "corporate_event_pit": ["symbol", "event_id", "revision_id"],
    }[table_name]
    duplicate_count = int(data.duplicated(identity).sum())
    known_missing = data["known_at"].isna()
    effective_missing = data["effective_from"].isna()
    effective_before_known = (
        data["effective_from"].dt.normalize()
        < data["known_at"].dt.normalize()
    ).fillna(False)
    source_missing = data["source"].fillna("").astype(str).str.strip().eq("")
    document_missing = data["source_document_id"].fillna("").astype(str).str.strip().eq("")
    checks = [
        {"check": "required_columns", "passed": True, "detail": f"columns={len(data.columns)}"},
        {"check": "unique_revision_key", "passed": duplicate_count == 0, "detail": f"duplicates={duplicate_count}"},
        {"check": "known_at_present", "passed": not known_missing.any(), "detail": f"missing={int(known_missing.sum())}"},
        {"check": "effective_from_present", "passed": not effective_missing.any(), "detail": f"missing={int(effective_missing.sum())}"},
        {"check": "effective_not_before_known", "passed": not effective_before_known.any(), "detail": f"invalid={int(effective_before_known.sum())}"},
        {"check": "source_present", "passed": not source_missing.any(), "detail": f"missing={int(source_missing.sum())}"},
        {"check": "source_document_present", "passed": not document_missing.any(), "detail": f"missing={int(document_missing.sum())}"},
    ]
    if table_name == "financial_statement_pit":
        invalid_period = data["report_period"].isna() | data["report_period"].gt(data["known_at"])
        checks.append({
            "check": "report_period_known_order",
            "passed": not invalid_period.any(),
            "detail": f"invalid={int(invalid_period.sum())}",
        })
    if table_name == "corporate_event_pit":
        invalid_cancelled = ~data["cancelled"].isin([True, False, 0, 1])
        checks.append({
            "check": "cancelled_boolean",
            "passed": not invalid_cancelled.any(),
            "detail": f"invalid={int(invalid_cancelled.sum())}",
        })
    return pd.DataFrame(checks)


def load_pit_level2_table(
    table_name: str,
    *,
    root: str | Path = DEFAULT_PIT_LEVEL2_ROOT,
    required: bool = True,
    filters=None,
) -> pd.DataFrame:
    path = pit_level2_table_path(table_name, root=root)
    if not path.exists():
        if required:
            raise PitLevel2UnavailableError(f"Required PIT Level-2 table is unavailable: {path}")
        return pd.DataFrame(columns=PIT_LEVEL2_SCHEMAS[table_name])
    data = pd.read_parquet(path, filters=filters)
    audit = validate_pit_level2_frame(data, table_name=table_name)
    failed = audit[~audit["passed"].fillna(False).astype(bool)]
    if not failed.empty:
        detail = "; ".join(f"{row.check}:{row.detail}" for row in failed.itertuples())
        raise PitLevel2UnavailableError(f"PIT Level-2 validation failed for {path}: {detail}")
    return data


def pit_level2_store_status(*, root: str | Path = DEFAULT_PIT_LEVEL2_ROOT) -> pd.DataFrame:
    rows = []
    for table_name in PIT_LEVEL2_SCHEMAS:
        path = pit_level2_table_path(table_name, root=root)
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
            "manifest_available": manifest_path.exists(),
            "formal_eligible": bool(path.exists() and manifest.get("formal_eligible", False)),
            "status": "available" if path.exists() else "unavailable",
        })
    return pd.DataFrame(rows)


def run_pit_level2_preflight(
    *,
    mode: str = "research",
    root: str | Path = DEFAULT_PIT_LEVEL2_ROOT,
    output_path: str | Path | None = None,
) -> dict:
    normalized_mode = str(mode or "research").strip().lower()
    if normalized_mode not in {"off", "research", "formal"}:
        raise ValueError(f"Invalid PIT Level-2 mode={mode!r}; expected off, research, or formal")
    status = pit_level2_store_status(root=root)
    missing = status.loc[~status["available"], "table_name"].astype(str).tolist()
    formal_ineligible = status.loc[
        status["available"] & ~status["formal_eligible"], "table_name"
    ].astype(str).tolist()
    payload = {
        "pit_level": 2,
        "pit_mode": normalized_mode,
        "pit_runtime_state": (
            "disabled" if normalized_mode == "off"
            else ("degraded" if missing else ("research_only" if formal_ineligible else "available"))
        ),
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
        raise PitLevel2UnavailableError(
            f"Formal PIT Level-2 preflight failed; missing tables: {missing}; "
            f"formal-ineligible tables: {formal_ineligible}"
        )
    return payload
