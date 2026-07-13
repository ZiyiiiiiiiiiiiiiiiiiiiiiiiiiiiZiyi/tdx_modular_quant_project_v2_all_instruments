from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from functions.decision_council.live_monitor_dashboard import HTML
from functions.decision_council.live_monitor_web import HTML as SERVED_HTML

ROOT = Path(__file__).resolve().parent


def main() -> None:
    assert SERVED_HTML == HTML
    required_ids = {
        "perfChart", "excessChart", "drawdownChart", "factorChart", "moduleChart",
        "holdingPathChart", "benchmarkText", "exposureText", "entryGateText",
        "tradeQualityText", "riskModelText", "safetyText", "holdingsBody",
        "candidatesText", "ordersText", "pendingText", "orderReasonText",
        "moduleWeightsBody", "factorWeightsBody", "lifecycleBody",
    }
    for element_id in required_ids:
        assert f'id="{element_id}"' in HTML, element_id
    for token in (
        'command==="stage"',
        'window.devicePixelRatio',
        'data-tab="overview"',
        'data-tab="risk"',
        'data-tab="execution"',
        'data-tab="factors"',
        'addEventListener("mousemove"',
        'setTimeout(poll,1000)',
    ):
        assert token in HTML, token
    assert "radial-gradient" not in HTML
    assert "border-radius: 14px" not in HTML
    direct_import = subprocess.run(
        [sys.executable, "functions/decision_council/live_monitor_web.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert direct_import.returncode == 1, direct_import.stderr
    assert "ModuleNotFoundError" not in direct_import.stderr
    print("[PASS] professional live monitor preserves data surfaces and responsive chart contracts")


if __name__ == "__main__":
    main()
