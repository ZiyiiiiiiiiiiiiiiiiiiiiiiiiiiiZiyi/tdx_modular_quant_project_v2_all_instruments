from pathlib import Path


def main() -> int:
    report_text = Path("build_governance_mainline_report.py").read_text(encoding="utf-8")
    summary_text = Path("functions/decision_council/runner_summary.py").read_text(encoding="utf-8")
    unified_text = Path("functions/report_builder.py").read_text(encoding="utf-8")
    for text in [report_text, unified_text]:
        assert "factor_cabinet_path" in text
        assert "factor_source" in text
    assert "factor_source_spec.summary_dict()" in summary_text
    assert "Strict entry alpha count" in report_text
    assert "Proxy entry alpha count" in report_text
    print("[PASS] governance reports include factor source and factor_cabinet_path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
