"""Atomic, stage-aware manifest for governance result products."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import time


ARTIFACT_MANIFEST_SCHEMA = "governance_artifact_manifest_v1"


def update_artifact_manifest(
    output_dir,
    *,
    stage: str,
    status: str = "running",
    error: str = "",
    core_complete: bool | None = None,
    audit_complete: bool | None = None,
    web_complete: bool | None = None,
    research_products_complete: bool | None = None,
    artifact_name: str = "",
    artifact_status: str = "",
) -> Path:
    """Merge one stage update and replace the manifest atomically."""
    target = Path(output_dir) / "artifact_manifest.json"
    payload = _read_manifest(target)
    now = time.time()
    payload.update(
        {
            "schema_version": ARTIFACT_MANIFEST_SCHEMA,
            "status": str(status),
            "stage": str(stage),
            "owner_pid": os.getpid(),
            "updated_at": now,
            "updated_at_text": datetime.fromtimestamp(now).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "error": str(error),
        }
    )
    payload.setdefault("core_complete", False)
    payload.setdefault("audit_complete", False)
    payload.setdefault("web_complete", False)
    payload.setdefault("research_products_complete", False)
    payload.setdefault("stages", [])
    payload.setdefault("artifacts", {})
    if core_complete is not None:
        payload["core_complete"] = bool(core_complete)
    if audit_complete is not None:
        payload["audit_complete"] = bool(audit_complete)
    if web_complete is not None:
        payload["web_complete"] = bool(web_complete)
    if research_products_complete is not None:
        payload["research_products_complete"] = bool(
            research_products_complete
        )
    if not payload["stages"] or payload["stages"][-1].get("stage") != str(stage):
        payload["stages"].append(
            {"stage": str(stage), "status": str(status), "at": now}
        )
    else:
        payload["stages"][-1].update({"status": str(status), "at": now})
    if artifact_name:
        payload["artifacts"][str(artifact_name)] = {
            "status": str(artifact_status or status),
            "at": now,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(1, 9):
        temporary = target.with_name(
            f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            temporary.write_text(body, encoding="utf-8")
            os.replace(str(temporary), str(target))
            break
        except OSError:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            if attempt < 8:
                time.sleep(0.10 * attempt)
    # Observability must never destroy a completed economic artifact. If
    # Windows keeps the manifest open through all retries, the checkpoint and
    # next stage update will retry again.
    return target


def _read_manifest(target: Path) -> dict:
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {
            "schema_version": ARTIFACT_MANIFEST_SCHEMA,
            "status": "manifest_recovered",
            "stages": [],
            "artifacts": {},
        }
