import main_launcher_web


def main() -> int:
    html = main_launcher_web._render_run_html()
    for token in (
        'id="orderflow_parameter_research"',
        'id="pit_level1_audit"',
        'id="registered_mainline_v2_suite"',
        'id="pit_mode"',
        'value="research" selected',
        'id="research_max_runtime_seconds"',
        'value="1800"',
        'research_max_runtime_seconds: researchMaxRuntimeSeconds',
    ):
        assert token in html, token
    all_tasks_line = next(line for line in html.splitlines() if "const tasks =" in line and "main_pipeline" in line)
    assert "orderflow_parameter_research" not in all_tasks_line
    assert "registered_mainline_v2_suite" not in all_tasks_line
    print("[PASS] web exposes bounded research controls without adding long tasks to run-all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
