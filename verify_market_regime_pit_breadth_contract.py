from __future__ import annotations

import pandas as pd

from config import MARKET_REGIME_BENCHMARK_SYMBOL
from functions.decision_council.market_regime_policy import (
    MarketRegimeDetector,
    MarketRegimePolicy,
)
from functions.decision_council.runner import GovernanceBacktestRunner


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _features(*, low_breadth: bool, missing_proxy_date=None) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-02", periods=100)
    missing = pd.Timestamp(missing_proxy_date) if missing_proxy_date is not None else None
    for index, date in enumerate(dates):
        close = 100.0 + 0.35 * index
        if missing is None or date != missing:
            rows.append(
                {
                    "date": date,
                    "symbol": MARKET_REGIME_BENCHMARK_SYMBOL,
                    "close": close,
                    "close_nominal": close,
                    "instrument_type": "etf_fund",
                    "is_trading": True,
                    "ret_20": 0.05,
                    "close_to_ma20": 0.05,
                }
            )
        for symbol_index in range(20):
            healthy = not low_breadth or symbol_index < 2
            rows.append(
                {
                    "date": date,
                    "symbol": f"sh60{symbol_index:04d}",
                    "close": 10.0 + symbol_index,
                    "close_nominal": 10.0 + symbol_index,
                    "instrument_type": "stock",
                    "is_trading": True,
                    "ret_20": 0.03 if healthy else -0.03,
                    "close_to_ma20": 0.02 if healthy else -0.02,
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    high = _features(low_breadth=False)
    low = _features(low_breadth=True)
    last_date = pd.Timestamp(high["date"].max()).normalize()

    high_detector = MarketRegimeDetector()
    high_series = high_detector.prepare_history(high, MARKET_REGIME_BENCHMARK_SYMBOL)
    high_diag = high_detector.diagnostics(last_date, MARKET_REGIME_BENCHMARK_SYMBOL)
    low_detector = MarketRegimeDetector()
    low_series = low_detector.prepare_history(low, MARKET_REGIME_BENCHMARK_SYMBOL)
    low_diag = low_detector.diagnostics(last_date, MARKET_REGIME_BENCHMARK_SYMBOL)

    expect(bool(high_diag["regime_input_valid"]), "same-day benchmark and breadth produce a valid regime input")
    expect(float(high_diag["regime_breadth_coverage"]) == 1.0, "breadth coverage is measured from tradable stocks")
    expect(float(high_diag["regime_breadth_score"]) > 0.95, "healthy cross-section produces high PIT breadth")
    expect(float(low_diag["regime_breadth_score"]) < 0.20, "weak cross-section produces low PIT breadth")
    expect(str(high_series.loc[last_date]) == "bull", "positive benchmark trend plus healthy breadth confirms bull")
    expect(str(low_series.loc[last_date]) != "bull", "the same benchmark cannot be bull when actual breadth is weak")

    cutoff = pd.Timestamp(high["date"].drop_duplicates().sort_values().iloc[80]).normalize()
    truncated = high[pd.to_datetime(high["date"]).dt.normalize().le(cutoff)].copy()
    truncated_detector = MarketRegimeDetector()
    truncated_series = truncated_detector.prepare_history(truncated, MARKET_REGIME_BENCHMARK_SYMBOL)
    expect(
        str(high_series.loc[cutoff]) == str(truncated_series.loc[cutoff]),
        "future rows do not change an already observed regime label",
    )

    missing_date = pd.Timestamp(high["date"].drop_duplicates().sort_values().iloc[90]).normalize()
    missing = _features(low_breadth=False, missing_proxy_date=missing_date)
    missing_detector = MarketRegimeDetector()
    missing_series = missing_detector.prepare_history(missing, MARKET_REGIME_BENCHMARK_SYMBOL)
    missing_diag = missing_detector.diagnostics(missing_date, MARKET_REGIME_BENCHMARK_SYMBOL)
    expect(str(missing_series.loc[missing_date]) == "unknown", "missing same-day control benchmark is not forward-filled into a valid label")
    expect(not bool(missing_diag["regime_input_valid"]), "missing control benchmark fails the state input contract")
    expect(str(missing_diag["regime_input_status"]) == "benchmark_missing_for_date", "invalid state date discloses the exact reason")
    expect(str(missing_diag["regime_benchmark_role"]) == "safety_control_proxy", "control benchmark role is explicit and separate from performance attribution")

    # Layer validation deliberately withholds trading authority from the regime
    # module.  Its diagnostics must nevertheless be live on the real runner
    # path; otherwise a disabled control is indistinguishable from broken data.
    observation_only = object.__new__(GovernanceBacktestRunner)
    observation_only.enable_market_regime_policy = False
    observation_only.governance_control_mode = "aggressive_lean"
    observation_only.features = high
    observation_only.market_regime_policy = MarketRegimePolicy()
    observation_only.market_regime_policy.detector.prepare_history(
        high, MARKET_REGIME_BENCHMARK_SYMBOL
    )
    observation_only._current_regime = "unknown"
    observation_only._regime_params_cache = {}
    observation_only._regime_diagnostics_cache = {}
    observed_params = observation_only._get_regime_params(last_date)
    observed_diag = observation_only._regime_diagnostics_cache[last_date]
    expect(observed_params is None, "observation-only regime module has no trading authority")
    expect(bool(observed_diag["regime_input_valid"]), "observation-only runner still records valid market-state inputs")
    expect(float(observed_diag["regime_breadth_score"]) > 0.95, "runner diagnostics retain actual market breadth instead of a neutral constant")

    source = open("functions/decision_council/position_lifecycle.py", encoding="utf-8").read()
    expect("regime_binary" not in source, "market state repair does not introduce a binary exit master switch")
    regime_source = open("functions/decision_council/market_regime_policy.py", encoding="utf-8").read()
    expect("breadth = 0.5" not in regime_source, "market classification has no hidden 0.5 breadth fallback")
    print("[PASS] market regime PIT/breadth contract verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
