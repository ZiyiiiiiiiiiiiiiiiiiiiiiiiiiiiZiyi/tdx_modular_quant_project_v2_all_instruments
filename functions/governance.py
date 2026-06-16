# -*- coding: utf-8 -*-
"""Formal-readiness gates and explicit exploratory fallback disclosure."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    BENCHMARK_REPORT_CSV,
    CORPORATE_ACTIONS_PARQUET,
    FORMAL_MODE_NAME,
    MARKET_CAP_PARQUET,
    RESEARCH_RUN_MODE,
    TEST_LOCK_ENABLED,
    EXECUTION_MODEL_VERSION,
)


class FormalStatus(str, Enum):
    EXPLORATORY = "exploratory"
    EXPLORATORY_AFTER_P0_ENGINE = "exploratory_after_p0_engine"
    FORMAL_CANDIDATE = "formal_candidate"
    FORMAL_CANDIDATE_LIMITED = "formal_candidate_limited"
    FORMAL_TESTED = "formal_tested"
    FORMAL_BLOCKED = "formal_blocked"
    FORMAL_CONTAMINATED = "formal_contaminated"


class FormalBlockReason(str, Enum):
    GOVERNANCE_NOT_SIGNED = "GOVERNANCE_NOT_SIGNED"
    PIT_ADJUSTMENT_UNVERIFIED = "PIT_ADJUSTMENT_UNVERIFIED"
    PIT_CORPORATE_ACTION_UNVERIFIED = "PIT_CORPORATE_ACTION_UNVERIFIED"
    PIT_UNIVERSE_UNVERIFIED = "PIT_UNIVERSE_UNVERIFIED"
    PIT_INDUSTRY_UNVERIFIED = "PIT_INDUSTRY_UNVERIFIED"
    INDUSTRY_PIT_PARTIAL = "INDUSTRY_PIT_PARTIAL"
    LINEAGE_COVERAGE_LOW = "LINEAGE_COVERAGE_LOW"
    FEATURE_TIMESTAMP_AUDIT_FAILED = "FEATURE_TIMESTAMP_AUDIT_FAILED"
    LABEL_LEAKAGE_AUDIT_FAILED = "LABEL_LEAKAGE_AUDIT_FAILED"
    EXECUTION_PRICE_NOT_NOMINAL = "EXECUTION_PRICE_NOT_NOMINAL"
    T_PLUS_ONE_LOCK_FAILED = "T_PLUS_ONE_LOCK_FAILED"
    ACCOUNT_LEDGER_INCOMPLETE = "ACCOUNT_LEDGER_INCOMPLETE"
    TAX_LEDGER_MISSING = "TAX_LEDGER_MISSING"
    UNSUPPORTED_EVENT_TYPE = "UNSUPPORTED_EVENT_TYPE"
    SLIPPAGE_SENSITIVITY_MISSING = "SLIPPAGE_SENSITIVITY_MISSING"
    FORMAL_SENSITIVE_TO_COST_MODEL = "FORMAL_SENSITIVE_TO_COST_MODEL"
    GOLDEN_TEST_FAILED = "GOLDEN_TEST_FAILED"
    REPRO_PACKAGE_MISSING = "REPRO_PACKAGE_MISSING"
    BENCHMARK_NOT_INVESTABLE = "BENCHMARK_NOT_INVESTABLE"
    LIMITED_REVIEW_INDEPENDENCE = "LIMITED_REVIEW_INDEPENDENCE"
    MANUAL_REVIEW_REJECTED = "MANUAL_REVIEW_REJECTED"
    POST_TEST_CONTAMINATED = "POST_TEST_CONTAMINATED"


@dataclass(frozen=True)
class FallbackDisclosure:
    component: str
    substitute: str
    reason: str
    block_reason_code: str


@dataclass(frozen=True)
class ResearchStatus:
    research_mode: str
    formal_status: str
    formal_eligible: bool
    formal_block_reason_code: str
    formal_block_reason_detail: str
    data_manifest_id: str
    execution_model_version: str
    benchmark_id: str
    review_status: str


def default_fallback_disclosures() -> list[FallbackDisclosure]:
    benchmark_disclosure = _benchmark_fallback_disclosure()
    return [
        FallbackDisclosure(
            "PIT adjustment factors",
            "Keep feature-price provenance visible and block formal adjusted-price claims.",
            "Provider factor rows exist, but end-to-end PIT observability and revision auditing are not proven.",
            FormalBlockReason.PIT_ADJUSTMENT_UNVERIFIED.value,
        ),
        FallbackDisclosure(
            "PIT corporate-action chain",
            "Use local nominal TDX bars for execution and mark adjusted-price formal claims blocked.",
            "Local .day files do not prove announcement, record, ex-date, payment-date, and revision timestamps.",
            FormalBlockReason.PIT_CORPORATE_ACTION_UNVERIFIED.value,
        ),
        FallbackDisclosure(
            "PIT universe",
            "Run exploratory strategies with an explicit survivorship-risk marker.",
            "No PIT listing/delisting universe is attached.",
            FormalBlockReason.PIT_UNIVERSE_UNVERIFIED.value,
        ),
        FallbackDisclosure(
            "PIT industry classification",
            "Run non-industry exploratory strategies only.",
            "No PIT industry mapping is attached.",
            FormalBlockReason.PIT_INDUSTRY_UNVERIFIED.value,
        ),
        FallbackDisclosure(
            "Formal account and corporate-action ledger",
            "Use the integrated order-cost ledger and synthetic account golden tests as an exploratory engine.",
            "The live backtest writes exploratory cash, tax, and conservative valuation ledgers, but it does not yet maintain a complete share-level corporate-action accounting timeline.",
            FormalBlockReason.ACCOUNT_LEDGER_INCOMPLETE.value,
        ),
        FallbackDisclosure(
            "Formal tax ledger",
            "Report modeled commission, stamp duty, and tax impact while blocking formal tax claims.",
            "The live backtest does not yet maintain a complete tax ledger or holding-period dividend-tax model.",
            FormalBlockReason.TAX_LEDGER_MISSING.value,
        ),
        benchmark_disclosure,
        FallbackDisclosure(
            "Independent review",
            "Keep results exploratory and require a future reviewer timestamp or signature before formal release.",
            "Signed independent manual review is not attached.",
            FormalBlockReason.LIMITED_REVIEW_INDEPENDENCE.value,
        ),
        FallbackDisclosure(
            "Formal reproducibility package",
            "Use current run metadata, config snapshots, and generated readiness reports for exploratory reproduction.",
            "A signed formal manifest with complete external fingerprints is not attached.",
            FormalBlockReason.REPRO_PACKAGE_MISSING.value,
        ),
    ]


def build_research_status() -> ResearchStatus:
    disclosures = default_fallback_disclosures()
    reason_codes = [item.block_reason_code for item in disclosures]
    formal_ready = (
        RESEARCH_RUN_MODE == FORMAL_MODE_NAME
        and Path(ADJUSTMENT_FACTORS_PARQUET).exists()
        and Path(CORPORATE_ACTIONS_PARQUET).exists()
        and Path(MARKET_CAP_PARQUET).exists()
        and TEST_LOCK_ENABLED
        and not disclosures
    )
    return ResearchStatus(
        research_mode=RESEARCH_RUN_MODE,
        formal_status=(
            FormalStatus.FORMAL_CANDIDATE.value
            if formal_ready
            else FormalStatus.EXPLORATORY_AFTER_P0_ENGINE.value
        ),
        formal_eligible=formal_ready,
        formal_block_reason_code="|".join(reason_codes),
        formal_block_reason_detail="; ".join(item.reason for item in disclosures),
        data_manifest_id="runtime_manifest_pending",
        execution_model_version=EXECUTION_MODEL_VERSION,
        benchmark_id=_resolved_benchmark_id(),
        review_status="independent_review_pending",
    )


def research_status_dict() -> dict:
    return asdict(build_research_status())


def resolve_formal_status(block_reason_codes, *, post_test_modified=False, limited_independence=False):
    """Apply the irreversible contamination and limited-independence caps."""
    reasons = {str(code) for code in block_reason_codes}
    if post_test_modified or FormalBlockReason.POST_TEST_CONTAMINATED.value in reasons:
        return FormalStatus.FORMAL_CONTAMINATED.value
    blocking = {
        FormalBlockReason.MANUAL_REVIEW_REJECTED.value,
        FormalBlockReason.GOLDEN_TEST_FAILED.value,
        FormalBlockReason.PIT_ADJUSTMENT_UNVERIFIED.value,
        FormalBlockReason.PIT_CORPORATE_ACTION_UNVERIFIED.value,
        FormalBlockReason.PIT_UNIVERSE_UNVERIFIED.value,
        FormalBlockReason.BENCHMARK_NOT_INVESTABLE.value,
    }
    if reasons & blocking:
        return FormalStatus.FORMAL_BLOCKED.value
    if limited_independence or FormalBlockReason.LIMITED_REVIEW_INDEPENDENCE.value in reasons:
        return FormalStatus.FORMAL_CANDIDATE_LIMITED.value
    return FormalStatus.FORMAL_CANDIDATE.value


def print_runtime_disclosure() -> None:
    status = build_research_status()
    disclosures = default_fallback_disclosures()
    print("\n========== Final Fallback Disclosure ==========")
    print("Used substitutes:", "YES" if disclosures else "NO")
    print("Research mode:", status.research_mode)
    print("Formal status:", status.formal_status)
    print("Formal eligible:", status.formal_eligible)
    if disclosures:
        for index, item in enumerate(disclosures, start=1):
            print(f"{index}. Component: {item.component}")
            print(f"   Substitute: {item.substitute}")
            print(f"   Reason: {item.reason}")
            print(f"   Formal block reason: {item.block_reason_code}")
    else:
        print("No substitute content was used.")
    print("===============================================")


def _benchmark_fallback_disclosure() -> FallbackDisclosure:
    report_path = Path(BENCHMARK_REPORT_CSV)
    if report_path.exists():
        try:
            import pandas as pd

            report = pd.read_csv(report_path)
        except Exception:
            report = None
        if report is not None and not report.empty and {"benchmark_id", "symbol", "status"}.issubset(report.columns):
            available = report[report["status"].astype(str).str.lower() == "available"].copy()
            if not available.empty:
                row = available.iloc[0]
                benchmark_id = str(row.get("benchmark_id", ""))
                symbol = str(row.get("symbol", ""))
                return FallbackDisclosure(
                    "Investable benchmark",
                    "Use the attached tradable ETF benchmark for exploratory excess-return comparison, but keep formal ranking blocked pending audited benchmark governance.",
                    f"Exploratory benchmark comparison is available via {benchmark_id}:{symbol}, but formal benchmark admission and review sign-off are not complete.",
                    FormalBlockReason.BENCHMARK_NOT_INVESTABLE.value,
                )
    return FallbackDisclosure(
        "Investable benchmark",
        "Print strategy metrics without asserting a formal ranking.",
        "Investable benchmark artifacts are not attached.",
        FormalBlockReason.BENCHMARK_NOT_INVESTABLE.value,
    )


def _resolved_benchmark_id() -> str:
    disclosure = _benchmark_fallback_disclosure()
    text = disclosure.reason
    if "via " in text:
        return text.split("via ", 1)[1].split(",", 1)[0].strip()
    return "investable_benchmark_pending"
