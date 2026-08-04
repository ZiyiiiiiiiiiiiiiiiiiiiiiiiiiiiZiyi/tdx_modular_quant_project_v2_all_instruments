from pathlib import Path


source = Path("tools/run_controlled_capital_matrix.py").read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


check('"changed_variable": "initial_cash_only"' in source, "matrix declares its single changed variable")
check("min_cash_buffer=1000.0" in source, "cash buffer amount remains fixed")
check('capital_usage_mode="allow_cash"' in source, "capital usage mode remains fixed")
check('factor_cabinet_run_id="pruned_run20260714_184846_581132_20260715_230524"' in source, "factor cabinet remains frozen")
check("runtime_identity_hash" in source, "each matrix row records runtime identity")
