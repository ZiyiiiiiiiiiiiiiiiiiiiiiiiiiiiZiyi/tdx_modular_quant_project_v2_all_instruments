"""Single authoritative feasible-candidate pool for SCAP.

The contract deliberately separates financial feasibility from computational
compression.  A search shortlist may never manufacture or erase a portfolio
holding requirement.
"""

from __future__ import annotations

import math

import pandas as pd


CANDIDATE_POOL_CONTRACT_VERSION = "scap_feasible_candidate_pool_v1"


def select_feasible_candidate_pool(
    candidates: pd.DataFrame,
    *,
    limit: int,
    per_pool_reserve: int = 2,
) -> tuple[list[object], pd.Series, pd.Series]:
    """Return pool-first candidate indices and factual eligibility masks.

    Required hard-feasibility fields are produced by ``mainline_v3``.  Missing
    production fields fail closed; synthetic fixtures can still supply the
    same explicit booleans.  Pool reservation precedes global ranking so a
    later truncation cannot silently erase diversification.
    """
    if candidates is None or candidates.empty:
        empty = pd.Series(dtype=bool)
        return [], empty, empty
    cap = max(int(limit), 1)
    reserve = max(int(per_pool_reserve), 1)
    data = candidates
    index = data.index

    def flag(name: str, default: bool = False) -> pd.Series:
        if name not in data.columns:
            return pd.Series(default, index=index, dtype=bool)
        return data[name].fillna(default).astype(bool)

    utility = pd.to_numeric(
        data.get("scap_candidate_utility", pd.Series(float("nan"), index=index)),
        errors="coerce",
    )
    cash = pd.to_numeric(
        data.get("mainline_v3_one_lot_cash_required", pd.Series(0.0, index=index)),
        errors="coerce",
    )
    max_lots = pd.to_numeric(
        data.get("scap_v31_max_lots", pd.Series(0.0, index=index)),
        errors="coerce",
    ).fillna(0.0)
    expected_return = pd.to_numeric(
        data.get(
            "scap_v31_decision_expected_return",
            pd.Series(float("nan"), index=index),
        ),
        errors="coerce",
    ).combine_first(
        pd.to_numeric(
            data.get(
                "scap_decision_expected_return",
                pd.Series(float("nan"), index=index),
            ),
            errors="coerce",
        )
    )
    tier = data.get(
        "scap_v31_authority_tier", pd.Series("D", index=index)
    ).fillna("D").astype(str)
    held = flag("lifecycle_held_row")
    permission = flag("mainline_v3_market_permission_feasible")
    lot_feasible = flag("mainline_v3_lot_feasible")
    structural = flag("mainline_v3_structural_feasible")
    cash_feasible = flag("mainline_v3_cash_feasible")
    hard_state = data.get(
        "position_state", pd.Series("", index=index)
    ).fillna("").astype(str).str.lower().isin(
        {"cooldown", "exiting", "protecting_profit"}
    ) | flag("exit_state")

    factual_feasible = (
        permission
        & lot_feasible
        & structural
        & cash_feasible
        & cash.gt(0.0)
        & max_lots.gt(0.0)
        & tier.isin({"A", "B", "C"})
        & ~held
        & ~hard_state
    )
    # A negative one-lot value caused only by the fixed minimum commission may
    # become positive at a larger integer lot count.  Keep that narrow review
    # path in the computational pool; the proposal factory recomputes exact
    # lifecycle cost and the optimizer still rejects non-positive proposals.
    multi_lot_economic_review = (
        expected_return.gt(0.0)
        & expected_return.notna()
        & max_lots.gt(1.0)
    )
    positive_feasible = factual_feasible & (
        (utility.gt(0.0) & utility.notna()) | multi_lot_economic_review
    )
    pool = data.loc[positive_feasible].copy()
    if pool.empty:
        return [], factual_feasible, positive_feasible

    pool["_utility_amount"] = utility.loc[pool.index]
    pool["_capital_efficiency"] = (
        pool["_utility_amount"]
        / cash.loc[pool.index].where(cash.loc[pool.index].gt(0.0))
    ).replace([float("inf"), float("-inf")], pd.NA).fillna(float("-inf"))
    pool["_primary_score"] = pd.to_numeric(
        pool.get("primary_score", pd.Series(0.0, index=pool.index)),
        errors="coerce",
    ).fillna(0.0)
    pool["_thesis"] = pool.get(
        "cabinet_entry_thesis", pd.Series("unclassified", index=pool.index)
    ).fillna("unclassified").astype(str).replace("", "unclassified")
    pool["_symbol"] = pool.get(
        "symbol", pd.Series(pool.index.astype(str), index=pool.index)
    ).astype(str)

    chosen: list[object] = []
    # Reserve each observable pool first.  Pools with the strongest available
    # capital-efficient member receive deterministic priority if the cap binds.
    groups = []
    for thesis, group in pool.groupby("_thesis", sort=True):
        ordered = group.sort_values(
            ["_capital_efficiency", "_utility_amount", "_primary_score", "_symbol"],
            ascending=[False, False, False, True],
        )
        groups.append((float(ordered.iloc[0]["_capital_efficiency"]), str(thesis), ordered))
    for _, _, ordered in sorted(groups, key=lambda item: (-item[0], item[1])):
        chosen.extend(ordered.head(reserve).index.tolist())
        if len(dict.fromkeys(chosen)) >= cap:
            break

    # Fill remaining computational capacity by unit-capital value first.  The
    # absolute CNY amount is only a later tie-break and cannot favour an
    # infeasible large lot because infeasible rows were removed above.
    global_order = pool.sort_values(
        ["_capital_efficiency", "_utility_amount", "_primary_score", "_symbol"],
        ascending=[False, False, False, True],
    )
    chosen.extend(global_order.index.tolist())
    selected = list(dict.fromkeys(chosen))[:cap]
    if len(selected) > cap or not math.isfinite(float(len(selected))):
        raise AssertionError("candidate pool compression invariant failed")
    return selected, factual_feasible, positive_feasible
