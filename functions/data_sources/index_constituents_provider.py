"""Index constituent providers for HS300, CSI500, and CSI A500 pools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from functions.investable_universe import (
    INDEX_CONSTITUENTS_PARQUET,
    TARGET_INDEX_POOLS,
    normalize_index_constituents,
)


@dataclass(frozen=True)
class IndexConstituentFetchResult:
    data: pd.DataFrame
    errors: pd.DataFrame


def fetch_current_csindex_constituents_with_akshare(index_codes=None, *, asof_date=None) -> IndexConstituentFetchResult:
    """Fetch current CSI index constituents through AKShare's csindex adapter.

    This produces a point-in-time snapshot from `asof_date` forward. It must not
    be used to backfill historical membership before that date.
    """
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "AKShare is not installed in this interpreter. Install akshare or run this script "
            "with the stock_ai environment that contains akshare."
        ) from exc

    asof = pd.Timestamp(asof_date or pd.Timestamp.today().normalize())
    codes = [str(code).zfill(6) for code in (index_codes or [v["index_code"] for v in TARGET_INDEX_POOLS.values()])]
    frames = []
    errors = []
    for code in codes:
        try:
            raw = ak.index_stock_cons_csindex(symbol=code)
            if raw is None or raw.empty:
                errors.append({"index_code": code, "status": "empty_result"})
                continue
            frames.append(_normalize_akshare_csindex_frame(raw, code, asof))
        except Exception as exc:  # provider errors should be reported per index
            errors.append({"index_code": code, "status": str(exc)})
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return IndexConstituentFetchResult(data=data, errors=pd.DataFrame(errors))


def merge_constituent_snapshot(existing: pd.DataFrame, snapshot: pd.DataFrame, *, asof_date=None) -> pd.DataFrame:
    """Append a current snapshot without rewriting prior point-in-time records."""
    if snapshot.empty:
        return existing.copy()
    asof = pd.Timestamp(asof_date or snapshot["asof_date"].dropna().max())
    old = existing.copy() if existing is not None and not existing.empty else pd.DataFrame(columns=snapshot.columns)
    normalized_snapshot = normalize_index_constituents(snapshot, source="akshare_csindex_snapshot")
    if old.empty:
        return normalized_snapshot
    old = normalize_index_constituents(old, source="existing_index_constituents")
    # Close old active memberships that disappear from the new snapshot.
    active_old = old[old["out_date"].isna()].copy()
    new_keys = set(zip(normalized_snapshot["index_code"], normalized_snapshot["symbol"]))
    close_mask = old["out_date"].isna() & pd.Series([
        (idx_code, symbol) not in new_keys
        for idx_code, symbol in zip(old["index_code"], old["symbol"])
    ], index=old.index)
    old.loc[close_mask, "out_date"] = asof
    old_keys = set(zip(active_old["index_code"], active_old["symbol"]))
    additions = normalized_snapshot[
        pd.Series(
            [
            (idx_code, symbol) not in old_keys
            for idx_code, symbol in zip(normalized_snapshot["index_code"], normalized_snapshot["symbol"])
            ],
            index=normalized_snapshot.index,
        )
    ]
    merged = pd.concat([old, additions], ignore_index=True)
    return merged.drop_duplicates().sort_values(["index_code", "symbol", "first_trade_date"])


def save_index_constituents(frame: pd.DataFrame, path: Path = INDEX_CONSTITUENTS_PARQUET) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_index_constituents(frame).to_parquet(path, index=False)
    return path


def _normalize_akshare_csindex_frame(raw: pd.DataFrame, index_code: str, asof: pd.Timestamp) -> pd.DataFrame:
    data = raw.copy()
    code_col = next((col for col in ["成分券代码", "证券代码", "品种代码"] if col in data.columns), None)
    if code_col is None:
        raise ValueError(f"Cannot find constituent code column in AKShare result columns: {data.columns.tolist()}")
    index_name = TARGET_INDEX_POOLS.get(_pool_id_for_code(index_code), {}).get("index_name", str(index_code))
    exchange_col = next((col for col in ["交易所", "交易所英文名称"] if col in data.columns), None)
    symbols = [_to_tdx_symbol(code, exchange=data.get(exchange_col, pd.Series(index=data.index)).iloc[i] if exchange_col else None) for i, code in enumerate(data[code_col])]
    result = pd.DataFrame(
        {
            "index_code": str(index_code).zfill(6),
            "index_name": data.get("指数名称", pd.Series(index_name, index=data.index)).fillna(index_name),
            "symbol": symbols,
            "announcement_date": asof,
            "effective_after_close_date": asof,
            "first_trade_date": asof,
            "in_date": asof,
            "out_date": pd.NaT,
            "source": "akshare.index_stock_cons_csindex",
            "asof_date": asof,
        }
    )
    return normalize_index_constituents(result, source="akshare.index_stock_cons_csindex")


def _to_tdx_symbol(code, exchange=None) -> str:
    value = str(code).strip().lower().replace(".", "")
    digits = "".join(ch for ch in value if ch.isdigit())[-6:].zfill(6)
    exchange_text = str(exchange or "").lower()
    if "深圳" in exchange_text or "shenzhen" in exchange_text or digits.startswith(("0", "1", "2", "3")):
        return f"sz{digits}"
    return f"sh{digits}"


def _pool_id_for_code(index_code: str) -> str | None:
    for pool_id, spec in TARGET_INDEX_POOLS.items():
        if spec["index_code"] == str(index_code).zfill(6):
            return pool_id
    return None
