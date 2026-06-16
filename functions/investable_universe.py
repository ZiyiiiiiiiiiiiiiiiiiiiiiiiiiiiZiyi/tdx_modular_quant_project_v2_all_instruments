"""Point-in-time investable universe helpers for index-based stock pools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from config import PROCESSED_DIR, REPORT_DIR
from functions.decision_council.position_management import evaluate_index_constituent_coverage


INDEX_CONSTITUENTS_PARQUET = PROCESSED_DIR / "index_constituents.parquet"
INDEX_UNIVERSE_QUALITY_CSV = REPORT_DIR / "index_universe_quality_report.csv"

TARGET_INDEX_POOLS = {
    "hs300": {"index_code": "000300", "index_name": "沪深300"},
    "csi500": {"index_code": "000905", "index_name": "中证500"},
    "csi_a500": {"index_code": "000510", "index_name": "中证A500"},
}

# Universe mode constants
UNIVERSE_MODE_INDEX_POOL_STRICT = "index_pool_strict"
UNIVERSE_MODE_QUALITY_FALLBACK = "quality_fallback"
UNIVERSE_MODE_BLOCKED = "blocked"


@dataclass(frozen=True)
class UniverseFilterConfig:
    min_history_days: int = 120
    min_avg_amount_20: float = 10_000_000.0
    max_amihud_20: float = 5e-8
    abnormal_return_threshold: float = 0.11
    require_adjustment: bool = False


def normalize_index_constituents(raw: pd.DataFrame, *, source: str = "manual_or_provider") -> pd.DataFrame:
    """Normalize point-in-time index constituent records.

    Expected input may use either `first_trade_date` directly, or
    `effective_after_close_date`, in which case first trade date is the next
    business day. Static current constituents are accepted only for research
    smoke tests and should carry a source disclosure.
    """
    data = raw.copy()
    rename_map = {
        "证券代码": "symbol",
        "指数代码": "index_code",
        "指数名称": "index_name",
        "公告日期": "announcement_date",
        "生效收盘日": "effective_after_close_date",
        "首个交易日": "first_trade_date",
        "调入日期": "in_date",
        "调出日期": "out_date",
    }
    data = data.rename(columns={k: v for k, v in rename_map.items() if k in data.columns})
    required = {"index_code", "symbol"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"index constituents missing required columns: {missing}")
    for column in ["announcement_date", "effective_after_close_date", "first_trade_date", "in_date", "out_date", "asof_date"]:
        if column not in data.columns:
            data[column] = pd.NaT
        data[column] = pd.to_datetime(data[column], errors="coerce")
    if "index_name" not in data.columns:
        data["index_name"] = data["index_code"].map(
            {v["index_code"]: v["index_name"] for v in TARGET_INDEX_POOLS.values()}
        ).fillna(data["index_code"])
    missing_first = data["first_trade_date"].isna() & data["effective_after_close_date"].notna()
    data.loc[missing_first, "first_trade_date"] = data.loc[missing_first, "effective_after_close_date"] + pd.offsets.BDay(1)
    data["first_trade_date"] = data["first_trade_date"].fillna(data["in_date"])
    data["asof_date"] = data["asof_date"].fillna(pd.Timestamp.today().normalize())
    data["source"] = data.get("source", source)
    data["symbol"] = data["symbol"].map(_normalize_a_share_symbol)
    data["index_code"] = data["index_code"].astype(str).str.zfill(6)
    columns = [
        "index_code",
        "index_name",
        "symbol",
        "announcement_date",
        "effective_after_close_date",
        "first_trade_date",
        "in_date",
        "out_date",
        "source",
        "asof_date",
    ]
    return data[columns].drop_duplicates().sort_values(["index_code", "symbol", "first_trade_date"])


def active_index_members(constituents: pd.DataFrame, *, as_of_date, index_codes=None) -> pd.DataFrame:
    date = pd.Timestamp(as_of_date)
    data = normalize_index_constituents(constituents) if not _has_normalized_columns(constituents) else constituents.copy()
    if index_codes is not None:
        wanted = {str(code).zfill(6) for code in index_codes}
        data = data[data["index_code"].astype(str).str.zfill(6).isin(wanted)]
    data["first_trade_date"] = pd.to_datetime(data["first_trade_date"], errors="coerce")
    data["out_date"] = pd.to_datetime(data["out_date"], errors="coerce").fillna(pd.Timestamp.max.normalize())
    return data[(data["first_trade_date"] <= date) & (data["out_date"] > date)].copy()


def attach_index_pool_flags(features: pd.DataFrame, constituents: pd.DataFrame) -> pd.DataFrame:
    data = features.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    result_parts = []
    index_codes = [item["index_code"] for item in TARGET_INDEX_POOLS.values()]
    for date, one_day in data.groupby("date", sort=True):
        active = active_index_members(constituents, as_of_date=date, index_codes=index_codes)
        pool_map = active.groupby("symbol")["index_code"].apply(lambda s: ",".join(sorted(set(s)))).to_dict()
        frame = one_day.copy()
        frame["index_pool_codes"] = frame["symbol"].astype(str).map(pool_map).fillna("")
        frame["in_target_index_pool"] = frame["index_pool_codes"] != ""
        frame["universe_mode"] = UNIVERSE_MODE_INDEX_POOL_STRICT
        frame["constituent_data_status"] = "available"
        result_parts.append(frame)
    return pd.concat(result_parts, ignore_index=True) if result_parts else data


def filter_investable_universe(
    features: pd.DataFrame,
    constituents: pd.DataFrame | None = None,
    *,
    config: UniverseFilterConfig | None = None,
    require_constituents: bool = True,
    allow_fallback: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Apply the required 沪深300/中证500/中证A500 stock-pool filters.

    Returns
    -------
    tuple[pd.DataFrame, str]
        (filtered_data, universe_mode)
        universe_mode is one of: "index_pool_strict", "quality_fallback", "blocked"
    """
    cfg = config or UniverseFilterConfig()
    data = features.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.sort_values(["symbol", "date"]).copy()

    # Determine universe mode
    has_constituents = constituents is not None and not constituents.empty

    if has_constituents:
        # Strict index pool mode
        universe_mode = UNIVERSE_MODE_INDEX_POOL_STRICT
        data = attach_index_pool_flags(data, constituents)
        data = data[data["in_target_index_pool"]]
    elif require_constituents and not allow_fallback:
        # Blocked: constituents required but missing
        raise ValueError(
            "Index constituents are required (strict mode) but unavailable. "
            "Build data/processed/index_constituents.parquet first."
        )
    elif allow_fallback:
        # Quality fallback mode
        universe_mode = UNIVERSE_MODE_QUALITY_FALLBACK
        data["universe_mode"] = UNIVERSE_MODE_QUALITY_FALLBACK
        data["constituent_data_status"] = "missing"
        data["in_target_index_pool"] = pd.NA  # Not applicable in fallback mode
        data["index_pool_codes"] = ""
    else:
        universe_mode = UNIVERSE_MODE_BLOCKED
        return pd.DataFrame(), universe_mode

    if "instrument_type" in data.columns:
        data = data[data["instrument_type"] == "stock"]
    for column, required_value in [("is_st", False), ("is_delisting", False), ("is_trading", True)]:
        if column in data.columns:
            data = data[data[column] == required_value]
    if "rough_limit_up" in data.columns:
        data = data[data["rough_limit_up"] == False]
    if "rough_limit_down" in data.columns:
        data = data[data["rough_limit_down"] == False]
    if cfg.require_adjustment and "formal_price_eligible" in data.columns:
        data = data[data["formal_price_eligible"] == True]
    grouped = data.groupby("symbol", group_keys=False)
    data["history_days"] = grouped.cumcount() + 1
    amount_col = "amount" if "amount" in data.columns else None
    if amount_col:
        data["avg_amount_20"] = grouped[amount_col].transform(lambda s: pd.to_numeric(s, errors="coerce").rolling(20, min_periods=5).mean())
    else:
        data["avg_amount_20"] = np.nan
    close_col = "close_nominal" if "close_nominal" in data.columns else "close"
    ret = grouped[close_col].pct_change(fill_method=None)
    amount = pd.to_numeric(data.get("amount", pd.Series(np.nan, index=data.index)), errors="coerce")
    data["amihud_20"] = (ret.abs() / amount.replace(0.0, np.nan)).groupby(data["symbol"]).transform(
        lambda s: s.rolling(20, min_periods=5).mean()
    )
    if "raw_ret" in data.columns:
        data = data[pd.to_numeric(data["raw_ret"], errors="coerce").abs().fillna(0.0) <= cfg.abnormal_return_threshold]
    data = data[data["history_days"] >= cfg.min_history_days]
    data = data[pd.to_numeric(data["avg_amount_20"], errors="coerce").fillna(0.0) >= cfg.min_avg_amount_20]
    data = data[pd.to_numeric(data["amihud_20"], errors="coerce").fillna(0.0) <= cfg.max_amihud_20]
    return data, universe_mode


