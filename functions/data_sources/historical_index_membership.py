"""Research PIT index-membership ingestion with fail-closed coverage checks.

BaoStock supplies dated HS300/CSI500 snapshots.  CSI A500 is intentionally
loaded through an explicit dated file until a credential-free historical API
with verifiable provenance is available.  A current snapshot is never
backfilled into an earlier decision date.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Iterable

import pandas as pd
import pyarrow.dataset as ds

from functions.data.pit_level1_builder import write_pit_table_atomic


BAOSTOCK_INDEX_QUERIES = {
    "000300": "query_hs300_stocks",
    "000905": "query_zz500_stocks",
}
TARGET_COUNTS = {"000300": 300, "000905": 500, "000510": 500}
A500_LAUNCH_DATE = pd.Timestamp("2024-09-23")
DEFAULT_RAW_ROOT = Path("data/raw_external/index_membership")
DEFAULT_SNAPSHOT_CACHE = DEFAULT_RAW_ROOT / "historical_index_membership_snapshots.parquet"
DEFAULT_PIT_ROOT = Path("data/processed/pit_level1")
DEFAULT_CURRENT_CONSTITUENTS = Path("data/processed/index_constituents.parquet")

# Public periodic adjustment attachments.  These pairs are intentionally kept
# as source-addressed reference data so reverse reconstruction is deterministic
# and reviewable.  The current local snapshot predates the June-2026 rebalance,
# therefore only effective events through 2025-12-15 are applied here.
A500_PERIODIC_ADJUSTMENTS = (
    {
        "announcement_at": "2025-05-30",
        "effective_from": "2025-06-16",
        "source_url": "https://www.itdcw.com/uploads/file/20250603/1748931876609103.pdf",
        "removals": (
            "002081", "002151", "002240", "002268", "002368", "002541", "300212",
            "300595", "300999", "600027", "600167", "600399", "600755", "600771",
            "600816", "600884", "603290", "603456", "603588", "603688", "603882",
        ),
        "additions": (
            "000032", "000426", "000563", "002130", "002155", "002244", "002595",
            "300442", "300757", "301358", "301381", "600208", "600312", "600511",
            "600864", "605589", "688213", "688266", "688506", "688578", "688608",
        ),
    },
    {
        "announcement_at": "2025-11-28",
        "effective_from": "2025-12-15",
        "source_url": (
            "https://oss-ch.csindex.com.cn/notice/20251128165753-"
            "%E9%99%84%E4%BB%B6%EF%BC%9A%E9%83%A8%E5%88%86%E6%8C%87%E6%95%B0"
            "%E6%A0%B7%E6%9C%AC%E8%B0%83%E6%95%B4%E5%90%8D%E5%8D%95.pdf"
        ),
        "removals": (
            "000563", "002372", "002439", "002508", "002831", "300182", "300296",
            "300315", "300769", "301381", "600129", "600131", "600188", "600315",
            "600335", "600919", "601636", "603000", "603613", "605358",
        ),
        "additions": (
            "002701", "002837", "002851", "002891", "300083", "300748", "300803",
            "300972", "600079", "600157", "600522", "600580", "600673", "600816",
            "601211", "688017", "688065", "688166", "688472", "688521",
        ),
    },
    {
        "announcement_at": "2026-01-06",
        "effective_from": "2026-01-12",
        "source_url": "https://www.yuncaijing.com/news/id_17070304.html",
        "removals": ("600079",),
        "additions": ("688114",),
    },
)


def observed_trading_dates(feature_path, *, start_date, end_date, max_days=None) -> list[pd.Timestamp]:
    """Read only the requested date column and return observed trading dates."""
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError(f"start_date is after end_date: {start.date()} > {end.date()}")
    dataset = ds.dataset(str(Path(feature_path)), format="parquet")
    field = ds.field("date")
    table = dataset.to_table(columns=["date"], filter=(field >= start) & (field <= end))
    dates = pd.to_datetime(table.column("date").to_pandas(), errors="coerce").dropna().dt.normalize()
    result = sorted(pd.Timestamp(value) for value in dates.unique())
    if max_days is not None:
        result = result[: max(int(max_days), 0)]
    if not result:
        raise ValueError(f"No observed feature trading dates in {start.date()}..{end.date()}")
    return result


def fetch_baostock_snapshots(
    dates: Iterable,
    *,
    index_codes=("000300", "000905"),
    progress_callback=None,
) -> pd.DataFrame:
    """Fetch dated constituent sets; every response is retained as observed."""
    import baostock as bs

    normalized_dates = [pd.Timestamp(value).normalize() for value in dates]
    requested = [str(value).zfill(6) for value in index_codes]
    unsupported = sorted(set(requested) - set(BAOSTOCK_INDEX_QUERIES))
    if unsupported:
        raise ValueError(f"BaoStock historical constituent query is unavailable for {unsupported}")
    login = bs.login()
    if str(login.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    rows: list[dict] = []
    try:
        total = max(len(normalized_dates) * len(requested), 1)
        completed = 0
        for date in normalized_dates:
            for index_code in requested:
                query = getattr(bs, BAOSTOCK_INDEX_QUERIES[index_code])
                result = query(date.strftime("%Y-%m-%d"))
                if str(result.error_code) != "0":
                    raise RuntimeError(
                        f"BaoStock {index_code} query failed for {date.date()}: "
                        f"{result.error_code} {result.error_msg}"
                    )
                while result.next():
                    values = dict(zip(result.fields, result.get_row_data()))
                    rows.append({
                        "snapshot_date": date,
                        "provider_update_date": pd.to_datetime(values.get("updateDate"), errors="coerce"),
                        "index_code": index_code,
                        "symbol": normalize_a_share_symbol(values.get("code")),
                        "membership_weight": 1.0,
                        "source": "baostock_dated_membership_research",
                        "source_document_id": f"baostock:{index_code}:{date.date()}",
                        "downloaded_at": pd.Timestamp.now(tz="UTC"),
                    })
                completed += 1
                if progress_callback is not None:
                    progress_callback({
                        "percent": 5.0 + 55.0 * completed / total,
                        "step": "baostock_history",
                        "message": f"fetched {index_code} membership for {date.date()}",
                    })
    finally:
        bs.logout()
    return normalize_snapshot_frame(pd.DataFrame(rows))


def load_a500_snapshot_file(path) -> pd.DataFrame:
    """Load explicit historical A500 snapshots; an undated file is rejected."""
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"CSI A500 historical membership file is missing: {source_path}")
    suffix = source_path.suffix.lower()
    if suffix == ".parquet":
        data = pd.read_parquet(source_path)
    elif suffix in {".xlsx", ".xls"}:
        data = pd.read_excel(source_path)
    elif suffix in {".csv", ".txt"}:
        data = pd.read_csv(source_path, encoding="utf-8-sig")
    else:
        raise ValueError(f"Unsupported A500 history file: {source_path.suffix}")
    date_col = _first_column(data, "snapshot_date", "trade_date", "date", "as_of_date")
    symbol_col = _first_column(data, "symbol", "code", "con_code", "成分券代码", "证券代码")
    if date_col is None or symbol_col is None:
        raise ValueError(
            "A500 history file requires a dated snapshot column "
            "(snapshot_date/trade_date/date/as_of_date) and symbol/code column"
        )
    index_values = (
        data[_first_column(data, "index_code", "指数代码")].astype(str).str.extract(r"(\d{6})", expand=False)
        if _first_column(data, "index_code", "指数代码") is not None
        else pd.Series("000510", index=data.index)
    )
    weight_col = _first_column(data, "membership_weight", "weight", "权重")
    result = pd.DataFrame({
        "snapshot_date": pd.to_datetime(data[date_col], errors="coerce").dt.normalize(),
        "provider_update_date": pd.to_datetime(data[date_col], errors="coerce").dt.normalize(),
        "index_code": index_values.fillna("000510").astype(str).str.zfill(6),
        "symbol": data[symbol_col].map(normalize_a_share_symbol),
        "membership_weight": (
            pd.to_numeric(data[weight_col], errors="coerce") if weight_col else 1.0
        ),
        "source": "explicit_a500_dated_membership_research",
        "source_document_id": [f"file:{source_path.name}:{index}" for index in data.index],
        "downloaded_at": pd.Timestamp.now(tz="UTC"),
    })
    result = result[result["index_code"].eq("000510")]
    return normalize_snapshot_frame(result)


def reconstruct_a500_snapshots_from_current(
    dates: Iterable,
    *,
    current_constituents_path=DEFAULT_CURRENT_CONSTITUENTS,
) -> pd.DataFrame:
    """Reverse complete periodic adjustments from a later local A500 set.

    This is research-only.  It reconstructs the requested 2025--2026 window
    from complete 21-for-21 periodic lists and fails if set transitions do not
    reconcile exactly.  Temporary-event coverage remains a disclosed gap.
    """
    path = Path(current_constituents_path)
    if not path.exists():
        raise FileNotFoundError(f"Current constituent baseline is missing: {path}")
    raw = pd.read_parquet(path)
    required = {"index_code", "symbol", "asof_date"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"Current constituent baseline missing columns: {missing}")
    base = raw[raw["index_code"].astype(str).str.zfill(6).eq("000510")].copy()
    if base["symbol"].map(normalize_a_share_symbol).nunique() != 500:
        raise ValueError("Current CSI A500 baseline must contain exactly 500 unique symbols")
    asof_values = pd.to_datetime(base["asof_date"], errors="coerce").dropna().dt.normalize()
    if asof_values.empty or asof_values.nunique() != 1:
        raise ValueError("Current CSI A500 baseline requires one explicit asof_date")
    baseline_date = pd.Timestamp(asof_values.iloc[0])
    requested_dates = sorted(pd.Timestamp(value).normalize() for value in dates)
    if requested_dates and requested_dates[0] < pd.Timestamp("2024-12-16"):
        raise ValueError("A500 reverse reconstruction currently starts at 2024-12-16")
    if requested_dates and requested_dates[-1] > baseline_date:
        raise ValueError(
            f"A500 requested date {requested_dates[-1].date()} exceeds baseline {baseline_date.date()}"
        )
    baseline = {normalize_a_share_symbol(value) for value in base["symbol"]}
    rows: list[dict] = []
    adjustments = sorted(
        A500_PERIODIC_ADJUSTMENTS,
        key=lambda item: pd.Timestamp(item["effective_from"]),
        reverse=True,
    )
    for date in requested_dates:
        members = set(baseline)
        applied = []
        for event in adjustments:
            effective = pd.Timestamp(event["effective_from"])
            if effective <= date or effective > baseline_date:
                continue
            additions = {normalize_a_share_symbol(value) for value in event["additions"]}
            removals = {normalize_a_share_symbol(value) for value in event["removals"]}
            missing_additions = sorted(additions - members)
            unexpected_removals = sorted(removals & members)
            if missing_additions or unexpected_removals:
                raise ValueError(
                    f"A500 reverse transition does not reconcile at {effective.date()}: "
                    f"missing_additions={missing_additions[:5]}, active_removals={unexpected_removals[:5]}"
                )
            members.difference_update(additions)
            members.update(removals)
            if len(members) != 500:
                raise ValueError(f"A500 reverse transition at {effective.date()} produced {len(members)} members")
            applied.append(str(event["source_url"]))
        if len(members) != 500:
            raise ValueError(f"A500 reconstruction for {date.date()} produced {len(members)} members")
        document_digest = sha256("|".join(applied).encode("utf-8")).hexdigest()[:16]
        for symbol in sorted(members):
            rows.append({
                "snapshot_date": date,
                "provider_update_date": date,
                "index_code": "000510",
                "symbol": symbol,
                "membership_weight": 1.0,
                "source": "csindex_periodic_reverse_reconstruction_research",
                "source_document_id": f"a500-reverse:{date.date()}:{document_digest}",
                "downloaded_at": pd.Timestamp.now(tz="UTC"),
            })
    return normalize_snapshot_frame(pd.DataFrame(rows))


def normalize_snapshot_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "snapshot_date", "provider_update_date", "index_code", "symbol",
        "membership_weight", "source", "source_document_id", "downloaded_at",
    ]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    data = frame.copy()
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        raise ValueError(f"Historical membership snapshots missing columns: {missing}")
    data["snapshot_date"] = pd.to_datetime(data["snapshot_date"], errors="coerce").dt.normalize()
    data["provider_update_date"] = pd.to_datetime(data["provider_update_date"], errors="coerce").dt.normalize()
    data["downloaded_at"] = pd.to_datetime(data["downloaded_at"], errors="coerce", utc=True)
    data["index_code"] = data["index_code"].astype(str).str.extract(r"(\d{6})", expand=False).str.zfill(6)
    data["symbol"] = data["symbol"].map(normalize_a_share_symbol)
    data["membership_weight"] = pd.to_numeric(data["membership_weight"], errors="coerce").fillna(1.0)
    data = data.dropna(subset=["snapshot_date", "index_code", "symbol"])
    return data[columns].drop_duplicates(["snapshot_date", "index_code", "symbol"], keep="last").sort_values(
        ["snapshot_date", "index_code", "symbol"]
    ).reset_index(drop=True)


def merge_snapshot_cache(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return normalize_snapshot_frame(incoming)
    old = normalize_snapshot_frame(existing)
    new = normalize_snapshot_frame(incoming)
    return normalize_snapshot_frame(pd.concat([old, new], ignore_index=True))


def validate_snapshot_coverage(snapshots: pd.DataFrame, dates: Iterable) -> pd.DataFrame:
    data = normalize_snapshot_frame(snapshots)
    requested_dates = [pd.Timestamp(value).normalize() for value in dates]
    rows = []
    for date in requested_dates:
        for index_code, expected in TARGET_COUNTS.items():
            if index_code == "000510" and date < A500_LAUNCH_DATE:
                expected = 0
            count = int(data[
                data["snapshot_date"].eq(date) & data["index_code"].eq(index_code)
            ]["symbol"].nunique())
            rows.append({
                "snapshot_date": date,
                "index_code": index_code,
                "expected_count": expected,
                "observed_count": count,
                "passed": count == expected,
                "reason": "count_match" if count == expected else "constituent_count_mismatch",
            })
    return pd.DataFrame(rows)


def compress_snapshots_to_pit(snapshots: pd.DataFrame, dates: Iterable) -> pd.DataFrame:
    """Compress daily sets into half-open membership intervals."""
    data = normalize_snapshot_frame(snapshots)
    requested_dates = sorted(pd.Timestamp(value).normalize() for value in dates)
    coverage = validate_snapshot_coverage(data, requested_dates)
    failed = coverage[~coverage["passed"]]
    if not failed.empty:
        detail = "; ".join(
            f"{row.index_code}@{row.snapshot_date.date()}={row.observed_count}/{row.expected_count}"
            for row in failed.head(20).itertuples()
        )
        raise ValueError(f"Historical constituent coverage is incomplete: {detail}")
    records: list[dict] = []
    for index_code in TARGET_COUNTS:
        active: dict[str, dict] = {}
        for date in requested_dates:
            one = data[data["snapshot_date"].eq(date) & data["index_code"].eq(index_code)]
            current = set(one["symbol"].astype(str))
            for symbol in sorted(set(active) - current):
                record = active.pop(symbol)
                record["effective_to"] = date
                records.append(record)
            by_symbol = one.set_index("symbol", drop=False).to_dict("index") if not one.empty else {}
            for symbol in sorted(current - set(active)):
                row = by_symbol[symbol]
                active[symbol] = {
                    "symbol": symbol,
                    "effective_from": date,
                    "effective_to": pd.NaT,
                    # Snapshot-only membership is treated as knowable no earlier
                    # than its effective observation date.
                    "known_at": date,
                    "source": str(row["source"]),
                    "source_document_id": str(row["source_document_id"]),
                    "downloaded_at": row["downloaded_at"],
                    "index_code": index_code,
                    "membership_weight": float(row["membership_weight"]),
                }
        records.extend(active.values())
    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError("Historical membership compression produced no intervals")
    result["revision_id"] = result.apply(
        lambda row: sha256(
            "|".join(str(row.get(name, "")) for name in (
                "index_code", "symbol", "effective_from", "effective_to", "known_at", "source_document_id"
            )).encode("utf-8")
        ).hexdigest()[:16],
        axis=1,
    )
    columns = [
        "symbol", "effective_from", "effective_to", "known_at", "source",
        "source_document_id", "revision_id", "downloaded_at", "index_code", "membership_weight",
    ]
    return result[columns].sort_values(["index_code", "symbol", "effective_from"]).reset_index(drop=True)


def build_historical_index_membership(
    *,
    feature_path,
    start_date,
    end_date,
    max_days=None,
    a500_history_path=None,
    snapshot_cache=DEFAULT_SNAPSHOT_CACHE,
    output_root=DEFAULT_PIT_ROOT,
    progress_callback=None,
) -> dict[str, Path]:
    """Fetch, validate, cache and atomically publish research PIT membership."""
    dates = observed_trading_dates(
        feature_path, start_date=start_date, end_date=end_date, max_days=max_days
    )
    if progress_callback is not None:
        progress_callback({"percent": 2.0, "step": "calendar", "message": f"resolved {len(dates)} trading dates"})
    fetched = fetch_baostock_snapshots(dates, progress_callback=progress_callback)
    cache_path = Path(snapshot_cache)
    existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame()
    combined = merge_snapshot_cache(existing, fetched)
    if a500_history_path:
        combined = merge_snapshot_cache(combined, load_a500_snapshot_file(a500_history_path))
    else:
        combined = merge_snapshot_cache(combined, reconstruct_a500_snapshots_from_current(dates))
    requested = combined[combined["snapshot_date"].isin(dates)].copy()
    coverage = validate_snapshot_coverage(requested, dates)
    failed = coverage[~coverage["passed"]]
    coverage_path = cache_path.with_name("historical_index_membership_coverage.csv")
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_parquet(combined, cache_path)
    if not failed.empty:
        detail = failed.head(20).to_dict("records")
        raise ValueError(f"Historical membership coverage failed: {detail}; report={coverage_path}")
    if progress_callback is not None:
        progress_callback({"percent": 75.0, "step": "compress", "message": "compressing snapshots into PIT intervals"})
    intervals = compress_snapshots_to_pit(requested, dates)
    output = Path(output_root) / "index_membership_pit.parquet"
    backup = _backup_existing(output)
    output_path = write_pit_table_atomic(
        intervals,
        table_name="index_membership_pit",
        root=output_root,
        formal_eligible=False,
        provenance={
            "source": "baostock_plus_a500_historical_reconstruction",
            "coverage_start": str(dates[0].date()),
            "coverage_end": str(dates[-1].date()),
            "coverage_date_count": len(dates),
            "snapshot_cache": str(cache_path),
            "a500_history_path": str(a500_history_path or ""),
            "degradation_flags": [
                "snapshot_known_at_set_to_effective_date",
                "announcement_timestamp_not_yet_enriched",
                "a500_periodic_reverse_reconstruction",
                "a500_temporary_adjustment_archive_incomplete",
                "research_only",
            ],
        },
    )
    manifest = output_path.with_suffix(".manifest.json")
    if progress_callback is not None:
        progress_callback({"percent": 100.0, "step": "complete", "message": "historical membership PIT published"})
    result = {
        "snapshot_cache": cache_path,
        "coverage_report": coverage_path,
        "index_membership_pit": output_path,
        "manifest": manifest,
    }
    if backup is not None:
        result["previous_membership_backup"] = backup
    return result


def normalize_a_share_symbol(value) -> str:
    raw = str(value or "").strip().lower().replace(".", "")
    digits = "".join(character for character in raw if character.isdigit())[-6:].zfill(6)
    if raw.startswith(("sh", "sz", "bj")):
        return raw[:2] + digits
    if raw.endswith(("sh", "sz", "bj")):
        return raw[-2:] + digits
    if digits.startswith(("4", "8")):
        return "bj" + digits
    if digits.startswith(("0", "1", "2", "3")):
        return "sz" + digits
    return "sh" + digits


def _first_column(frame: pd.DataFrame, *names):
    return next((name for name in names if name in frame.columns), None)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(path)


def _backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = path.with_name(f"{path.stem}.before_historical_{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    manifest = path.with_suffix(".manifest.json")
    if manifest.exists():
        shutil.copy2(manifest, backup.with_suffix(".manifest.json"))
    return backup
