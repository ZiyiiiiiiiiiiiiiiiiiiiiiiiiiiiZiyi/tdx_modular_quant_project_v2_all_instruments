from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from functions.decision_council.live_monitor_dashboard import HTML
from functions.decision_council.live_monitor_web import HTML as SERVED_HTML

ROOT = Path(__file__).resolve().parent


def _legacy_html() -> str:
    source = (ROOT / "functions/decision_council/live_monitor_web.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if any(isinstance(target, ast.Name) and target.id == "HTML" for target in node.targets):
            if isinstance(node.value.value, str):
                return node.value.value
    raise AssertionError("legacy monitor HTML template not found")


def _object_fields(html: str, object_name: str) -> set[str]:
    return set(re.findall(rf"\b{re.escape(object_name)}\.([A-Za-z_][A-Za-z0-9_]*)", html))


def _metric_keys(html: str, start: str, end: str) -> set[str]:
    section = html.split(start, 1)[1].split(end, 1)[0]
    return set(re.findall(r'''\[\s*["']([a-z][a-z0-9_]*)["']\s*,\s*["']''', section))


def main() -> None:
    assert SERVED_HTML == HTML
    required_ids = {
        "perfChart", "excessChart", "drawdownChart", "factorChart", "moduleChart",
        "holdingPathChart", "benchmarkText", "exposureText", "entryGateText",
        "tradeQualityText", "riskModelText", "safetyText", "holdingsBody",
        "candidatesText", "ordersText", "pendingText", "orderReasonText",
        "moduleWeightsBody", "factorWeightsBody", "lifecycleBody", "holdingPathLegend",
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
        'data-tab="holdings"',
        'id="tab-holdings"',
        '按实际入场价归一化为 1.0000',
        'addEventListener("mousemove"',
        'setTimeout(poll,1000)',
        "hydrateChartHistory(payload.chart_history)",
        "factorHistory[factorHistory.length-1].key===pointKey",
        'document.getElementById("runTitle").textContent=payload.title',
        "(stageCommand||finishCommand)&&payload.exposure",
        "实心圆标记实际买入节点",
        "const entryIndex=Number(path.entry_index)",
        "ctx.arc(x,y0,4,0,Math.PI*2)",
        "买入 ${entryDate}",
        "path.entry_visible===false",
        '["sortino","年化索提诺"]',
        "function annualizedSortino(returns,navMultiple,tradingDays)",
        "annualizedSortino(returns,navMultiple,history.length)",
        "sortino:[fmtNum(sortino,2),sortino]",
    ):
        assert token in HTML, token
    assert "radial-gradient" not in HTML
    assert "border-radius: 14px" not in HTML
    runner_source = (ROOT / "functions/decision_council/runner.py").read_text(encoding="utf-8")
    assert "entry_date_ts >= first_visible_date" in runner_source
    assert '"entry_visible": entry_index is not None' in runner_source
    legacy_html = _legacy_html()
    for object_name in ("ms", "exposure", "payload"):
        missing = _object_fields(legacy_html, object_name) - _object_fields(HTML, object_name)
        assert not missing, f"new monitor dropped {object_name} fields: {sorted(missing)}"
    legacy_metrics = _metric_keys(legacy_html, "const metricDefs", "const metricsRoot")
    new_metrics = _metric_keys(HTML, "const KPI_DEFS", "const metricValues")
    assert not legacy_metrics - new_metrics, f"new monitor dropped metrics: {sorted(legacy_metrics - new_metrics)}"
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
