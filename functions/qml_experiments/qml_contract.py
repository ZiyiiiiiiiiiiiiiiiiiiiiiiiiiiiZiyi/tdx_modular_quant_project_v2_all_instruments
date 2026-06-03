# -*- coding: utf-8 -*-
import pandas as pd

from config import (
    QML_MAX_DRAWDOWN_MULTIPLIER,
    QML_MIN_TEST_WINDOWS,
    QML_WILCOXON_P_THRESHOLD,
)


def build_qml_exit_criteria():
    return {
        "min_test_windows": QML_MIN_TEST_WINDOWS,
        "wilcoxon_p_threshold": QML_WILCOXON_P_THRESHOLD,
        "max_drawdown_multiplier": QML_MAX_DRAWDOWN_MULTIPLIER,
    }


def build_qml_experiment_registry():
    return pd.DataFrame(
        [
            {
                "experiment_name": "quantum_inspired_baseline",
                "legacy_prefix": "qubit_ml_",
                "normalized_prefix": "quantum_inspired_",
                "status": "active_research",
            },
            {
                "experiment_name": "true_qml_placeholder",
                "legacy_prefix": None,
                "normalized_prefix": "qml_",
                "status": "gated_by_exit_criteria",
            },
        ]
    )
