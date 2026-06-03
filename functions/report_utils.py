# -*- coding: utf-8 -*-
from config import (
    TDX_DIR, PROJECT_DIR, RAW_DAILY_PARQUET, CLEAN_DAILY_PARQUET,
    FEATURE_DAILY_PARQUET, READ_LIMIT, START_DATE, END_DATE,
    INCLUDE_INSTRUMENT_TYPES
)
from functions.governance import build_research_status, print_runtime_disclosure

def print_project_status():
    research_status = build_research_status()
    print("========== Project Status ==========")
    print("TDX_DIR:", TDX_DIR)
    print("PROJECT_DIR:", PROJECT_DIR)
    print("READ_LIMIT:", READ_LIMIT)
    print("START_DATE:", START_DATE)
    print("END_DATE:", END_DATE)
    print("INCLUDE_INSTRUMENT_TYPES:", INCLUDE_INSTRUMENT_TYPES)
    print("RAW_DAILY_PARQUET:", RAW_DAILY_PARQUET)
    print("CLEAN_DAILY_PARQUET:", CLEAN_DAILY_PARQUET)
    print("FEATURE_DAILY_PARQUET:", FEATURE_DAILY_PARQUET)
    print("RESEARCH_MODE:", research_status.research_mode)
    print("FORMAL_STATUS:", research_status.formal_status)
    print("FORMAL_ELIGIBLE:", research_status.formal_eligible)
    print("====================================")
