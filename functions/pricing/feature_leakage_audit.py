# -*- coding: utf-8 -*-
FUTURE_COLUMN_PREFIXES = (
    "future_",
    "futureret_",
    "future_ret_",
    "next_",
)

PATH_DEPENDENT_LABEL_TOKENS = (
    "drawdown",
    "new_high",
    "new_low",
    "path_",
    "semivariance_window",
)

FORBIDDEN_FEATURE_PREFIXES = (
    "reward_",
    "_ml_target",
)


def is_future_like_column(column_name):
    normalized = str(column_name).strip().lower()
    return normalized.startswith(FUTURE_COLUMN_PREFIXES)


def is_forbidden_feature_column(column_name):
    normalized = str(column_name).strip().lower()
    return normalized.startswith(FORBIDDEN_FEATURE_PREFIXES)


def find_future_like_columns(columns):
    return sorted(
        [column for column in columns if is_future_like_column(column)]
    )


def find_forbidden_feature_columns(columns):
    return sorted(
        [column for column in columns if is_forbidden_feature_column(column)]
    )


def validate_label_metadata(label_name, metadata):
    issues = []
    if not isinstance(metadata, dict):
        return [f"{label_name}: metadata must be a dict"]

    uses_path_dependent_stat = bool(metadata.get("uses_path_dependent_stat", False))
    formula_text = str(metadata.get("formula", "")).lower()

    if uses_path_dependent_stat:
        issues.append(f"{label_name}: path-dependent label flag is not allowed")

    matched_tokens = [
        token for token in PATH_DEPENDENT_LABEL_TOKENS
        if token in formula_text
    ]
    if matched_tokens:
        issues.append(
            f"{label_name}: formula contains path-dependent tokens {matched_tokens}"
        )

    return issues


def audit_feature_columns(feature_columns, label_metadata_map=None):
    feature_columns = list(feature_columns)
    label_metadata_map = label_metadata_map or {}

    future_columns = find_future_like_columns(feature_columns)
    forbidden_columns = find_forbidden_feature_columns(feature_columns)

    label_issues = []
    for label_name, metadata in label_metadata_map.items():
        label_issues.extend(validate_label_metadata(label_name, metadata))

    return {
        "future_like_feature_columns": future_columns,
        "forbidden_feature_columns": forbidden_columns,
        "label_metadata_issues": label_issues,
        "is_clean": not (future_columns or forbidden_columns or label_issues),
    }
