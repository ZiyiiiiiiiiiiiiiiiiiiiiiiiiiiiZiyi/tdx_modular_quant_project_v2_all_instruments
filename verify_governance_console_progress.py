"""Verify that governance console progress reuses one terminal line."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO


def _assert_single_line(tracker_type) -> None:
    stream = StringIO()
    tracker = tracker_type(2, "Test Progress")
    with redirect_stdout(stream):
        tracker.update("first status is deliberately long")
        tracker.update("done")
    output = stream.getvalue()
    assert output.count("\r") == 2, repr(output)
    assert output.count("\n") == 1, repr(output)
    assert "first status is deliberately long" in output
    assert "done" in output


def main() -> int:
    from functions.decision_council.runner import ProgressTracker as RunnerProgressTracker
    from run_governance_experiments import ProgressTracker as ExperimentProgressTracker

    _assert_single_line(RunnerProgressTracker)
    _assert_single_line(ExperimentProgressTracker)
    print("[PASS] governance console progress refreshes one line until completion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
