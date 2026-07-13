"""Focused checks for governance output reliability and bounded audit history."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


def check_csv_write_retries_after_transient_missing_directory() -> None:
    from functions.decision_council.outputs import write_governance_csv

    frame = pd.DataFrame({"date": ["2021-01-04"], "value": [1.0]})
    original = pd.DataFrame.to_csv
    calls = {"count": 0}

    def flaky_to_csv(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FileNotFoundError("simulated transient output-directory race")
        return original(self, *args, **kwargs)

    with TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "nested" / "ledger.csv"
        try:
            pd.DataFrame.to_csv = flaky_to_csv
            saved = write_governance_csv(frame, target)
        finally:
            pd.DataFrame.to_csv = original
        assert saved == target
        assert target.exists(), target
        assert calls["count"] == 2, calls
        assert pd.read_csv(target)["value"].tolist() == [1.0]
    print("[PASS] governance CSV output retries transient directory failures")


def check_text_write_retries_after_transient_missing_directory() -> None:
    from functions.decision_council.outputs import write_governance_text

    original = Path.write_text
    calls = {"count": 0}

    def flaky_write_text(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FileNotFoundError("simulated transient output-directory race")
        return original(self, *args, **kwargs)

    with TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "nested" / "report.md"
        try:
            Path.write_text = flaky_write_text
            saved = write_governance_text("# report", target)
        finally:
            Path.write_text = original
        assert saved == target
        assert target.read_text(encoding="utf-8") == "# report"
        assert calls["count"] == 2, calls
    print("[PASS] governance text output retries transient directory failures")


def check_plot_write_retries_after_transient_missing_directory() -> None:
    from functions.decision_council.plots import _safe_savefig

    class FlakyFigure:
        def __init__(self):
            self.calls = 0

        def savefig(self, path, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise FileNotFoundError("simulated transient plot-directory race")
            Path(path).write_bytes(b"plot")

    with TemporaryDirectory() as temp_dir:
        target = Path(temp_dir) / "nested" / "plot.png"
        figure = FlakyFigure()
        saved = _safe_savefig(figure, target)
        assert saved == target
        assert target.read_bytes() == b"plot"
        assert figure.calls == 2
    print("[PASS] governance plot output retries transient directory failures")


def check_pending_order_append_is_frame_safe() -> None:
    from functions.decision_council.pending_orders import PendingOrderBook

    book = PendingOrderBook()
    payload = {
        "decision_id": "test",
        "symbol": "sh600000",
        "side": "buy",
        "reason": "test",
        "priority": 1,
        "created_date": "2021-01-04",
        "target_shares": 100,
    }
    book.add_order(payload)
    book.add_order({**payload, "symbol": "sz000001"})
    assert len(book.orders) == 2
    assert set(book.orders["symbol"].astype(str)) == {"sh600000", "sz000001"}
    print("[PASS] pending order book appends without scalar-row assignment")


def check_bounded_audit_limits() -> None:
    import config

    assert 0 < config.GOVERNANCE_AUDIT_CANDIDATE_LIMIT <= config.GOVERNANCE_ALPHA_CANDIDATE_LIMIT
    assert 0 < config.GOVERNANCE_AUDIT_ENTRY_FORMULA_LIMIT <= 80
    assert config.GOVERNANCE_AUDIT_PRICE_HISTORY_CACHE_SYMBOL_LIMIT >= 1
    print("[PASS] governance audit history is explicitly bounded")


def check_price_history_is_lazy_and_bounded() -> None:
    from functions.decision_council.runner import GovernanceBacktestRunner

    runner = GovernanceBacktestRunner.__new__(GovernanceBacktestRunner)
    rows = []
    for index in range(300):
        symbol = f"sz{index:06d}"
        rows.extend(
            [
                {"symbol": symbol, "date": "2021-01-04", "close": 10.0},
                {"symbol": symbol, "date": "2021-01-05", "close": 10.5},
            ]
        )
    runner.features = pd.DataFrame(rows)
    runner._feature_indices_by_symbol = None
    runner._close_history_cache = __import__("collections").OrderedDict()

    first = runner._close_history("sz000000")
    assert first["close"].tolist() == [10.0, 10.5]
    for index in range(300):
        runner._close_history(f"sz{index:06d}")
    import config

    assert len(runner._close_history_cache) <= config.GOVERNANCE_AUDIT_PRICE_HISTORY_CACHE_SYMBOL_LIMIT
    assert len(runner._feature_indices_by_symbol) == 300
    print("[PASS] entry-price history is lazy and has a bounded symbol cache")


def main() -> int:
    check_csv_write_retries_after_transient_missing_directory()
    check_text_write_retries_after_transient_missing_directory()
    check_plot_write_retries_after_transient_missing_directory()
    check_pending_order_append_is_frame_safe()
    check_bounded_audit_limits()
    check_price_history_is_lazy_and_bounded()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
