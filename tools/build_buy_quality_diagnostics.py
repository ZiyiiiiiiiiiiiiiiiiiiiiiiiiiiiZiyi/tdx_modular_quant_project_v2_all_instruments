from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.decision_council.buy_quality_diagnostics import build_buy_quality_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Build post-run buy quality lineage")
    parser.add_argument("run_dir")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    print(json.dumps(build_buy_quality_diagnostics(args.run_dir, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
