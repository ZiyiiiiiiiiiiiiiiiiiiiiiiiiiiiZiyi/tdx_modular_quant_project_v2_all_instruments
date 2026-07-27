"""Pre-registered causal questions and method-eligibility rules."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


CAUSAL_REGISTRY_VERSION = "factor_causal_design_registry_v1"


@dataclass(frozen=True)
class CausalDesignSpec:
    causal_question_id: str
    family: str
    treatment_definition: str
    outcome_definition: str
    unit: str
    method: str
    identification_assumption: str
    treatment_date_source: str = ""
    cutoff_source: str = ""
    interpretation_scope: str = "research_only"


METHOD_REQUIREMENTS = {
    "did": ("treatment_definition", "treatment_date_source"),
    "scm": ("treatment_definition", "treatment_date_source"),
    "sdid": ("treatment_definition", "treatment_date_source"),
    "rdd": ("treatment_definition", "cutoff_source"),
    "dml": ("treatment_definition",),
    "negative_control": ("treatment_definition",),
}


def validate_causal_design(spec: CausalDesignSpec) -> dict:
    method = str(spec.method).strip().lower()
    failures = []
    if method not in METHOD_REQUIREMENTS:
        failures.append("unsupported_causal_method")
    for field in METHOD_REQUIREMENTS.get(method, ()):
        if not str(getattr(spec, field, "") or "").strip():
            failures.append(f"missing_{field}")
    if method in {"did", "scm", "sdid", "rdd"} and spec.family in {"rsi", "orderflow", "breakout"}:
        failures.append("technical_predictor_has_no_registered_exogenous_treatment")
    return {
        **asdict(spec),
        "design_valid": not failures,
        "design_failures": "|".join(failures),
        "causal_registry_version": CAUSAL_REGISTRY_VERSION,
    }


def causal_design_registry_frame(specs) -> pd.DataFrame:
    return pd.DataFrame([validate_causal_design(spec) for spec in specs])
