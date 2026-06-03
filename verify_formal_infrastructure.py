# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.execution.execution_model import execution_model_snapshot
from functions.execution.tax_ledger import build_trade_tax_ledger, tax_ledger_total
from functions.execution.valuation import (
    build_blocked_order_valuation_ledger,
    valuation_discount_by_date,
)
from functions.formal_admission import build_formal_admission_report
from functions.lineage import audit_feature_timestamps, build_default_feature_lineage
from functions.reproducibility import build_reproducibility_manifest


def verify_formal_infrastructure():
    model = execution_model_snapshot()
    assert model["execution_price_rule"] == "nominal_daily_price_only"
    assert "t_plus_1" in model["order_time_rule"]

    orders = pd.DataFrame(
        [
            {
                "trade_date": "2024-01-02",
                "symbol": "sh600000",
                "side": "sell",
                "execution_status": "filled",
                "trade_notional": 1000.0,
                "stamp_duty_cost": 1.0,
                "remaining_shares": 0,
                "price": 10.0,
                "price_limit_blocked": False,
                "suspension_blocked": False,
            },
            {
                "trade_date": "2024-01-03",
                "symbol": "sh600000",
                "side": "sell",
                "execution_status": "pending",
                "trade_notional": 0.0,
                "stamp_duty_cost": 0.0,
                "remaining_shares": 100,
                "price": 9.0,
                "price_limit_blocked": True,
                "suspension_blocked": False,
            },
        ]
    )
    tax = build_trade_tax_ledger(orders)
    assert set(tax["tax_type"]) == {"stamp_duty", "transfer_fee"}
    assert tax_ledger_total(tax) > 1.0

    valuation = build_blocked_order_valuation_ledger(orders)
    assert valuation.iloc[0]["freeze_type"] == "limit_down_liquidity_freeze"
    assert valuation.iloc[0]["economic_value"] < valuation.iloc[0]["nominal_value"]
    assert not valuation_discount_by_date(valuation).empty

    lineage = build_default_feature_lineage(["close_nominal", "backward_factor", "sector_parent"])
    assert set(lineage["lineage_risk_level"]) == {"low", "high"}
    timestamp_audit = audit_feature_timestamps(
        pd.DataFrame({"date": ["2024-01-02"], "feature_timestamp": ["2024-01-02"]})
    )
    assert timestamp_audit.iloc[0]["status"] == "passed"

    manifest = build_reproducibility_manifest()
    assert manifest["manifest_hash"]
    assert manifest["execution_model"]["execution_price_rule"] == "nominal_daily_price_only"

    admission = build_formal_admission_report()
    assert {"gate", "status", "formal_block_reason_code", "detail"}.issubset(admission.columns)
    assert "manual_review_required" in set(admission["status"])

    print("Formal infrastructure verification passed.")


if __name__ == "__main__":
    verify_formal_infrastructure()
