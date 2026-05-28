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
from pathlib import Path

TDX_DIR = Path(r"F:\tongxinda")
PROJECT_DIR = Path(r"F:\通信达量化\tdx_modular_quant_project_v2_all_instruments")

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
FACTOR_REGISTRY_STATUS_DEFAULT = "experimental"
REPORT_OUTPUT_MD = RESULT_DIR / "strategy_diagnostic_report.md"
FEATURE_COVERAGE_REPORT_CSV = REPORT_DIR / "feature_coverage_report.csv"
FEATURE_DISTRIBUTION_REPORT_CSV = REPORT_DIR / "feature_distribution_report.csv"
FEATURE_STABILITY_REPORT_CSV = REPORT_DIR / "feature_stability_report.csv"
FEATURE_REGISTRY_REPORT_CSV = REPORT_DIR / "feature_registry_validation_report.csv"
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
ENABLE_T_PLUS_ONE = True
ENABLE_PRICE_LIMIT_CHECK = True
ENABLE_SUSPENSION_CHECK = True
MAX_LIQUIDITY_LOCK_DAYS = 10
LIQUIDITY_LOCK_REPORT_CSV = RESULT_DIR / "extreme_liquidity_lock_report.csv"
ORDER_LEDGER_PREFIX = "backtest_orders"
BACKTEST_SUMMARY_V2_CSV = RESULT_DIR / "backtest_strategy_summary_v2.csv"
STRATEGY_RANK_SHIFT_REPORT_CSV = RESULT_DIR / "strategy_rank_shift_report.csv"

RAW_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_raw.parquet"
CLEAN_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_clean.parquet"
FEATURE_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_features.parquet"

FAILED_CODES_CSV = REPORT_DIR / "failed_codes.csv"
STOCK_INFO_CSV = REPORT_DIR / "instrument_info.csv"
ABNORMAL_RETURN_CSV = REPORT_DIR / "abnormal_return_rows.csv"
DATA_QUALITY_SUMMARY_CSV = REPORT_DIR / "data_quality_summary.csv"
