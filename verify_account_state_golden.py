# -*- coding: utf-8 -*-
"""Independent golden checks for the first account-state implementation."""
from datetime import date

from functions.execution.account_state import (
    CashState,
    RightsIssueState,
    apply_stock_dividend,
    buy_stock,
    expire_rights_issue,
    freeze_rights_issue_cash,
    receive_cash_dividend,
    record_sale_proceeds,
    release_frozen_cash,
    sell_stock,
    settle_cash_dividend,
    settle_sale_proceeds,
    subscribe_rights_issue,
    unlock_t_plus_one,
)


def verify_account_state_golden():
    cash = CashState(settled_cash=1000.0, withdrawable_cash=1000.0)
    dividend_pending = receive_cash_dividend(cash, 80.0)
    assert dividend_pending.available_cash == 1000.0
    dividend_paid = settle_cash_dividend(dividend_pending, 80.0)
    assert dividend_paid.available_cash == 1080.0

    sale_day = record_sale_proceeds(cash, 200.0)
    assert sale_day.available_cash == 1200.0
    assert sale_day.withdrawable_cash == 1000.0
    sale_settled = settle_sale_proceeds(sale_day)
    assert sale_settled.withdrawable_cash == 1200.0

    rights_frozen = freeze_rights_issue_cash(cash, 300.0)
    assert rights_frozen.available_cash == 700.0
    assert release_frozen_cash(rights_frozen, 300.0).available_cash == 1000.0
    try:
        freeze_rights_issue_cash(cash, 1200.0)
    except ValueError:
        pass
    else:
        raise AssertionError("Rights issue must reject insufficient cash")

    rights = RightsIssueState("sh600000", entitlement_shares=200, payment_deadline=date(2024, 1, 5))
    rights_cash, partial = subscribe_rights_issue(
        CashState(settled_cash=600.0),
        rights,
        shares=200,
        price=5.0,
        order_date=date(2024, 1, 4),
    )
    assert partial.subscribed_shares == 120
    assert partial.abandoned_shares == 80
    assert rights_cash.frozen_cash == 600.0
    unchanged_cash, failed = subscribe_rights_issue(
        cash,
        rights,
        shares=200,
        price=5.0,
        order_date=date(2024, 1, 5),
        order_accepted=False,
    )
    assert unchanged_cash == cash
    assert failed.status == "order_failed"
    expired = expire_rights_issue(rights, date(2024, 1, 6))
    assert expired.status == "expired"
    assert expired.abandoned_shares == 200

    bought = buy_stock(None, "sh600000", 100, 10.0, date(2024, 1, 2))
    try:
        sell_stock(bought, 100)
    except ValueError:
        pass
    else:
        raise AssertionError("T-day stock sale must be blocked")
    unlocked = unlock_t_plus_one(bought)
    with_dividend = apply_stock_dividend(unlocked, 0.05)
    assert with_dividend.position_shares == 105
    assert with_dividend.odd_lot_shares == 5
    assert sell_stock(with_dividend, 105).position_shares == 0

    print("Account-state golden verification passed.")
    print("Covered: pending dividend, sale proceeds, rights freeze, partial/failed/expired rights issue, T+1 lock, stock-dividend odd lots.")


if __name__ == "__main__":
    verify_account_state_golden()
