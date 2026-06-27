"""
如果你想测试沪深股票 + ETF

建议你现在先把 config.py 改成：

INCLUDE_MARKETS = ("sh", "sz")

INCLUDE_INSTRUMENT_TYPES = (
    "stock",
    "etf_fund",
)

然后保持：

READ_LIMIT = 200

这样会读沪深市场的前 200 个股票/ETF，更适合测试。

如果你只想看 ETF 选股

可以改成：

INCLUDE_MARKETS = ("sh", "sz")

INCLUDE_INSTRUMENT_TYPES = (
    "etf_fund",
)

READ_LIMIT = 200

这样输出的 strategy_selection.parquet 里应该就是 ETF / 场内基金。


"""
# -*- coding: utf-8 -*-
import hashlib
import json
from pathlib import Path

TDX_DIR = Path(r"F:\tongxinda")
PROJECT_DIR = Path(__file__).resolve().parent

DATA_DIR = PROJECT_DIR / "data"
RAW_EXTERNAL_DIR = DATA_DIR / "raw_external"
PROCESSED_DIR = DATA_DIR / "processed"
REPORT_DIR = DATA_DIR / "reports"
RESULT_DIR = PROJECT_DIR / "results"
RUNS_DIR = PROJECT_DIR / "runs"
PIPELINE_CACHE_JSON = REPORT_DIR / "pipeline_run_cache.json"

