# -*- coding: utf-8 -*-
"""Read, validate, and export the centralized project configuration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import (
    assert_valid_configuration,
    get_parameter,
    parameter_snapshot,
    validate_configuration,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--get", dest="parameter_name", default=None)
    parser.add_argument("--export", dest="export_path", default=None)
    parser.add_argument("--without-paths", action="store_true")
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.validate:
        errors = validate_configuration()
        if errors:
            raise SystemExit("Invalid configuration:\n- " + "\n- ".join(errors))
        print("Centralized configuration is valid.")
    if args.parameter_name:
        value = get_parameter(args.parameter_name)
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    snapshot = parameter_snapshot(include_paths=not args.without_paths)
    if args.export_path:
        output = Path(args.export_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print("Saved configuration snapshot:", output)
    if not args.validate and not args.parameter_name and not args.export_path:
        assert_valid_configuration()
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
