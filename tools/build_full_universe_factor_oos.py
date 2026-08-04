from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from functions.decision_council.full_universe_factor_oos import build_full_universe_factor_oos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--cache-manifest", required=True)
    parser.add_argument("--feature-path", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(build_full_universe_factor_oos(
        run_dir=args.run_dir, cache_manifest_path=args.cache_manifest,
        feature_path=args.feature_path, output_dir=args.output_dir,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