for folder in [DATA_DIR, RAW_EXTERNAL_DIR, PROCESSED_DIR, REPORT_DIR, RESULT_DIR, RUNS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

START_DATE = "2018-01-01"
END_DATE = None

# V2: keep all beginner-accessible and useful market instruments.
# Types:
# stock, etf_fund, index, bond, convertible_bond, b_share, unknown
INCLUDE_MARKETS = ("sh", "sz", "bj")
INCLUDE_INSTRUMENT_TYPES = (
    "stock",
    "etf_fund",
    "index",
    "bond",
    "convertible_bond",
    "b_share",
    "unknown",
)

# First test with 50. Change to None for all. None

READ_LIMIT = None

ABNORMAL_RETURN_THRESHOLD = 0.20

ENABLE_HOT_THEME_BIAS = True
HOT_THEME_SLOT_RATIO = 0.3
HOT_THEME_WEIGHTS = {
    "ai_infrastructure": 1.00,
    "robotics_automation": 0.90,
    "low_altitude_aerospace": 0.80,
}

ENABLE_LEARNING_STRATEGIES = True
LEARNING_STRATEGY_WHITELIST = None
ENABLE_PLACEHOLDER_STRATEGIES = False
ENABLE_QUANTUM_INSPIRED_STRATEGIES = False

ENABLE_EXPERIMENT_TRACKING = True
RUN_ID_PREFIX = "run"
RUN_METADATA_FILENAME = "metadata.json"
DATA_VERSION = "tdx_daily_v2"
ADJUSTMENT_DATA_VERSION = "baostock_adjust_factor_v1"
CORPORATE_ACTION_DATA_VERSION = "baostock_dividend_v1"
RESEARCH_RUN_MODE = "exploratory"
FORMAL_MODE_NAME = "formal"
ADJUSTED_FEATURE_PRICE_MODE = "point_in_time_backward"
RESEARCH_IDEA_ID = "baseline_rebuild_v2"
RESEARCH_ATTEMPT_ID = "attempt_01"
BASELINE_VERSION = "pre_p0_legacy"
WALK_FORWARD_TRAIN_PERIODS = 252
WALK_FORWARD_VALIDATION_PERIODS = 63
WALK_FORWARD_TEST_PERIODS = 63
WALK_FORWARD_STEP_PERIODS = 21
WALK_FORWARD_PURGE_PERIODS = 5
WALK_FORWARD_EMBARGO_PERIODS = 5
VALIDATION_MAX_ATTEMPTS = 5
TEST_LOCK_ENABLED = True
LABEL_DEFAULT_HORIZONS = (5, 10, 20)
LABEL_DEFAULT_TARGET_RETURN = 0.02
FEATURE_WINSORIZE_LOWER = 0.01
FEATURE_WINSORIZE_UPPER = 0.99
FEATURE_ROBUST_SCALE_EPSILON = 1e-9
FACTOR_MIN_COVERAGE_RATIO = 0.10
FEATURE_PTI_ADJUSTMENT_MIN_COVERAGE_RATIO = 1.0
FACTOR_REGISTRY_STATUS_DEFAULT = "experimental"
REPORT_OUTPUT_MD = RESULT_DIR / "strategy_diagnostic_report.md"
FEATURE_COVERAGE_REPORT_CSV = REPORT_DIR / "feature_coverage_report.csv"
FEATURE_DISTRIBUTION_REPORT_CSV = REPORT_DIR / "feature_distribution_report.csv"
FEATURE_STABILITY_REPORT_CSV = REPORT_DIR / "feature_stability_report.csv"
FEATURE_REGISTRY_REPORT_CSV = REPORT_DIR / "feature_registry_validation_report.csv"
FEATURE_MEMORY_REPORT_CSV = REPORT_DIR / "feature_memory_report.csv"
MODEL_TRAINING_DIAGNOSTICS_CSV = REPORT_DIR / "model_training_diagnostics.csv"
FEATURE_STORAGE_MODE = "pruned"
FEATURE_DOWNCAST_FLOATS = True
MULTI_WINDOW_BACKTEST_SUMMARY_CSV = RESULT_DIR / "multi_window_backtest_summary.csv"
MULTI_WINDOW_BACKTEST_REPORT_MD = RESULT_DIR / "multi_window_backtest_report.md"
MULTI_WINDOW_DEFAULT_MONTHS = 12
MULTI_WINDOW_DEFAULT_STEP_MONTHS = 12
RUNTIME_CONFIG_SNAPSHOT_JSON = REPORT_DIR / "runtime_config_snapshot.json"
EVENT_DATA_PARQUET = PROCESSED_DIR / "event_data.parquet"
EVENT_DATA_QUALITY_CSV = REPORT_DIR / "event_data_quality_report.csv"
QML_MIN_TEST_WINDOWS = 5
QML_WILCOXON_P_THRESHOLD = 0.05
QML_MAX_DRAWDOWN_MULTIPLIER = 1.2

DEFAULT_CORPORATE_ACTIONS_SOURCE = "manual_csv"
BAOSTOCK_ADJUSTMENT_SOURCE = "baostock_adjust_factor"
BAOSTOCK_CORPORATE_ACTION_SOURCE = "baostock_dividend"
CODE_MAPPING_CSV = REPORT_DIR / "code_mapping_report.csv"
CORPORATE_ACTIONS_PARQUET = PROCESSED_DIR / "corporate_actions.parquet"
CORPORATE_ACTIONS_QUALITY_CSV = REPORT_DIR / "corporate_actions_quality_report.csv"
ADJUSTMENT_FACTORS_PARQUET = PROCESSED_DIR / "adjustment_factors.parquet"
ADJUSTMENT_FACTORS_QUALITY_CSV = REPORT_DIR / "adjustment_factors_quality_report.csv"
MARKET_CAP_PARQUET = PROCESSED_DIR / "market_cap_history.parquet"
MARKET_CAP_QUALITY_CSV = REPORT_DIR / "market_cap_quality_report.csv"

COMMISSION_RATE = 0.0003
STAMP_DUTY_RATE = 0.001
SLIPPAGE_RATE = 0.0005
MIN_LOT_SIZE = 100
BACKTEST_INITIAL_CASH = 1_000_000.0
BACKTEST_RISK_FREE_RATE = 0.0
BACKTEST_SHOW_PLOT = False
ENABLE_T_PLUS_ONE = True
ENABLE_PRICE_LIMIT_CHECK = True
ENABLE_SUSPENSION_CHECK = True
MAX_LIQUIDITY_LOCK_DAYS = 10
LIQUIDITY_LOCK_REPORT_CSV = RESULT_DIR / "extreme_liquidity_lock_report.csv"
BACKTEST_SKIPPED_STRATEGIES_CSV = RESULT_DIR / "backtest_skipped_strategies.csv"
ORDER_LEDGER_PREFIX = "backtest_orders"
BACKTEST_SUMMARY_V2_CSV = RESULT_DIR / "backtest_strategy_summary_v2.csv"
STRATEGY_RANK_SHIFT_REPORT_CSV = RESULT_DIR / "strategy_rank_shift_report.csv"
FORMAL_ADMISSION_REPORT_CSV = REPORT_DIR / "formal_admission_report.csv"
FORMAL_MANIFEST_JSON = REPORT_DIR / "formal_reproducibility_manifest.json"
DATA_INTEGRITY_WHITEPAPER_MD = REPORT_DIR / "data_integrity_whitepaper.md"
DATA_INTEGRITY_REPORT_CSV = REPORT_DIR / "data_integrity_report.csv"
DATA_VERIFICATION_STATUS_JSON = REPORT_DIR / "data_verification_status.json"
EVENT_DENSITY_REPORT_CSV = REPORT_DIR / "strategy_event_density_report.csv"
STRATEGY_ADMISSION_REPORT_CSV = REPORT_DIR / "strategy_admission_report.csv"
V6_GAP_MATRIX_CSV = REPORT_DIR / "v6_implementation_gap_matrix.csv"
V6_RUNTIME_MONITORING_CSV = REPORT_DIR / "v6_runtime_monitoring.csv"
V6_RUNTIME_STATUS_JSON = REPORT_DIR / "v6_runtime_status.json"
FEATURE_LINEAGE_CSV = REPORT_DIR / "feature_lineage_report.csv"
FEATURE_TIMESTAMP_AUDIT_CSV = REPORT_DIR / "feature_timestamp_audit.csv"
BENCHMARK_REPORT_CSV = RESULT_DIR / "investable_benchmark_report.csv"
DEFAULT_INVESTABLE_BENCHMARK_ID = "hs300_etf"
DEFAULT_INVESTABLE_BENCHMARK_PRICE_COL = "close_nominal"
TAX_LEDGER_PREFIX = "backtest_tax_ledger"
CASH_LEDGER_PREFIX = "backtest_cash_ledger"
VALUATION_LEDGER_PREFIX = "backtest_valuation_ledger"
CORPORATE_ACTION_LEDGER_CSV = REPORT_DIR / "corporate_action_ledger.csv"
ADJUSTMENT_PTI_QUALITY_CSV = REPORT_DIR / "adjustment_pti_quality_report.csv"

DEFAULT_BACKTEST_CAPITAL_PROFILE = "institutional_1m"
BACKTEST_CAPITAL_PROFILES = {
    "institutional_1m": {
        "label": "1,000,000 baseline",
        "initial_cash": float(BACKTEST_INITIAL_CASH),
        "min_cash_buffer": 0.0,
        "max_positions": None,
        "affordability_first": False,
        "skip_unaffordable_symbols": False,
        "notes": "Legacy baseline profile. Uses the existing strategy target breadth.",
    },
    "institutional_10m": {
        "label": "10,000,000 large account",
        "initial_cash": 10_000_000.0,
        "min_cash_buffer": 0.0,
        "max_positions": None,
        "affordability_first": False,
        "skip_unaffordable_symbols": False,
        "notes": "Large-account comparison profile for high-capacity research.",
    },
    "retail_20k": {
        "label": "20,000 retail",
        "initial_cash": 20_000.0,
        "min_cash_buffer": 500.0,
        "max_positions": 5,
        "affordability_first": True,
        "skip_unaffordable_symbols": True,
        "notes": "Small-account profile with lot-size and cash-buffer discipline.",
    },
}

TRADE_PAIR_LEDGER_PREFIX = "backtest_trade_pairs"
OPEN_POSITION_LEDGER_PREFIX = "backtest_open_positions"

EXECUTION_MODEL_VERSION = "tdx_daily_t_plus_1_nominal_v2"
SIGNAL_TIME_RULE = "t_close_after_market"
ORDER_TIME_RULE = "t_plus_1_open_preferred_daily_proxy"
EXECUTION_PRICE_RULE = "nominal_daily_price_only"
EXECUTION_FEASIBILITY_RULE = "suspension_and_price_limit_and_cash_budget"
FALLBACK_PRICE_RULE = "daily_nominal_close_proxy_disclosed"
DATA_RESOLUTION_REQUIRED = "daily"

TRANSFER_FEE_RATE = 0.00001
DIVIDEND_TAX_RATE = 0.20
TAX_POLICY_VERSION = "cn_a_share_conservative_v1"
DIVIDEND_TAX_ASSUMPTION = "Conservative uniform dividend tax rate; holding-period tax is not modeled."
TAX_MODEL_LIMITATIONS = "Dividend payment-date and holding-period tax require verified corporate-action ledgers."

SUSPENSION_FORMAL_BLOCK_AUM_RATIO = 0.05
LIMIT_DOWN_LIQUIDITY_DISCOUNT = 0.10
VALUATION_MODEL_VERSION = "conservative_liquidity_discount_v1"
VALUATION_ASSUMPTION = "Blocked positions are discounted conservatively from nominal value."

RAW_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_raw.parquet"
CLEAN_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_clean.parquet"
FEATURE_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_features.parquet"

FAILED_CODES_CSV = REPORT_DIR / "failed_codes.csv"
STOCK_INFO_CSV = REPORT_DIR / "instrument_info.csv"
ABNORMAL_RETURN_CSV = REPORT_DIR / "abnormal_return_rows.csv"
DATA_QUALITY_SUMMARY_CSV = REPORT_DIR / "data_quality_summary.csv"
DATA_CONTINUITY_REPORT_CSV = REPORT_DIR / "data_continuity_report.csv"
DATA_CONTINUITY_GAP_DAYS_WARN = 10


def get_backtest_capital_profile(
    profile_name=None,
    *,
    initial_cash=None,
    max_positions_override="__profile_default__",
    min_cash_buffer=None,
):
    selected = str(profile_name or DEFAULT_BACKTEST_CAPITAL_PROFILE)
    if selected not in BACKTEST_CAPITAL_PROFILES:
        raise ValueError(
            f"Unknown backtest capital profile: {selected}. "
            f"Available: {sorted(BACKTEST_CAPITAL_PROFILES)}"
        )
    profile = dict(BACKTEST_CAPITAL_PROFILES[selected])
    profile["name"] = selected
    profile["initial_cash"] = float(profile["initial_cash"])
    profile["min_cash_buffer"] = float(profile.get("min_cash_buffer", 0.0) or 0.0)
    max_positions = profile.get("max_positions")
    profile["max_positions"] = None if max_positions in (None, "", 0) else int(max_positions)
    profile["affordability_first"] = bool(profile.get("affordability_first", False))
    profile["skip_unaffordable_symbols"] = bool(profile.get("skip_unaffordable_symbols", False))
    override_parts = []
    if initial_cash not in (None, ""):
        profile["initial_cash"] = float(initial_cash)
        if profile["initial_cash"] <= 0:
            raise ValueError("Backtest initial cash must be positive")
        override_parts.append(f"cash{_profile_number_slug(profile['initial_cash'])}")
    if max_positions_override != "__profile_default__":
        if max_positions_override in (None, "", 0, "0"):
            profile["max_positions"] = None
            override_parts.append("posall")
        else:
            profile["max_positions"] = int(max_positions_override)
            if profile["max_positions"] <= 0:
                raise ValueError("Backtest max positions must be positive or blank/0 for unlimited")
            override_parts.append(f"pos{profile['max_positions']}")
    if min_cash_buffer not in (None, ""):
        profile["min_cash_buffer"] = float(min_cash_buffer)
        if profile["min_cash_buffer"] < 0:
            raise ValueError("Backtest min cash buffer cannot be negative")
        override_parts.append(f"buf{_profile_number_slug(profile['min_cash_buffer'])}")
    if override_parts:
        profile["base_profile"] = selected
        profile["name"] = f"{selected}__{'__'.join(override_parts)}"
        profile["label"] = f"{profile.get('label', selected)} custom"
    return profile


def backtest_profile_suffix(profile_name=None):
    selected = str(profile_name or DEFAULT_BACKTEST_CAPITAL_PROFILE)
    return "" if selected == DEFAULT_BACKTEST_CAPITAL_PROFILE else f"__{selected}"


def _profile_number_slug(value):
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", "p").replace("-", "m")

# User-facing strategy defaults. Keep these here so main.py, batch runners,
# quick runners, and the auto-complete workflow cannot drift into different
# date windows or selection sizes. Step on/off control now lives in
# pipeline_steps.py.
STRATEGY_SCORE_COL = "score_mom_lowvol"
STRATEGY_TOP_N = 30
STRATEGY_FREQ = "ME"
STRATEGY_FREQ_OVERRIDES = {
    "eod_close_strength": "D",
    "limit_up_follow": "D",
    "macd_cross": "D",
    "ma_cross": "D",
    "price_volume_breakout": "D",
    "consecutive_decline_rebound": "D",
    "holiday_effect": "D",
    "kdj_oversold_cross": "D",
    "low_volume_pullback": "D",
}
STRATEGY_START_DATE = "2021-01-01"
STRATEGY_END_DATE = "2024-12-31"
STRATEGY_INCLUDE_TYPES = ("stock", "etf_fund")
EXPORT_SELECTION_EXCEL = True
PRINT_SELECTION_ROWS = 30

# Score qualification threshold: only stocks whose score percentile exceeds
# this threshold (relative to the daily universe) can enter the portfolio.
# If too few stocks qualify, remaining capital stays in previously qualified
# stocks. If no stocks qualify, go to cash.
# Range: 0.0 to 1.0. 0.0 = no filter, 0.5 = median, 0.8 = top 20%.
# Note: This is the default value. When MarketRegimePolicy is enabled,
# the actual threshold will be dynamically adjusted based on bull/bear regime.
STRATEGY_MIN_SCORE_PERCENTILE = 0.80

AUTO_COMPLETE_MAIN_PYTHON = Path(r"E:\ForANACONDA\python.exe")
AUTO_COMPLETE_EXTERNAL_DATA_PYTHON = Path(r"C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe")
AUTO_COMPLETE_STATE_PATH = REPORT_DIR / "auto_complete_after_vpn_state.json"
AUTO_COMPLETE_LOCK_PATH = REPORT_DIR / "auto_complete_after_vpn.lock"
AUTO_COMPLETE_LOCAL_GOVERNANCE_START_DATE = STRATEGY_START_DATE
AUTO_COMPLETE_LOCAL_GOVERNANCE_END_DATE = STRATEGY_END_DATE
AUTO_COMPLETE_MAX_STRATEGY_WORKERS = 2
AUTO_COMPLETE_DEFAULT_BATCH_SIZE = 1
STRATEGY_BATCH_SIZE_DEFAULT = 1
REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN = 0.50
REPORT_TOP5_WEIGHT_SUM_GAP_WARN = 0.20
FEATURE_PARQUET_GB_WARN = 1.0
FEATURE_COLUMN_COUNT_WARN = 250

# Centralized command-line and integration defaults. Scripts may expose
# overrides, but their defaults must come from this section.
CLI_MAIN_BATCH_SIZE = STRATEGY_BATCH_SIZE_DEFAULT
CLI_MAIN_BATCH_INDEX = 0
CLI_MAIN_MODE = "pipeline"
MAIN_STRATEGY_EXECUTION_MODE = "auto"
MAIN_STRATEGY_BOUNDED_PARQUET_GB_THRESHOLD = 1.0
CLI_MAIN_SAFETY_PROXY_MODE = "strict"
CLI_MAIN_GOVERNANCE_VARIANT = "rules_based_president"
CLI_STRATEGY_BATCH_MODE = "all"
CLI_STRATEGY_BATCH_OFFSET = 0
CLI_STRATEGY_BATCH_INDEX = None
CLI_AUTO_COMPLETE_STRATEGY_WORKERS = 1
CLI_AUTO_COMPLETE_START_BATCH_INDEX = 0
CLI_GOVERNANCE_START_DATE = STRATEGY_START_DATE
CLI_GOVERNANCE_END_DATE = STRATEGY_END_DATE
CLI_GOVERNANCE_MAX_DAYS = None
CLI_GOVERNANCE_SAFETY_PROXY_MODE = "strict"
CLI_GOVERNANCE_VARIANT = "rules_based_president"

INDEX_CONSTITUENT_DEFAULT_SOURCE = "akshare"
INDEX_CONSTITUENT_COVERAGE_START_DATE = "2024-09-23"
INDEX_CONSTITUENT_COVERAGE_END_DATE = None

EXTERNAL_DATA_FACTOR_HISTORY_START = "1990-01-01"
EXTERNAL_DATA_END_DATE = None
EXTERNAL_DATA_SYMBOL_LIMIT = None
EXTERNAL_DATA_BATCH_SIZE = 50
EXTERNAL_DATA_DIVIDEND_BATCH_SIZE = 5
EXTERNAL_DATA_REQUEST_DELAY_SECONDS = 0.35
EXTERNAL_DATA_BATCH_DELAY_SECONDS = 2.0
EXTERNAL_DATA_LOGIN_RETRIES = 3
EXTERNAL_DATA_LOGIN_RETRY_DELAY_SECONDS = 5.0
EXTERNAL_DATA_SOCKET_TIMEOUT_SECONDS = 30.0

AUTO_COMPLETE_FETCH_BATCH_SIZE = 50
AUTO_COMPLETE_FETCH_DIVIDEND_BATCH_SIZE = 5
AUTO_COMPLETE_FETCH_REQUEST_DELAY_SECONDS = 0.6
AUTO_COMPLETE_FETCH_BATCH_DELAY_SECONDS = 3.0
AUTO_COMPLETE_FETCH_LOGIN_RETRIES = 5
AUTO_COMPLETE_FETCH_LOGIN_RETRY_DELAY_SECONDS = 8.0
AUTO_COMPLETE_FETCH_SOCKET_TIMEOUT_SECONDS = 30.0
AUTO_COMPLETE_MARKET_CAP_SOURCE = "tdx_finance"

MARKET_CAP_DEFAULT_SOURCE = "tdx_finance"
MARKET_CAP_REPORT_START_DATE = "2017-01-01"
MARKET_CAP_MAX_REPORT_FILES = None
MARKET_CAP_BATCH_SIZE = 50
MARKET_CAP_REQUEST_DELAY_SECONDS = 0.35
MARKET_CAP_BATCH_DELAY_SECONDS = 2.0

ARTIFACT_VALIDATION_SYMBOL_SAMPLE_SIZE = 24
ARTIFACT_VALIDATION_ROW_GROUP_SAMPLE_SIZE = 12
ARTIFACT_VALIDATION_ROWS_PER_GROUP = 200

EXTERNAL_DIAGNOSIS_DEPENDENCIES = ("baostock", "mootdx")
EXTERNAL_DIAGNOSIS_HOSTS = ("public-api.baostock.com", "down.tdx.com.cn")
EXTERNAL_DIAGNOSIS_TCP_ENDPOINTS = (("public-api.baostock.com", 10030),)
EXTERNAL_DIAGNOSIS_SOCKET_TIMEOUT_SECONDS = 5.0

STRATEGY_PARAMS_VERSION = "strategy_params_v3_technical_expansion"
STRATEGY_PARAMS = {
    "macd_trend": {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "horizon_days": 20,
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "max_holding_days": 20,
    },
    "rsi_reversal": {
        "windows": (6, 14, 24),
        "oversold": 30,
        "overbought": 70,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
    "turtle_breakout": {
        "entry_window": 20,
        "long_window": 55,
        "atr_window": 20,
        "add_unit_atr": 0.5,
        "max_units": 4,
        "horizon_days": 20,
        "stop_loss_atr": 2.0,
        "take_profit_atr": 4.0,
        "max_holding_days": 55,
    },
    "mean_reversion": {
        "ma_window": 20,
        "long_ma_window": 60,
        "bollinger_std": 2.0,
        "z_entry": -1.5,
        "z_exit": 0.0,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.06,
        "max_holding_days": 15,
    },
    "grid_trading": {
        "atr_window": 20,
        "grid_atr_multiplier": 1.0,
        "horizon_days": 5,
        "min_expected_return_to_cost": 3.0,
        "max_position_adjustment": 0.02,
        "max_abs_ret_20": 0.08,
        "max_holding_days": 5,
    },
    "eod_close_strength": {
        "min_close_location": 0.80,
        "min_intraday_return": 0.01,
        "min_volume_ratio": 1.20,
        "horizon_days": 5,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 5,
    },
    "limit_up_follow": {
        "min_close_location": 0.65,
        "horizon_days": 5,
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "max_holding_days": 5,
    },
    "macd_cross": {
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
    "ma_cross": {
        "fast": 5,
        "slow": 20,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
    "price_volume_breakout": {
        "lookback": 20,
        "min_volume_ratio": 1.50,
        "horizon_days": 10,
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "max_holding_days": 10,
    },
    "consecutive_decline_rebound": {
        "decline_days": 3,
        "max_prior_return": -0.05,
        "horizon_days": 5,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.07,
        "max_holding_days": 5,
    },
    "holiday_effect": {
        "minimum_calendar_gap_days": 4,
        "horizon_days": 5,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.06,
        "max_holding_days": 5,
    },
    "kdj_oversold_cross": {
        "window": 9,
        "oversold": 30,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
    "low_volume_pullback": {
        "max_volume_ratio": 0.80,
        "min_ret_5": -0.08,
        "max_ret_5": 0.0,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
}

PRECOMPUTED_STRATEGY_CONFIGS = {
    "macd_trend": {"score_col": "score_macd_trend", "payoff_ratio": 2.0},
    "turtle_breakout": {"score_col": "score_turtle_breakout", "payoff_ratio": 2.0},
    "mean_reversion": {"score_col": "score_mean_reversion", "payoff_ratio": 1.5},
    "rsi_reversal": {"score_col": "score_rsi_reversal", "payoff_ratio": 1.5},
    "grid_trading": {"score_col": "score_grid_trading", "payoff_ratio": 1.2},
    "alpha_hedge": {"score_col": "score_alpha_hedge", "payoff_ratio": 2.0},
    "event_driven": {"score_col": "score_event_driven", "payoff_ratio": 2.0},
    "eod_close_strength": {"score_col": "score_eod_close_strength", "payoff_ratio": 2.0},
    "limit_up_follow": {"score_col": "score_limit_up_follow", "payoff_ratio": 2.0},
    "macd_cross": {"score_col": "score_macd_cross", "payoff_ratio": 2.0},
    "ma_cross": {"score_col": "score_ma_cross", "payoff_ratio": 2.0},
    "price_volume_breakout": {"score_col": "score_price_volume_breakout", "payoff_ratio": 2.0},
    "consecutive_decline_rebound": {"score_col": "score_consecutive_decline_rebound", "payoff_ratio": 1.75},
    "holiday_effect": {"score_col": "score_holiday_effect", "payoff_ratio": 1.5},
    "kdj_oversold_cross": {"score_col": "score_kdj_oversold_cross", "payoff_ratio": 2.0},
    "low_volume_pullback": {"score_col": "score_low_volume_pullback", "payoff_ratio": 1.75},
}


def strategy_params_hash(params=None) -> str:
    payload = {
        "version": STRATEGY_PARAMS_VERSION,
        "params": params or STRATEGY_PARAMS,
    }
    encoded = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

# Phase-one decision council. These settings are frozen for exploratory
# rules-based governance backtests and must be included in run manifests.
ENABLE_DECISION_COUNCIL = True
DECISION_COUNCIL_VERSION = "rules_based_president_v2_p0_p1_5"
SAFETY_PROXY_MODE = "strict"
SAFETY_PROXY_SYMBOLS = ("sh510300", "sh510310", "sz159919")
SAFETY_PROXY_MAX_LAG_DAYS = 1
SAFETY_PROXY_MAX_MISSING_DAYS = 2
# Safety drawdown thresholds - adjusted to reduce excessive deleveraging.
# When MarketRegimePolicy is enabled, these are dynamically adjusted:
# - Bull market: More tolerant (higher thresholds)
# - Bear market: More sensitive (lower thresholds)
SAFETY_WARNING_DRAWDOWN = 0.020
SAFETY_HIGH_DRAWDOWN = 0.04
SAFETY_CRISIS_DRAWDOWN = 0.06
SAFETY_WARNING_LIQUIDITY_STRESS = 0.25
SAFETY_HIGH_LIQUIDITY_STRESS = 0.40
SAFETY_CRISIS_LIQUIDITY_STRESS = 0.55
SAFETY_WARNING_CONFIRM_DAYS = 3
SAFETY_HIGH_CONFIRM_DAYS = 3
SAFETY_CRISIS_CONFIRM_DAYS = 3
SAFETY_WARNING_EXIT_DAYS = 3
SAFETY_HIGH_EXIT_DAYS = 4
SAFETY_CRISIS_EXIT_DAYS = 5
SAFETY_WARNING_EXPOSURE_CAP = 0.80
SAFETY_HIGH_EXPOSURE_CAP = 0.50
SAFETY_CRISIS_EXPOSURE_CAP = 0.20
SAFETY_HARD_FREEZE_EXPOSURE_CAP = 0.0
SAFETY_STRUCTURAL_NEUTRAL_UNDERWATER = 0.08
SAFETY_STRUCTURAL_WEAK_UNDERWATER = 0.15
SAFETY_STRUCTURAL_BEAR_UNDERWATER = 0.25
SAFETY_STRUCTURAL_NEUTRAL_BUDGET = 0.85
SAFETY_STRUCTURAL_WEAK_BUDGET = 0.65
SAFETY_STRUCTURAL_BEAR_BUDGET = 0.45
SAFETY_SELL_FLOW_ALERT_RATIO = 0.02
GOVERNANCE_PLAN_HORIZON_DAYS = 5
GOVERNANCE_MIN_HOLDING_DAYS = 5
GOVERNANCE_SINGLE_WEIGHT_DRIFT = 0.02
GOVERNANCE_TOTAL_WEIGHT_DRIFT = 0.10
GOVERNANCE_MAX_POSITION_WEIGHT = 0.20
GOVERNANCE_MAX_PROTOTYPE_SECTOR_WEIGHT = 0.40
GOVERNANCE_REALLOCATION_ITERATIONS = 5
GOVERNANCE_REALLOCATION_MIN_WEIGHT = 0.001
GOVERNANCE_VOLATILITY_CAP_MULTIPLIER = 1.20
GOVERNANCE_LOCK_HAIRCUT_DAYS = 5
GOVERNANCE_LOCK_ALERT_DAYS = 10
GOVERNANCE_LOCK_HAIRCUT_RATIO = 1.0
GOVERNANCE_REWARD_DRAWDOWN_BUDGET = 0.05
GOVERNANCE_REWARD_TURNOVER_PENALTY = 0.50
GOVERNANCE_REWARD_DRAWDOWN_PENALTY = 3.0
GOVERNANCE_REPUTATION_WARMUP_DAYS = 60
GOVERNANCE_REPUTATION_HALF_LIFE = 20
GOVERNANCE_REPUTATION_UPDATE_DAYS = 5
GOVERNANCE_REPUTATION_SENSITIVITY = 1.5
GOVERNANCE_REPUTATION_MIN_WEIGHT = 0.25
GOVERNANCE_REPUTATION_MAX_WEIGHT = 4.0
GOVERNANCE_REPUTATION_MAX_STEP_RATIO = 0.05
GOVERNANCE_TRAIN_PURGE_PERIODS = 20
GOVERNANCE_TRAIN_EMBARGO_PERIODS = 5
GOVERNANCE_ENVIRONMENT_MANIFEST_JSON = REPORT_DIR / "decision_council_environment_manifest.json"
GOVERNANCE_OUTPUT_DIR = RESULT_DIR / "decision_council"
GOVERNANCE_INITIAL_CASH = 1_000_000.0
GOVERNANCE_ALPHA_MODEL_FEATURES = {
    "momentum_20": "ret_20",
    "mom_lowvol": "score_mom_lowvol",
    "ma_break": "close_to_ma20",
    "orderflow_amount_shock": "score_orderflow_amount_shock",
    "orderflow_close_drive": "score_orderflow_close_drive",
    "orderflow_accumulation": "score_orderflow_accumulation",
    "orderflow_efficiency": "score_orderflow_efficiency",
    "macd_trend": "score_macd_trend",
    "mean_reversion": "score_mean_reversion",
    "rsi_reversal": "score_rsi_reversal",
    "turtle_breakout": "score_turtle_breakout",
    "alpha_hedge": "score_alpha_hedge",
    "event_driven": "score_event_driven",
    "grid_trading": "score_grid_trading",
    "eod_close_strength": "score_eod_close_strength",
    "limit_up_follow": "score_limit_up_follow",
    "macd_cross": "score_macd_cross",
    "ma_cross": "score_ma_cross",
    "price_volume_breakout": "score_price_volume_breakout",
    "consecutive_decline_rebound": "score_consecutive_decline_rebound",
    "holiday_effect": "score_holiday_effect",
    "kdj_oversold_cross": "score_kdj_oversold_cross",
    "low_volume_pullback": "score_low_volume_pullback",
    "ml_alpha": "score_ml_alpha",
    # Fundamental factors
    "value": "score_value",
    "quality": "score_quality",
    "growth": "score_growth",
    "fundamental": "score_fundamental",
}
GOVERNANCE_ALPHA_MODELS = tuple(GOVERNANCE_ALPHA_MODEL_FEATURES)
GOVERNANCE_ALPHA_CANDIDATE_LIMIT = 200
GOVERNANCE_DEFAULT_TOP_N = 20
GOVERNANCE_ENTRY_RANK_LIMIT = 20
GOVERNANCE_HOLD_RANK_LIMIT = 100
GOVERNANCE_NORMAL_REBALANCE_INTERVAL_DAYS = 5
# Turnover budget - reduced to control trading costs.
# When MarketRegimePolicy is enabled:
# - Bull market: 4% turnover budget
# - Bear market: 2% turnover budget
GOVERNANCE_DEFAULT_TURNOVER_BUDGET = 0.03
GOVERNANCE_WEEKLY_TURNOVER_BUDGET = 0.15
GOVERNANCE_PARTIAL_ADJUSTMENT_RATE = 0.25
GOVERNANCE_INITIAL_TRANSITION_DAYS = 20
GOVERNANCE_ALLOWED_INSTRUMENT_TYPES = ("stock", "etf_fund")
GOVERNANCE_MIN_DAILY_AMOUNT = 1_000_000.0
GOVERNANCE_STALE_PRICE_HAIRCUT_DAYS = 5
GOVERNANCE_STALE_PRICE_HAIRCUT_RATIO = 0.10
GOVERNANCE_IMPACT_MODEL_VERSION = "daily_sqrt_participation_proxy_v1_uncalibrated"
GOVERNANCE_IMPACT_SQRT_COEFFICIENT = 0.001
GOVERNANCE_IMPACT_MAX_RATE = 0.02
GOVERNANCE_MIN_DAILY_HISTORY = 20
GOVERNANCE_START_DATE = "2021-01-01"
GOVERNANCE_END_DATE = "2024-12-31"
GOVERNANCE_PRELOAD_CALENDAR_DAYS = 60

# Market Regime Policy Configuration
# Enable dynamic parameter adjustment based on bull/bear market detection.
# When enabled, all strategy parameters (safety thresholds, Kelly sizing,
# signal filtering, turnover budget) will be dynamically adjusted.
ENABLE_MARKET_REGIME_POLICY = True
MARKET_REGIME_BENCHMARK_SYMBOL = "sh510300"  # CSI 300 ETF as benchmark
MARKET_REGIME_MA_PERIOD = 20
MARKET_REGIME_MA_SLOPE_LOOKBACK = 5
MARKET_REGIME_VOLATILITY_THRESHOLD = 0.025
MARKET_REGIME_MIN_HISTORY_DAYS = 30

# Buy signal quality filters (applied before scoring)
ENABLE_BUY_QUALITY_FILTERS = True
BUY_FILTER_MAX_VOLATILITY_MULTIPLIER = 1.5  # Exclude stocks with vol > 1.5x median
BUY_FILTER_MIN_AMOUNT_MULTIPLIER = 2.0  # Require 2x minimum daily amount
BUY_FILTER_MAX_DECLINE_20D = -0.05  # Exclude stocks with >5% decline in 20 days
BUY_FILTER_MIN_RET_5D = -0.03  # Exclude stocks with >3% decline in 5 days

# Governance entry confirmation and exposure catch-up. These controls address
# cash drag without allowing low-quality candidates to absorb catch-up buys.
ENABLE_GOVERNANCE_ENTRY_CONFIRMATION = True
GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BULL = 0.75
GOVERNANCE_ENTRY_ALPHA_THRESHOLD_NEUTRAL = 0.80
GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WEAK = 0.85
GOVERNANCE_ENTRY_ALPHA_THRESHOLD_BEAR = 0.85
GOVERNANCE_ENTRY_ALPHA_THRESHOLD_WARNING = 0.90
GOVERNANCE_ENTRY_MIN_ORDERFLOW_CONFIRMATIONS = 2
GOVERNANCE_ENTRY_MIN_EXPECTED_RETURN_AFTER_COST = 0.003
GOVERNANCE_ENTRY_MIN_CONFIDENCE = 0.30
GOVERNANCE_ENTRY_MIN_AMOUNT_MA_RATIO = 0.80
GOVERNANCE_ENTRY_MAX_VOLATILITY_MULTIPLIER = 1.75
GOVERNANCE_ENTRY_MIN_CLOSE_TO_MA20 = -0.08
GOVERNANCE_ENTRY_MIN_RET_20 = -0.08

ENABLE_GOVERNANCE_EXPOSURE_CATCHUP = True
GOVERNANCE_CATCHUP_GAP_TRIGGER = 0.10
GOVERNANCE_CATCHUP_MIN_ENTRY_COUNT = 8
GOVERNANCE_CATCHUP_MAX_LIQUIDITY_STRESS = 0.20
GOVERNANCE_CATCHUP_RATE_NORMAL_BULL = 0.45
GOVERNANCE_CATCHUP_RATE_NORMAL_NEUTRAL = 0.35
GOVERNANCE_CATCHUP_RATE_NORMAL_WEAK = 0.25
GOVERNANCE_CATCHUP_RATE_NORMAL_BEAR = 0.20
GOVERNANCE_CATCHUP_RATE_WARNING = 0.10
GOVERNANCE_CATCHUP_EXTRA_BUDGET_NORMAL = 0.02
GOVERNANCE_CATCHUP_EXTRA_BUDGET_WARNING = 0.01
GOVERNANCE_CATCHUP_MAX_BUDGET = 0.05
# Research gate for allowing active exposure catch-up / high-exposure behavior.
# These thresholds are intentionally conservative and auditable:
# - profit factor is primary because recent diagnostics showed high win-rate can
#   still lose money when average losses dominate average wins.
# - closed trade count avoids amplifying noise from a tiny sample.
# - actual/target tracking is a ramp factor rather than a hard block.
GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES = 100
GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR = 1.20
GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO = 1.25
GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE = 0.45
GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION = 0.35
GOVERNANCE_HIGH_EXPOSURE_MIN_ACTUAL_TARGET_RATIO = 0.60
GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL = 0.0

# Position-management P0 contract defaults. These values define the first
# conservative Kelly implementation and are intentionally explicit because the
# decision matrix uses them as audited thresholds.
# When MarketRegimePolicy is enabled, these are dynamically adjusted:
# - Bull market: kelly_scale=0.45, min_p_win=0.50
# - Bear market: kelly_scale=0.35, min_p_win=0.55
POSITION_KELLY_SCALE = 0.40
POSITION_MIN_ENTRY_KELLY_SCORE = 0.02
POSITION_HOLD_KELLY_SCORE = 0.03
POSITION_SEVERE_EXIT_KELLY_SCORE = 0.015
POSITION_MIN_P_WIN = 0.52
POSITION_EXIT_EXPECTED_RETURN_20D = -0.005
POSITION_EXIT_HYSTERESIS_DAYS = 3
POSITION_KELLY_DECLINE_DAYS = 5
POSITION_KELLY_DECLINE_RATIO = 0.50
POSITION_RISK_DISCOUNT_SMOOTH_DAYS = 5
POSITION_EMERGENCY_SINGLE_DAY_DRAWDOWN = 0.07
POSITION_A500_MIN_COVERAGE_RATIO = 0.80
POSITION_DEFAULT_RETURN_HORIZON_DAYS = 20
POSITION_REQUIRE_INDEX_CONSTITUENTS = True

# Universe mode definitions - explicit, auditable, no silent fallback
UNIVERSE_MODE_INDEX_POOL_STRICT = "index_pool_strict"
UNIVERSE_MODE_QUALITY_FALLBACK = "quality_fallback"
UNIVERSE_MODE_BLOCKED = "blocked"

# When True: if constituents missing + strict required -> raise error
# When False: allow quality_fallback mode
POSITION_ALLOW_QUALITY_FALLBACK = False

POSITION_STRATEGY_STATS_LOOKBACK_DAYS = 252
POSITION_STRATEGY_STATS_MIN_SAMPLES = 20
POSITION_BAYES_PRIOR_P = 0.50
POSITION_BAYES_PRIOR_STRENGTH = 20.0
POSITION_BAYES_LOWER_CONFIDENCE = 0.85
POSITION_BAYES_PRIOR_SOURCE = "global_neutral_baseline"
POSITION_BAYES_PRIOR_NOTE = "Neutral 50/50 baseline with pseudo-count strength for cold-start stabilization; review via sensitivity report before changing live research conclusions."
POSITION_PAYOFF_TRIM_RATIO = 0.10
POSITION_PAYOFF_MIN = 1.0
POSITION_PAYOFF_MAX = 3.0
POSITION_SINGLE_STOCK_CAP = 0.05
POSITION_INDUSTRY_CAP = 0.20
POSITION_STRATEGY_GROUP_CAP = 0.35
POSITION_CONFLICT_REDUCE_THRESHOLD = 0.30
POSITION_CONFLICT_BLOCK_THRESHOLD = 0.50
POSITION_CONFLICT_EXIT_THRESHOLD = 0.60
POSITION_MIN_REBALANCE_DAYS = 3
POSITION_NEW_CONSTITUENT_WAIT_DAYS = 5
POSITION_LIQUIDITY_ALERT_DAYS = 3
POSITION_LIQUIDITY_ADV_QUANTILE = 0.05
POSITION_LIQUIDITY_AMIHUD_QUANTILE = 0.95
POSITION_PORTFOLIO_LIQUIDITY_ALERT_RATIO = 0.20
KELLY_PRIOR_SENSITIVITY_CSV = REPORT_DIR / "kelly_prior_sensitivity.csv"
KELLY_PRIOR_SENSITIVITY_MD = REPORT_DIR / "kelly_prior_sensitivity.md"

# V6 strategy governance. Only the formal candidates can receive non-zero
# admission weights. Observation strategies remain available for diagnostics.
V6_FORMAL_STRATEGY_CANDIDATES = (
    "macd_cross",
    "rsi_reversal",
    "low_volume_pullback",
    "limit_up_follow",
)
V6_OBSERVATION_STRATEGIES = (
    "ma_cross",
    "kdj_oversold_cross",
    "mean_reversion",
    "consecutive_decline_rebound",
    "price_volume_breakout",
    "turtle_breakout",
    "eod_close_strength",
    "holiday_effect",
    "grid_trading",
    "alpha_hedge",
    "event_driven",
)
V6_STRATEGY_GROUPS = {
    "macd_cross": "trend",
    "rsi_reversal": "reversal",
    "low_volume_pullback": "price_volume",
    "limit_up_follow": "event",
}
V6_STRATEGY_COOLDOWN_DAYS = {
    "macd_cross": 5,
    "rsi_reversal": 3,
    "low_volume_pullback": 3,
    "limit_up_follow": 0,
}
V6_STRATEGY_TARGET_HORIZONS = {
    "macd_cross": 10,
    "rsi_reversal": 5,
    "low_volume_pullback": 5,
    "limit_up_follow": 2,
}
V6_EVENT_DENSITY_WARNING_PER_YEAR = 50
V6_PRIMARY_BENCHMARK = "CSI300_TOTAL_RETURN"
V6_ML_INITIAL_WEIGHT = 0.10
V6_ML_MAX_WEIGHT = 0.30
V6_ML_WEIGHT_STEP = 0.05
V6_ML_BRIER_IMPROVEMENT_REQUIRED = 0.10
V6_ML_REQUIRED_CONSECUTIVE_WINDOWS = 2
V6_LIQUIDITY_PARTICIPATION_RATE = 0.02
V6_LIQUIDITY_STRESS_RATES = (0.01, 0.02, 0.05, 0.10)
V6_RESEARCH_WATERMARK = "基于未完全验证数据，禁止引用为实盘期望收益"

# P2-P7 industrial governance contracts. All stages run serially to keep
# memory bounded on a research workstation.
GOVERNANCE_INDUSTRIAL_DIR = RESULT_DIR / "decision_council_industrial"
GOVERNANCE_MODEL_REGISTRY_JSON = GOVERNANCE_INDUSTRIAL_DIR / "model_registry.json"
GOVERNANCE_INDUSTRIAL_MANIFEST_JSON = GOVERNANCE_INDUSTRIAL_DIR / "industrial_manifest.json"
GOVERNANCE_PHASE_GATE_CSV = GOVERNANCE_INDUSTRIAL_DIR / "phase_gate_report.csv"
GOVERNANCE_MODEL_CONGRESS_CSV = GOVERNANCE_INDUSTRIAL_DIR / "model_congress_catalog.csv"
GOVERNANCE_SAFETY_DAILY_CSV = GOVERNANCE_INDUSTRIAL_DIR / "safety_daily_dataset.csv"
GOVERNANCE_SAFETY_MODEL_JSON = GOVERNANCE_INDUSTRIAL_DIR / "safety_model.json"
GOVERNANCE_SAFETY_CALIBRATION_CSV = GOVERNANCE_INDUSTRIAL_DIR / "safety_calibration.csv"
GOVERNANCE_SAFETY_EVALUATION_CSV = GOVERNANCE_INDUSTRIAL_DIR / "safety_evaluation.csv"
GOVERNANCE_BANDIT_ACTIONS_CSV = GOVERNANCE_INDUSTRIAL_DIR / "bandit_action_contract.csv"
GOVERNANCE_MONITORING_POLICY_JSON = GOVERNANCE_INDUSTRIAL_DIR / "monitoring_rollback_policy.json"
GOVERNANCE_TRANSITION_PROTOCOL_JSON = GOVERNANCE_INDUSTRIAL_DIR / "initial_portfolio_transition_protocol.json"
GOVERNANCE_RESEARCH_REFERENCES_CSV = GOVERNANCE_INDUSTRIAL_DIR / "research_references.csv"
GOVERNANCE_STREAM_BATCH_SIZE = 50_000
GOVERNANCE_SAFETY_TRAIN_RATIO = 0.60
GOVERNANCE_SAFETY_VALIDATION_RATIO = 0.20
GOVERNANCE_SAFETY_MAX_ITERATIONS = 600
GOVERNANCE_SAFETY_LEARNING_RATE = 0.05
GOVERNANCE_SAFETY_L2 = 0.01
GOVERNANCE_MOMENTUM_REBOUND_DRAWDOWN = -0.08
GOVERNANCE_MOMENTUM_REBOUND_RETURN = 0.03
GOVERNANCE_BANDIT_ACTION_BOUND_RATIO = 0.20
GOVERNANCE_BANDIT_SHADOW_DAYS = 252
GOVERNANCE_SUMMARY_CSV = GOVERNANCE_OUTPUT_DIR / "governance_strategy_summary.csv"
GOVERNANCE_REPORT_MD = GOVERNANCE_OUTPUT_DIR / "governance_strategy_report.md"

# Registry Framework Configuration
# 4-layer extensible architecture: Universe, Alpha, Policy, Evaluation
REGISTRY_FRAMEWORK_VERSION = "v1.0"
REGISTRY_OUTPUT_DIR = RESULT_DIR / "registry"
REGISTRY_VALIDATION_REPORT_CSV = REPORT_DIR / "registry_validation_report.csv"
REGISTRY_COMPARISON_REPORT_CSV = REPORT_DIR / "registry_comparison_report.csv"

# Default registry selections (can be overridden by CLI or experiment plan)
DEFAULT_UNIVERSE_NAME = "hs300_csi500_a500_strict"
DEFAULT_ALPHA_BUNDLE = "president_core_bundle"
DEFAULT_GOVERNANCE_VARIANT = "rules_based_president"

# Experiment output structure: results/governance/{universe}/{variant}/{bundle}/
GOVERNANCE_EXPERIMENT_BASE_DIR = RESULT_DIR / "governance"


def get_parameter(name: str):
    """Return one centralized parameter for debugging or external interfaces."""
    key = str(name).strip().upper()
    if key not in globals() or key.startswith("_"):
        raise KeyError(f"Unknown configuration parameter: {name}")
    return globals()[key]


def parameter_snapshot(*, include_paths: bool = True) -> dict:
    """Return a JSON-serializable snapshot of all public configuration values."""
    snapshot = {}
    for name, value in sorted(globals().items()):
        if not name.isupper() or name.startswith("_"):
            continue
        if not include_paths and isinstance(value, Path):
            continue
        snapshot[name] = _serialize_parameter(value)
    return snapshot


def validate_configuration() -> list[str]:
    """Validate cross-parameter contracts before a pipeline starts."""
    errors = []
    try:
        start = None if START_DATE is None else __import__("pandas").Timestamp(START_DATE)
        end = None if END_DATE is None else __import__("pandas").Timestamp(END_DATE)
        strategy_start = None if STRATEGY_START_DATE is None else __import__("pandas").Timestamp(STRATEGY_START_DATE)
        strategy_end = None if STRATEGY_END_DATE is None else __import__("pandas").Timestamp(STRATEGY_END_DATE)
    except Exception as exc:
        errors.append(f"date parsing failed: {exc}")
        return errors
    if start is not None and end is not None and start > end:
        errors.append("START_DATE must not be after END_DATE")
    if strategy_start is not None and strategy_end is not None and strategy_start > strategy_end:
        errors.append("STRATEGY_START_DATE must not be after STRATEGY_END_DATE")
    if start is not None and strategy_start is not None and strategy_start < start:
        errors.append("STRATEGY_START_DATE must not be before START_DATE")
    if STRATEGY_TOP_N <= 0:
        errors.append("STRATEGY_TOP_N must be positive")
    if STRATEGY_BATCH_SIZE_DEFAULT <= 0:
        errors.append("STRATEGY_BATCH_SIZE_DEFAULT must be positive")
    if MAIN_STRATEGY_EXECUTION_MODE not in {"auto", "bounded"}:
        errors.append("MAIN_STRATEGY_EXECUTION_MODE must be 'auto' or 'bounded'")
    if float(MAIN_STRATEGY_BOUNDED_PARQUET_GB_THRESHOLD) <= 0:
        errors.append("MAIN_STRATEGY_BOUNDED_PARQUET_GB_THRESHOLD must be positive")
    if not 1 <= AUTO_COMPLETE_MAX_STRATEGY_WORKERS <= 2:
        errors.append("AUTO_COMPLETE_MAX_STRATEGY_WORKERS must be between 1 and 2")
    if POSITION_PAYOFF_MIN <= 0 or POSITION_PAYOFF_MAX < POSITION_PAYOFF_MIN:
        errors.append("POSITION_PAYOFF_MIN/MAX are invalid")
    for name in [
        "COMMISSION_RATE",
        "STAMP_DUTY_RATE",
        "SLIPPAGE_RATE",
        "TRANSFER_FEE_RATE",
        "POSITION_KELLY_SCALE",
        "POSITION_SINGLE_STOCK_CAP",
        "POSITION_INDUSTRY_CAP",
        "V6_LIQUIDITY_PARTICIPATION_RATE",
    ]:
        value = float(globals()[name])
        if value < 0:
            errors.append(f"{name} must not be negative")
    if float(REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN) < 0:
        errors.append("REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN must not be negative")
    if float(REPORT_TOP5_WEIGHT_SUM_GAP_WARN) < 0:
        errors.append("REPORT_TOP5_WEIGHT_SUM_GAP_WARN must not be negative")
    if float(FEATURE_PARQUET_GB_WARN) <= 0:
        errors.append("FEATURE_PARQUET_GB_WARN must be positive")
    if int(FEATURE_COLUMN_COUNT_WARN) <= 0:
        errors.append("FEATURE_COLUMN_COUNT_WARN must be positive")
    if FEATURE_STORAGE_MODE not in {"full", "pruned"}:
        errors.append("FEATURE_STORAGE_MODE must be 'full' or 'pruned'")
    if int(MULTI_WINDOW_DEFAULT_MONTHS) <= 0:
        errors.append("MULTI_WINDOW_DEFAULT_MONTHS must be positive")
    if int(MULTI_WINDOW_DEFAULT_STEP_MONTHS) <= 0:
        errors.append("MULTI_WINDOW_DEFAULT_STEP_MONTHS must be positive")
    if errors:
        return errors
    return []


def assert_valid_configuration() -> None:
    errors = validate_configuration()
    if errors:
        raise ValueError("Invalid centralized configuration:\n- " + "\n- ".join(errors))


def _serialize_parameter(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_serialize_parameter(item) for item in value]
    if isinstance(value, list):
        return [_serialize_parameter(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_parameter(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
