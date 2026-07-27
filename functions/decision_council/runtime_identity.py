"""Immutable runtime identity for governance/SCAP experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config import COMMISSION_RATE, SLIPPAGE_RATE, STAMP_DUTY_RATE, TRANSFER_FEE_RATE


RUNTIME_IDENTITY_SCHEMA_VERSION = "governance_runtime_identity_v1"
CONTROL_SCHEMA_VERSION = "scap_control_schema_v1"
REASON_SCHEMA_VERSION = "scap_reason_schema_v1"
SCORING_SCHEMA_VERSION = "mainline_v3_scoring_schema_v1"

_CODE_IDENTITY_FILES = (
    "config.py",
    "main.py",
    "functions/decision_council/runner.py",
    "functions/decision_council/runner_summary.py",
    "functions/decision_council/mainline_v3.py",
    "functions/decision_council/position_lifecycle.py",
    "functions/decision_council/policy.py",
    "functions/decision_council/execution_runtime.py",
    "functions/decision_council/small_capital_aggressive.py",
)


def build_runtime_identity(
    runner,
    *,
    dates,
    output_dir,
) -> dict:
    """Build the effective, result-relevant identity after date bounding."""
    normalized_dates = list(dates)
    profile = dict(getattr(runner, "capital_profile", {}) or {})
    factor_spec = getattr(runner, "factor_source_spec", None)
    factor_summary = factor_spec.summary_dict() if factor_spec is not None else {}
    code_fingerprint, code_files = governance_code_fingerprint()
    identity = {
        "schema_version": RUNTIME_IDENTITY_SCHEMA_VERSION,
        "control_schema_version": CONTROL_SCHEMA_VERSION,
        "reason_schema_version": REASON_SCHEMA_VERSION,
        "scoring_schema_version": SCORING_SCHEMA_VERSION,
        "strategy_logic_version": str(getattr(runner, "strategy_logic_version", "")),
        "governance_variant": str(getattr(runner, "governance_variant", "")),
        "governance_control_mode": str(getattr(runner, "governance_control_mode", "")),
        "capital_profile_name": str(profile.get("name", "custom")),
        "initial_cash": float(getattr(runner, "initial_cash", 0.0)),
        "max_positions": getattr(runner, "_max_positions_override", None),
        "min_cash_buffer": float(profile.get("min_cash_buffer", 0.0) or 0.0),
        "capital_usage_mode": str(getattr(runner, "capital_usage_mode", "")),
        "objective_metric": str(profile.get("objective_metric", "")),
        "special_strategy_version": str(profile.get("special_strategy_version", "")),
        "scap_exit_stage": str(profile.get("scap_exit_stage", "E0") or "E0").upper(),
        "scap_loss_stop": float(profile.get("scap_loss_stop", -0.12)),
        "universe_name": str(getattr(runner, "_universe_name", "") or ""),
        "universe_mode": str(getattr(runner, "_universe_mode", "") or ""),
        "alpha_bundle": str(getattr(runner, "_alpha_bundle", "") or ""),
        **factor_summary,
        "pit_runtime_state": str(getattr(runner, "pit_runtime_state", "")),
        "pit_level2_runtime_state": str(getattr(runner, "pit_level2_runtime_state", "")),
        "factor_temporal_isolation_pass": bool(
            getattr(runner, "factor_temporal_isolation_pass", False)
        ),
        "effective_start_date": (
            str(normalized_dates[0].date()) if normalized_dates else None
        ),
        "effective_end_date": (
            str(normalized_dates[-1].date()) if normalized_dates else None
        ),
        "effective_trading_days": len(normalized_dates),
        "experiment_sample_role": _experiment_sample_role(normalized_dates),
        "commission_rate": float(COMMISSION_RATE),
        "slippage_rate": float(SLIPPAGE_RATE),
        "stamp_duty_rate": float(STAMP_DUTY_RATE),
        "transfer_fee_rate": float(TRANSFER_FEE_RATE),
        "output_dir": str(Path(output_dir).resolve()),
        "code_fingerprint": code_fingerprint,
        "code_identity_files": code_files,
    }
    identity["runtime_identity_hash"] = _stable_hash(identity)
    return identity


def _experiment_sample_role(normalized_dates) -> str:
    """The diagnosed 2025-to-2026-05 window is development forever."""
    if not normalized_dates:
        return "empty"
    start = normalized_dates[0]
    end = normalized_dates[-1]
    development_start = __import__("pandas").Timestamp("2025-01-02")
    development_end = __import__("pandas").Timestamp("2026-05-29")
    if start <= development_end and end >= development_start:
        return "development_audit"
    return "unregistered_requires_preregistration"


def governance_code_fingerprint(project_root: Path | None = None) -> tuple[str, dict]:
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    files: dict[str, str] = {}
    for relative in _CODE_IDENTITY_FILES:
        path = root / relative
        files[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        )
    return _stable_hash(files), files


def _stable_hash(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
