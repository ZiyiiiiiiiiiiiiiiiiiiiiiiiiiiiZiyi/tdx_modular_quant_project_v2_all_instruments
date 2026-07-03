# -*- coding: utf-8 -*-
"""Run the narrowed governance mainline review with live monitoring."""
from __future__ import annotations

import argparse
from pathlib import Path

from config import GOVERNANCE_END_DATE, GOVERNANCE_START_DATE
from build_governance_mainline_report import build_report
from run_governance_experiments import run_single_experiment


REVIEW_UNIVERSES = ("hs300_csi500_a500_strict", "hs300_strict")
VARIANT_NAME = "rules_based_president"
ALPHA_BUNDLE = "diversified_pre_screen_bundle_v2"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=GOVERNANCE_START_DATE)
    parser.add_argument("--end-date", default=GOVERNANCE_END_DATE)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--alpha-bundle", default=ALPHA_BUNDLE)
    parser.add_argument("--no-live-monitor", action="store_true", help="Disable the per-universe live popup monitor.")
    return parser.parse_args()


def _show_completion_popup(report_path: Path, comparison_path: Path) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Governance Mainline Review Complete",
            f"Report:\n{report_path}\n\nComparison:\n{comparison_path}",
        )
        root.destroy()
    except Exception:
        pass


def main() -> None:
    args = parse_args()
    for universe_name in REVIEW_UNIVERSES:
        print("=" * 72)
        print(f"Running mainline review universe: {universe_name}")
        print("=" * 72)
        run_single_experiment(
            variant_name=VARIANT_NAME,
            alpha_bundle=args.alpha_bundle,
            universe_name=universe_name,
            start_date=args.start_date,
            end_date=args.end_date,
            max_days=args.max_days,
            show_live_monitor=not args.no_live_monitor,
        )
    report_path, comparison_path = build_report(alpha_bundle=args.alpha_bundle)
    print(f"Saved review report: {report_path}")
    print(f"Saved comparison csv: {comparison_path}")
    _show_completion_popup(report_path, comparison_path)


if __name__ == "__main__":
    main()
