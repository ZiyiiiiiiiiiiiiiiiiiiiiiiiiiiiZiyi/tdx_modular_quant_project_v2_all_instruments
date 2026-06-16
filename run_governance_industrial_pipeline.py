# -*- coding: utf-8 -*-
"""Build P2-P7 governance artifacts serially with bounded memory."""
from __future__ import annotations

import argparse

from config import GOVERNANCE_STREAM_BATCH_SIZE, assert_valid_configuration
from functions.decision_council.industrial_pipeline import run_industrial_governance_build


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=GOVERNANCE_STREAM_BATCH_SIZE)
    return parser.parse_args()


def main():
    assert_valid_configuration()
    args = parse_args()
    print("========== Serial Governance Industrial Build P2-P7 ==========")
    print("Arrow batch size:", args.batch_size)
    saved = run_industrial_governance_build(batch_size=args.batch_size)
    for name, path in sorted(saved.items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
