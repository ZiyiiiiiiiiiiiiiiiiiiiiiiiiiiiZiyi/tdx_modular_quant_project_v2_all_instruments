"""Compatibility wrapper for centralized strategy parameters.

All editable strategy parameters live in config.py.  This module keeps older
imports stable while preventing a second source of truth.
"""
from __future__ import annotations

from config import STRATEGY_PARAMS, STRATEGY_PARAMS_VERSION, strategy_params_hash

__all__ = ["STRATEGY_PARAMS", "STRATEGY_PARAMS_VERSION", "strategy_params_hash"]
