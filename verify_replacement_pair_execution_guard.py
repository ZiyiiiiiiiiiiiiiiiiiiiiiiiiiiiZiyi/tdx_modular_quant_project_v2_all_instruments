import pandas as pd

from functions.decision_council.execution_runtime import (
    filled_replacement_sell_pair_ids,
    replacement_pair_leg_authorized,
    replacement_pair_still_valid,
)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    expect(replacement_pair_leg_authorized("pair_1", "sell", set()),
           "the sell leg may attempt execution independently")
    expect(not replacement_pair_leg_authorized("pair_1", "buy", set()),
           "the buy leg is blocked when the paired sell did not fill")
    expect(replacement_pair_leg_authorized("pair_1", "buy", {"pair_1"}),
           "the buy leg becomes executable after its exact paired sell fills")
    expect(replacement_pair_leg_authorized("", "buy", set()),
           "ordinary unpaired buys retain their original execution behavior")
    durable = filled_replacement_sell_pair_ids(pd.DataFrame([{
        "replacement_pair_id": "pair_prior_day",
        "replacement_pair_leg": "sell",
        "status": "filled",
    }]))
    expect(replacement_pair_leg_authorized("pair_prior_day", "buy", durable),
           "a prior-day filled sell authorizes its durable paired buy")
    market = pd.DataFrame([
        {"symbol": "held", "comparable_expected_alpha": 0.01, "comparable_alpha_lcb": 0.005},
        {"symbol": "challenger", "comparable_expected_alpha": 0.012, "comparable_alpha_lcb": 0.009},
    ]).set_index("symbol", drop=False)
    carried = {
        "symbol": "challenger", "replacement_paired_symbol": "held",
        "replacement_cost_rate": 0.001,
    }
    expect(not replacement_pair_still_valid(carried, market),
           "a carried buy expires when its refreshed conservative net edge is non-positive")
    market.at["challenger", "comparable_alpha_lcb"] = 0.02
    expect(replacement_pair_still_valid(carried, market),
           "a carried buy remains eligible when refreshed edge still covers cost")
    print("[PASS] replacement pair execution guard verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
