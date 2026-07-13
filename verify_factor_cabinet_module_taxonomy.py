"""Verify cabinet economic taxonomy and reduced experiment contracts."""
from __future__ import annotations

from functions.decision_council.factor_cabinet_module_taxonomy import (
    build_cabinet_experiment_contracts,
    build_cabinet_module_mapping,
)
from functions.decision_council.factor_source import resolve_factor_source


def main() -> int:
    spec = resolve_factor_source(
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id="pruned_run20260706_183553_702097_20260710_202906",
    )
    mapping = build_cabinet_module_mapping(spec)
    contracts = build_cabinet_experiment_contracts(mapping)
    assert len(mapping) == 74
    assert len(contracts) == 4
    assert not contracts["duplicate_view_hash"].any()
    assert contracts.loc[contracts["view_name"].eq("cabinet_full"), "contract_valid"].iloc[0]
    print("[PASS] 74 factors are mapped and four non-duplicate experiment contracts are audited")
    print(mapping["primary_economic_module"].value_counts().to_string())
    print(contracts[["view_name", "factor_count", "contract_valid", "contract_reasons"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
