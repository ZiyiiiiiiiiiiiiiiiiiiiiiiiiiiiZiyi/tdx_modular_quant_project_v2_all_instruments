# -*- coding: utf-8 -*-
"""Run-scoped output naming helpers.

All research tables and charts should be written with a run timestamp so a new
run cannot silently overwrite a previous run's artifacts.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


_RUN_TIMESTAMP = os.environ.get("TDX_RUN_TIMESTAMP") or datetime.now().strftime("%Y%m%d_%H%M%S")
os.environ["TDX_RUN_TIMESTAMP"] = _RUN_TIMESTAMP


def run_timestamp() -> str:
    return _RUN_TIMESTAMP


def reset_run_timestamp(value: str | None = None) -> str:
    """Refresh the run timestamp for interactive reruns in long-lived kernels."""
    global _RUN_TIMESTAMP
    _RUN_TIMESTAMP = value or datetime.now().strftime("%Y%m%d_%H%M%S")
    os.environ["TDX_RUN_TIMESTAMP"] = _RUN_TIMESTAMP
    return _RUN_TIMESTAMP


def run_suffix() -> str:
    return f"_run{_RUN_TIMESTAMP}"


def dated_path(path) -> Path:
    target = Path(path)
    if target.suffix:
        return target.with_name(f"{target.stem}{run_suffix()}{target.suffix}")
    return target / f"run{_RUN_TIMESTAMP}"


def dated_run_dir(base_dir) -> Path:
    return Path(base_dir) / f"run{_RUN_TIMESTAMP}"
