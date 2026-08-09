"""Focused mathematical and contract checks for SCAP portfolio sizing v2."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.portfolio_constraint_contract import PolicyBand
from functions.decision_council.position_sizing_contract import (
    attach_entry_sizing_envelopes,
    resolve_portfolio_sizing_intent,
)


def _policy() -> PolicyBand:
    return PolicyBand(
        state="normal",
        holding_floor=4,
        holding_target=6,
        holding_ceiling=32,
        exposure_lower=0.60,
        exposure_target=0.85,
        exposure_upper=0.90,
        disaster_ceiling=1.0,
    )


def _check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    intents = [
        resolve_portfolio_sizing_intent(
            decision_id=f"capital_{capital}",
            nav_amount=capital,
            current_exposure=0.0,
            current_holding_count=0,
            policy_band=_policy(),
            hard_holding_ceiling=32,
            hard_exposure_ceiling=0.90,
            legacy_sizing_reference_positions=legacy,
        )
        for capital, legacy in ((20_000, 6), (50_000, 16), (100_000, 32), (200_000, 32))
    ]
    _check(
        {intent.executable_target_holding_count for intent in intents} == {6},
        "capital capacity does not rewrite the six-name policy target",
    )
    unit_amounts = [intent.base_new_name_target_amount / intent.nav_amount for intent in intents]
    _check(
        max(unit_amounts) - min(unit_amounts) < 1e-12,
        "per-name target weight is invariant to capital when policy is invariant",
    )
    _check(
        all(abs(value - 0.85 / 6.0) < 1e-12 for value in unit_amounts),
        "empty-portfolio sizing uses policy target exposure divided by policy target names",
    )

    partly_invested = resolve_portfolio_sizing_intent(
        decision_id="partly_invested",
        nav_amount=100_000,
        current_exposure=0.30,
        current_holding_count=2,
        policy_band=_policy(),
        hard_holding_ceiling=32,
        hard_exposure_ceiling=0.90,
    )
    _check(partly_invested.target_new_name_count == 4, "existing names reduce only the new-name target")
    _check(
        abs(partly_invested.base_new_name_target_amount - 13_750.0) < 1e-8,
        "incremental target amount is allocated across missing policy names",
    )

    candidates = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "close_nominal": [10.0, 10.0, 10.0, 10.0],
            "scap_v31_authority_tier": ["A", "B", "C", "D"],
        }
    )
    sized = attach_entry_sizing_envelopes(
        candidates,
        intent=intents[2],
        spendable_cash_amount=90_000.0,
        per_name_hard_cap=0.25,
        add_authorized=False,
    )
    _check(sized["scap_v31_max_lots"].tolist() == [14, 8, 4, 0], "A/B/C/D integer authority fractions are applied after policy sizing")
    _check(
        sized["scap_v32_authority_role"].eq("final_authorized_size_add_unavailable").all(),
        "starter size is not mislabelled when no add path is authorized",
    )
    _check(
        sized["scap_sizing_contract_id"].nunique() == 1,
        "all candidate envelopes carry the unique daily sizing contract id",
    )

    expensive = attach_entry_sizing_envelopes(
        pd.DataFrame(
            {
                "symbol": ["EXPENSIVE"],
                "close_nominal": [300.0],
                "scap_v31_authority_tier": ["A"],
            }
        ),
        intent=intents[0],
        spendable_cash_amount=18_000.0,
        per_name_hard_cap=0.40,
        add_authorized=False,
    )
    _check(expensive.loc[0, "scap_v31_max_lots"] == 0, "unaffordable board lot fails closed")


if __name__ == "__main__":
    main()
