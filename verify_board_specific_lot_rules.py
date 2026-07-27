from functions.execution.security_trading_rules import (
    is_legal_order_quantity,
    legal_buy_quantity,
    permission_allows,
    trading_rule_for,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    star = trading_rule_for("sh688582", trade_date="2024-01-04")
    check(star.minimum_buy_quantity == 200, "STAR minimum buy quantity is 200")
    check(not is_legal_order_quantity("sh688582", "buy", 100, trade_date="2024-01-04"), "STAR 100-share buy is rejected")
    check(is_legal_order_quantity("sh688582", "buy", 200, trade_date="2024-01-04"), "STAR 200-share buy is accepted")
    check(legal_buy_quantity("sh688582", 201, trade_date="2024-01-04") == 201, "STAR increments above 200 may be one share")
    check(is_legal_order_quantity("sz301200", "buy", 100, trade_date="2024-01-04"), "ChiNext 100-share buy is accepted")
    check(not permission_allows("sh688582"), "STAR permission defaults to denied")
    check(permission_allows("sh688582", allow_star_market=True), "explicit STAR permission is honored")


if __name__ == "__main__":
    main()
