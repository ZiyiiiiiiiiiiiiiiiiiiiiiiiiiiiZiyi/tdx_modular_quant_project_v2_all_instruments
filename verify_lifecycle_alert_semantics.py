from pathlib import Path


ROOT = Path(__file__).resolve().parent


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    runner = (ROOT / "functions/decision_council/runner.py").read_text(encoding="utf-8")
    web = (ROOT / "functions/decision_council/live_monitor_web.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "functions/decision_council/live_monitor_dashboard.py").read_text(encoding="utf-8")

    expect('"paper_exit_reason": state.get("paper_exit_reason", "")' in runner,
           "monitor payload preserves the paper exit reason")
    expect('"paper_exit_state": bool(state.get("paper_exit_state", False))' in runner,
           "monitor payload distinguishes paper and executable exits")
    expect('"snapshot_date":' in runner, "lifecycle payload identifies its market-data snapshot date")
    expect('"giveback_armed":' in runner, "lifecycle payload explicitly identifies whether giveback is economically armed")

    for source, name in ((web, "live monitor"), (dashboard, "dashboard")):
        expect("纸面观察：" in source and "（未执行）" in source,
               f"{name} labels paper exits as non-executable")
        expect("买后表现失败" in source,
               f"{name} calls the post-purchase outcome failure by its correct meaning")
        expect("giveback_armed" in source and '"--"' in source,
               f"{name} suppresses an unarmed giveback percentage")

    print("[PASS] lifecycle alert semantics verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
