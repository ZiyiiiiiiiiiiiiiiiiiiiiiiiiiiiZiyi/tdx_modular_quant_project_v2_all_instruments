# -*- coding: utf-8 -*-
"""Rebuild the full feature parquet after provider artifacts change."""
from config import FEATURE_DAILY_PARQUET
from functions.feature_engineering import generate_daily_features_multi


def main():
    features = generate_daily_features_multi()
    print("Rebuilt feature rows:", len(features))
    print("Published feature parquet:", FEATURE_DAILY_PARQUET)


if __name__ == "__main__":
    main()
