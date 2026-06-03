# -*- coding: utf-8 -*-
"""Run the equal-weight baseline and phase-one ablations in isolated folders."""
from __future__ import annotations

import argparse

from config import GOVERNANCE_OUTPUT_DIR
from functions.decision_council.runner import run_governance_backtest


VARIANTS = {
    "equal_weight_alpha_ensemble": {"enable_sector_cap": True, "enable_safety_agent": True, "enable_reputation": False},
    "rules_based_president_without_sector_cap": {"enable_sector_cap": False, "enable_safety_agent": True},
    "rules_based_president_without_safety_agent": {"enable_sector_cap": True, "enable_safety_agent": False},
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--safety-proxy-mode", choices=["strict", "degraded_backtest"], default="strict")
    return parser.parse_args()


def main():
    args = parse_args()
    for variant, options in VARIANTS.items():
        print(f"========== Governance ablation: {variant} ==========")
        run_governance_backtest(
            start_date=args.start_date,
            end_date=args.end_date,
            max_days=args.max_days,
            safety_proxy_mode=args.safety_proxy_mode,
            output_dir=GOVERNANCE_OUTPUT_DIR / variant,
            **options,
        )
    print("Governance ablations completed.")


if __name__ == "__main__":
    main()
