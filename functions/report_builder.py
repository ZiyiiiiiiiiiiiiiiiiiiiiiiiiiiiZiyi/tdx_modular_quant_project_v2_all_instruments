# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import FORMAL_MODE_NAME, REPORT_OUTPUT_MD, RESEARCH_RUN_MODE


def build_strategy_report(summary_df, regime_breakdown_df=None):
    lines = ["# Strategy Diagnostic Report", "", f"Research mode: `{RESEARCH_RUN_MODE}`.", ""]
    if summary_df.empty:
        lines.append("No summary rows available.")
    elif RESEARCH_RUN_MODE != FORMAL_MODE_NAME:
        lines.append("## Exploratory Metrics")
        lines.append("P0 is not complete; this table is diagnostic only and is not a strategy ranking.")
        lines.append(summary_df.head(10).to_markdown(index=False))
    else:
        top = summary_df.head(10)
        lines.append("## Candidate Strategies")
        lines.append(top.to_markdown(index=False))
    if regime_breakdown_df is not None and not regime_breakdown_df.empty:
        lines.extend(["", "## Market Regime Breakdown", regime_breakdown_df.to_markdown(index=False)])
    return "\n".join(lines) + "\n"


def save_strategy_report(report_text, output_path=REPORT_OUTPUT_MD):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report_text, encoding="utf-8")
    return output_file