def build_index_universe_quality_report(constituents: pd.DataFrame, *, start_date, end_date) -> pd.DataFrame:
    rows = []
    normalized = normalize_index_constituents(constituents) if not _has_normalized_columns(constituents) else constituents
    for pool_id, spec in TARGET_INDEX_POOLS.items():
        report = evaluate_index_constituent_coverage(
            normalized,
            index_code=spec["index_code"],
            start_date=start_date,
            end_date=end_date,
        )
        rows.append({"pool_id": pool_id, "index_name": spec["index_name"], **report})
    return pd.DataFrame(rows)


def load_index_constituents(path: Path = INDEX_CONSTITUENTS_PARQUET) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(
            columns=[
                "index_code",
                "index_name",
                "symbol",
                "announcement_date",
                "effective_after_close_date",
                "first_trade_date",
                "in_date",
                "out_date",
                "source",
                "asof_date",
            ]
        )
    return pd.read_parquet(path)


def save_index_universe_quality_report(report: pd.DataFrame, output_path=INDEX_UNIVERSE_QUALITY_CSV):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False, encoding="utf-8-sig")
    return Path(output_path)


def _has_normalized_columns(frame: pd.DataFrame) -> bool:
    return {"index_code", "symbol", "first_trade_date", "out_date"}.issubset(frame.columns)


def _normalize_a_share_symbol(value) -> str:
    raw = str(value).strip().lower()
    compact = raw.replace(".", "")
    if len(compact) == 8 and compact[:2] in {"sh", "sz", "bj"}:
        return compact
    if len(compact) == 8 and compact[-2:] in {"sh", "sz", "bj"}:
        return compact[-2:] + compact[:6]
    digits = "".join(character for character in compact if character.isdigit())
    code = digits[-6:].zfill(6)
    if code.startswith(("4", "8")):
        market = "bj"
    elif code.startswith(("0", "2", "3")):
        market = "sz"
    else:
        market = "sh"
    return market + code
