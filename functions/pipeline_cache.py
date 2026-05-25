# -*- coding: utf-8 -*-
import hashlib
import json
from datetime import datetime
from pathlib import Path

from config import PIPELINE_CACHE_JSON


def file_fingerprint(path):
    file_path = Path(path)
    if not file_path.exists():
        return {
            "path": str(file_path),
            "exists": False,
        }

    stat = file_path.stat()
    return {
        "path": str(file_path),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def code_file_fingerprint(path):
    file_path = Path(path)
    fingerprint = file_fingerprint(file_path)
    if not fingerprint["exists"]:
        return fingerprint

    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    fingerprint["sha256"] = hasher.hexdigest()
    return fingerprint


def build_signature(payload):
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_pipeline_cache():
    if not PIPELINE_CACHE_JSON.exists():
        return {}
    try:
        return json.loads(PIPELINE_CACHE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_pipeline_cache(cache):
    PIPELINE_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_CACHE_JSON.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def should_skip_step(step_name, signature, outputs):
    cache = load_pipeline_cache()
    record = cache.get(step_name)
    if not record:
        return False
    if record.get("signature") != signature:
        return False
    return all(Path(path).exists() for path in outputs)


def mark_step_completed(step_name, signature, outputs, extra=None):
    cache = load_pipeline_cache()
    cache[step_name] = {
        "signature": signature,
        "outputs": [str(Path(path)) for path in outputs],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        cache[step_name]["extra"] = extra
    save_pipeline_cache(cache)
