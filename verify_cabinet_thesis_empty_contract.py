from __future__ import annotations

from io import StringIO
import pandas as pd

from functions.decision_council.cabinet_thesis_audit import build_cabinet_thesis_counterfactual


result = build_cabinet_thesis_counterfactual(pd.DataFrame(), pd.DataFrame())
required = {
    "date", "symbol", "paper_exit_reason", "paper_exit_signal_price",
    "counterfactual_return_5d", "counterfactual_return_10d", "counterfactual_return_20d",
    "counterfactual_interpretation",
}
assert required <= set(result.columns), sorted(required - set(result.columns))
buffer = StringIO()
result.to_csv(buffer, index=False)
reloaded = pd.read_csv(StringIO(buffer.getvalue()))
assert required <= set(reloaded.columns)
print("[PASS] empty cabinet-thesis counterfactual keeps a readable schema")
