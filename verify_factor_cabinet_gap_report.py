from pathlib import Path
import json

import pandas as pd

from functions.decision_council.factor_cabinet_gap_report import build_factor_cabinet_gap_report
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LATEST_CABINET,
    FACTOR_SOURCE_SELECTED_CABINET,
    resolve_factor_source,
)


SOURCE_RUN_ID = "run20260706_183553_702097"


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def check_gap_report_outputs() -> None:
    saved = build_factor_cabinet_gap_report(
        factor_source=FACTOR_SOURCE_LATEST_CABINET,
        start_date="2021-01-01",
        end_date="2021-01-08",
        sample_rows=20_000,
        output_root=Path("reports") / "verify_factor_cabinet_gap_report",
    )
    required = {
        "summary",
        "report",
        "cabinet_structure",
        "cabinet_family_concentration",
        "cabinet_near_relative_concentration",
        "cabinet_role_gap",
        "cabinet_missing_family_gap",
        "factor_value_spearman_corr",
        "top_quantile_overlap",
    }
    assert required <= set(saved), sorted(set(required) - set(saved))
    for key in required:
        assert saved[key].exists(), f"missing {key}: {saved[key]}"
    summary = json.loads(saved["summary"].read_text(encoding="utf-8"))
    assert summary["factor_source"] == FACTOR_SOURCE_LATEST_CABINET
    assert int(summary["factor_count"]) > 0
    assert "recommendations" in summary
    role_gap = pd.read_csv(saved["cabinet_role_gap"])
    assert {"role", "factor_count", "status"}.issubset(role_gap.columns)
    missing = pd.read_csv(saved["cabinet_missing_family_gap"])
    assert {"expected_family", "present", "status"}.issubset(missing.columns)
    _pass("factor_cabinet gap report writes all required artifacts")


def check_source_cabinet_has_expected_gap_signals() -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=SOURCE_RUN_ID,
    )
    assert spec.factor_count == 116
    assert spec.strict_entry_alpha_count < 15
    assert spec.proxy_entry_alpha_count > 15
    _pass("source cabinet exposes entry-alpha shortage and proxy-entry pressure")


def check_cli_and_web_expose_task() -> None:
    main_text = Path("main.py").read_text(encoding="utf-8")
    web_text = Path("main_launcher_web.py").read_text(encoding="utf-8")
    assert "--factor-cabinet-gap-report" in main_text
    assert "run_factor_cabinet_gap_report_from_main" in main_text
    assert 'id="factor_cabinet_gap_report"' in web_text
    assert '"factor_cabinet_gap_report"' in web_text
    _pass("CLI and Web expose factor_cabinet_gap_report")


def main() -> None:
    check_source_cabinet_has_expected_gap_signals()
    check_cli_and_web_expose_task()
    check_gap_report_outputs()


if __name__ == "__main__":
    main()
