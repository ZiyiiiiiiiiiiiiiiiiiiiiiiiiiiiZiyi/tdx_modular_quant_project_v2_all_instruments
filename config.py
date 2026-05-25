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
PROCESSED_DIR = DATA_DIR / "processed"
REPORT_DIR = DATA_DIR / "reports"
RESULT_DIR = PROJECT_DIR / "results"
PIPELINE_CACHE_JSON = REPORT_DIR / "pipeline_run_cache.json"

for folder in [DATA_DIR, PROCESSED_DIR, REPORT_DIR, RESULT_DIR]:
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

HOT_THEME_SLOT_RATIO = 0.3
HOT_THEME_WEIGHTS = {
    "ai_infrastructure": 1.00,
    "robotics_automation": 0.90,
    "low_altitude_aerospace": 0.80,
}

RAW_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_raw.parquet"
CLEAN_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_clean.parquet"
FEATURE_DAILY_PARQUET = PROCESSED_DIR / "tdx_daily_features.parquet"

FAILED_CODES_CSV = REPORT_DIR / "failed_codes.csv"
STOCK_INFO_CSV = REPORT_DIR / "instrument_info.csv"
ABNORMAL_RETURN_CSV = REPORT_DIR / "abnormal_return_rows.csv"
DATA_QUALITY_SUMMARY_CSV = REPORT_DIR / "data_quality_summary.csv"
