# -*- coding: utf-8 -*-
"""Generate offline formal-readiness artifacts without claiming formal release."""
from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    ADJUSTMENT_PTI_QUALITY_CSV,
    CORPORATE_ACTION_LEDGER_CSV,
    CORPORATE_ACTIONS_PARQUET,
    FEATURE_DAILY_PARQUET,
)
from functions.benchmark import save_investable_benchmark_report
from functions.execution.corporate_action_ledger import build_corporate_action_ledger
from functions.formal_admission import save_formal_admission_report
from functions.lineage import save_lineage_reports
from functions.pricing.adjustment_pti_audit import build_adjustment_pti_quality_report
from functions.reproducibility import save_reproducibility_manifest


def main():
    columns = pq.read_schema(FEATURE_DAILY_PARQUET).names
    wanted = [column for column in ["date", "feature_timestamp"] if column in columns]
    feature_df = pd.read_parquet(FEATURE_DAILY_PARQUET, columns=wanted)
    lineage, timestamp_audit = save_lineage_reports(feature_df, feature_columns=columns)
    actions = pd.read_parquet(CORPORATE_ACTIONS_PARQUET) if CORPORATE_ACTIONS_PARQUET.exists() else pd.DataFrame()
    factors = pd.read_parquet(ADJUSTMENT_FACTORS_PARQUET) if ADJUSTMENT_FACTORS_PARQUET.exists() else pd.DataFrame()
    action_ledger = build_corporate_action_ledger(actions)
    action_ledger.to_csv(CORPORATE_ACTION_LEDGER_CSV, index=False, encoding="utf-8-sig")
    build_adjustment_pti_quality_report(factors, action_ledger).to_csv(
        ADJUSTMENT_PTI_QUALITY_CSV, index=False, encoding="utf-8-sig"
    )
    benchmark = save_investable_benchmark_report()
    manifest = save_reproducibility_manifest()
    admission = save_formal_admission_report()
    for path in [
        lineage,
        timestamp_audit,
        CORPORATE_ACTION_LEDGER_CSV,
        ADJUSTMENT_PTI_QUALITY_CSV,
        benchmark,
        manifest,
        admission,
    ]:
        print("Saved:", path)


if __name__ == "__main__":
    main()
