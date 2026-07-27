from functions.execution.execution_rules import open_price_limit_blocked


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    check(
        open_price_limit_blocked(side="buy", open_price=11.0, limit_up_price=11.0),
        "buy at the open limit is conservatively blocked",
    )
    check(
        not open_price_limit_blocked(side="buy", open_price=10.2, limit_up_price=11.0),
        "later close at limit cannot block a below-limit open",
    )
    check(
        open_price_limit_blocked(side="sell", open_price=9.0, limit_down_price=9.0),
        "sell at the open limit is conservatively blocked",
    )


if __name__ == "__main__":
    main()
