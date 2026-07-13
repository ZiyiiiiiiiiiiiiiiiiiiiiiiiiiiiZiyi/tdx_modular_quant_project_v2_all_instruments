import inspect

from functions.decision_council.runner import GovernanceBacktestRunner, run_governance_backtest


def main() -> int:
    backtest_sig = inspect.signature(run_governance_backtest)
    runner_sig = inspect.signature(GovernanceBacktestRunner.__init__)
    for name in ["factor_source", "factor_cabinet_run_id", "factor_cabinet_path"]:
        assert name in backtest_sig.parameters, name
    assert "factor_source_spec" in runner_sig.parameters
    print("[PASS] governance runner accepts factor source and cabinet parameters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
