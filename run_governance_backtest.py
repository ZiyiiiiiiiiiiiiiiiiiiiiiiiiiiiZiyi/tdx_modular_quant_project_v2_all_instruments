# -*- coding: utf-8 -*-
"""Run the phase-one daily decision-council backtest."""
from __future__ import annotations

import argparse

from config import GOVERNANCE_OUTPUT_DIR
from functions.decision_council.runner import run_governance_backtest


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default="strict")
    parser.add_argument(
        "--variant",
        choices=["rules_based_president", "equal_weight_alpha_ensemble", "rules_based_president_without_sector_cap", "rules_based_president_without_safety_agent"],
        default="rules_based_president",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    enable_sector_cap = args.variant != "rules_based_president_without_sector_cap"
    enable_safety_agent = args.variant != "rules_based_president_without_safety_agent"
    enable_reputation = args.variant != "equal_weight_alpha_ensemble"
    output_dir = GOVERNANCE_OUTPUT_DIR if args.variant == "rules_based_president" else GOVERNANCE_OUTPUT_DIR / args.variant
    saved = run_governance_backtest(
        start_date=args.start_date,
        end_date=args.end_date,
        max_days=args.max_days,
        safety_proxy_mode=args.safety_proxy_mode,
        output_dir=output_dir,
        enable_sector_cap=enable_sector_cap,
        enable_safety_agent=enable_safety_agent,
        enable_reputation=enable_reputation,
    )
    print("Decision-council backtest completed.")
    for name, path in sorted(saved.items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
