import pandas as pd

from functions.decision_council.factor_appeal_judge import _summarize_event_window_appeal
from functions.decision_council.factor_judge_profiles import load_factor_judge_profiles
from functions.factors.pit_factor_registry import pit_factor_registry_rows


def main() -> int:
    dates = pd.date_range("2024-01-02", periods=25, freq="B")
    rows = []
    for index in range(240):
        symbol = f"{index:06d}.SZ"
        treated = index < 120
        for day, date in enumerate(dates):
            rows.append({
                "symbol": symbol,
                "date": date,
                "close": 10.0 * (1.0 + (0.01 * min(day, 5) if treated else 0.0)),
                "cand_event_buyback_announcement": 1.0 if treated and day == 0 else 0.0,
            })
    data = pd.DataFrame(rows)
    spec = next(
        row for row in pit_factor_registry_rows(families={"event"})
        if row["factor_name"] == "event_buyback_announcement"
    )
    result = _summarize_event_window_appeal(
        data,
        rows=[spec],
        profile=load_factor_judge_profiles()["event_decay"],
        old_decision_lookup={},
    )
    row = result.iloc[0]
    if int(row["event_count"]) != 120 or row["new_decision"] != "promote_candidate":
        print(f"[FAIL] event-window evidence was not judged correctly: {row.to_dict()}")
        return 1
    print("[PASS] event appeal uses onset count and forward excess-return evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
