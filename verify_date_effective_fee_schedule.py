from functions.execution.fee_schedule import commission_cost, stamp_duty_rate_for


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    check(stamp_duty_rate_for("2023-08-27", fallback_rate=0.001) == 0.001, "pre-cut stamp duty uses 0.1 percent")
    check(stamp_duty_rate_for("2023-08-28", fallback_rate=0.001) == 0.0005, "post-cut stamp duty uses 0.05 percent")
    check(stamp_duty_rate_for("2024-01-02", fallback_rate=0.001) == 0.0005, "2024 backtest uses effective stamp duty")
    check(commission_cost(1000, rate=0.0003, minimum=5.0) == 5.0, "minimum commission is applied")
    check(abs(commission_cost(100000, rate=0.0003, minimum=5.0) - 30.0) < 1e-12, "rate commission applies above minimum")


if __name__ == "__main__":
    main()
