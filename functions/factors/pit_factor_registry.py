"""Canonical runtime contract for PIT Level-2 fundamental and event factors."""
from __future__ import annotations


def _spec(name, source, family, role, *, module="fundamental", direction="higher_better"):
    return {
        "factor_name": name,
        "raw_column": f"cand_{name}",
        "source_column": source,
        "module": module,
        "family": family,
        "allowed_roles": role,
        "direction": direction,
        "candidate_pool": "pit_level2_appeal",
        "source_file": "functions/factors/pit_factor_registry.py",
    }


PIT_FACTOR_SPECS = (
    _spec("fund_earnings_yield_ttm", "earnings_yield_ttm", "valuation", "entry_alpha"),
    _spec("fund_book_to_price", "book_to_price", "valuation", "entry_alpha"),
    _spec("fund_fcf_yield", "fcf_yield", "cashflow", "entry_alpha|hold_validation"),
    _spec("fund_roe_ttm_ind_neutral", "roe_ttm_ind_neutral", "profitability", "entry_alpha|hold_validation"),
    _spec("fund_roa_ttm_ind_neutral", "roa_ttm_ind_neutral", "profitability", "entry_alpha|hold_validation"),
    _spec("fund_gross_margin_ttm", "gross_margin_ttm", "profitability", "hold_validation"),
    _spec("fund_operating_margin_ttm", "operating_margin_ttm", "profitability", "hold_validation"),
    _spec("fund_asset_growth_neg", "asset_growth_neg", "investment", "entry_alpha|risk_override"),
    _spec("fund_capex_growth_neg", "capex_growth_neg", "investment", "risk_override|hold_validation"),
    _spec("fund_capex_to_assets_neg", "capex_to_assets_neg", "investment", "risk_override|hold_validation"),
    _spec("fund_ocf_to_net_profit", "ocf_to_net_profit", "cashflow", "hold_validation"),
    _spec("fund_accruals_neg", "accruals_neg", "cashflow", "risk_override|hold_validation"),
    _spec("fund_cash_profit_quality", "cash_profit_quality", "cashflow", "hold_validation"),
    _spec("fund_revenue_yoy_accel", "revenue_yoy_accel", "growth", "entry_alpha"),
    _spec("fund_profit_yoy_accel", "profit_yoy_accel", "growth", "entry_alpha"),
    _spec("fund_growth_stability", "growth_stability", "growth", "hold_validation"),
    _spec("fund_growth_surprise", "growth_surprise", "growth", "entry_alpha"),
    _spec("fund_revenue_profit_sync", "revenue_profit_sync", "growth", "hold_validation"),
    _spec("event_earnings_forecast_positive", "earnings_forecast_positive", "event", "timing_filter", module="event"),
    _spec("event_earnings_forecast_negative", "earnings_forecast_negative", "event", "risk_override", module="event", direction="lower_better"),
    _spec("event_buyback_announcement", "buyback_announcement", "event", "timing_filter|hold_validation", module="event"),
    _spec("event_shareholder_increase", "shareholder_increase", "event", "timing_filter|hold_validation", module="event"),
    _spec("event_shareholder_decrease", "shareholder_decrease", "event", "risk_override", module="event", direction="lower_better"),
    _spec("event_announcement_density", "announcement_density", "event", "timing_filter|risk_override", module="event"),
)


def pit_factor_registry_rows(*, families=None) -> list[dict]:
    selected = set(families or ())
    return [dict(spec) for spec in PIT_FACTOR_SPECS if not selected or spec["family"] in selected]


def pit_factor_raw_columns() -> frozenset[str]:
    return frozenset(spec["raw_column"] for spec in PIT_FACTOR_SPECS)


def append_pit_factor_aliases(frame):
    data = frame.copy()
    for spec in PIT_FACTOR_SPECS:
        source = spec["source_column"]
        if source in data.columns:
            data[spec["raw_column"]] = data[source]
    return data
