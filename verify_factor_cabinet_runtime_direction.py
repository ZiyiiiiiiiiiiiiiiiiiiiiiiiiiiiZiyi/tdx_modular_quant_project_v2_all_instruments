from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pandas as pd

from functions.decision_council.factor_source import resolve_factor_source
from functions.decision_council.proposals import build_rule_alpha_proposals


def main() -> int:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "factor_cabinet.json"
        path.write_text(json.dumps({
            "run_id": "direction_smoke",
            "factors": [{
                "factor_name": "negative_event", "raw_column": "cand_negative_event",
                "role": "risk_override", "module": "event", "family": "event",
                "direction": "lower_better",
            }],
        }), encoding="utf-8")
        spec = resolve_factor_source(
            factor_source="selected_factor_cabinet",
            factor_cabinet_run_id="direction_smoke",
            factor_cabinet_path=str(path),
        )
        context = spec.runtime_context()
        data = pd.DataFrame({
            "symbol": ["bad", "good"], "cand_negative_event": [2.0, 0.0],
            "volatility_20": [0.1, 0.1],
        })
        proposals = build_rule_alpha_proposals(
            data,
            model_names=("negative_event",),
            factor_judged=True,
            runtime_context=context,
        ).set_index("symbol")
        if proposals.loc["bad", "predicted_return_5d"] >= proposals.loc["good", "predicted_return_5d"]:
            print("[FAIL] lower_better cabinet direction was not applied at runtime")
            return 1
    print("[PASS] cabinet direction contract reaches runtime proposal scores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
