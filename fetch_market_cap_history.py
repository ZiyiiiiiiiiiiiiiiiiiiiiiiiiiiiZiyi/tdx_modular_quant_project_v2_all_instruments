# -*- coding: utf-8 -*-
"""Build real market-cap history from a provider export or AkShare Eastmoney.

The published artifact is data/processed/market_cap_history.parquet.  This
script never fabricates market cap values: if the provider is unavailable, it
writes an error report and exits non-zero unless a local input file is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import struct
import time
from pathlib import Path
import zipfile

import pandas as pd

from config import (
    CLEAN_DAILY_PARQUET,
    MARKET_CAP_PARQUET,
    MARKET_CAP_QUALITY_CSV,
    RAW_EXTERNAL_DIR,
    REPORT_DIR,
    START_DATE,
    EXTERNAL_DATA_END_DATE,
    EXTERNAL_DATA_SYMBOL_LIMIT,
    MARKET_CAP_BATCH_DELAY_SECONDS,
    MARKET_CAP_BATCH_SIZE,
    MARKET_CAP_DEFAULT_SOURCE,
    MARKET_CAP_MAX_REPORT_FILES,
    MARKET_CAP_REPORT_START_DATE,
    MARKET_CAP_REQUEST_DELAY_SECONDS,
    assert_valid_configuration,
)
from functions.data_sources.market_cap_data import (
    detect_market_cap_jump_flags,
    fill_stabilized_market_cap,
    load_market_cap_input,
    normalize_market_cap_history,
    save_market_cap_history,
    save_market_cap_quality_report,
)


TDX_TOTAL_SHARE_FIELD_INDEX = 238
TDX_FLOAT_A_SHARE_FIELD_INDEX = 239


def eligible_stock_symbols(limit=None):
    bars = pd.read_parquet(CLEAN_DAILY_PARQUET, columns=["symbol", "instrument_type"])
    symbols = (
        bars[(bars["instrument_type"] == "stock") & bars["symbol"].str[:2].isin(["sh", "sz"])]
        ["symbol"].drop_duplicates().sort_values()
    )
    return symbols.head(limit).tolist() if limit else symbols.tolist()


def main():
    assert_valid_configuration()
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["akshare", "file", "tdx_finance"], default=MARKET_CAP_DEFAULT_SOURCE)
    parser.add_argument("--input-file", default=None, help="CSV/XLSX/Parquet with date, code/symbol, total_cap, float_cap.")
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=EXTERNAL_DATA_END_DATE)
    parser.add_argument("--limit", type=int, default=EXTERNAL_DATA_SYMBOL_LIMIT, help="Validation subset only.")
    parser.add_argument("--report-start-date", default=MARKET_CAP_REPORT_START_DATE)
    parser.add_argument("--max-report-files", type=int, default=MARKET_CAP_MAX_REPORT_FILES)
    parser.add_argument("--use-existing-reports-only", action="store_true")
    parser.add_argument("--batch-size", type=int, default=MARKET_CAP_BATCH_SIZE)
    parser.add_argument("--request-delay-seconds", type=float, default=MARKET_CAP_REQUEST_DELAY_SECONDS)
    parser.add_argument("--batch-delay-seconds", type=float, default=MARKET_CAP_BATCH_DELAY_SECONDS)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    args.end_date = args.end_date or pd.Timestamp.today().date().isoformat()

    if args.source == "file":
        if not args.input_file:
            raise ValueError("--input-file is required when --source=file")
        source_name = args.source_name or "manual_market_cap_file"
        market_cap = load_market_cap_input(args.input_file, source_name=source_name)
    elif args.source == "tdx_finance":
        source_name = args.source_name or "tdx_finance_gpcw"
        market_cap = build_market_cap_from_tdx_finance(
            start_date=args.start_date,
            end_date=args.end_date,
            report_start_date=args.report_start_date,
            source_name=source_name,
            limit=args.limit,
            max_report_files=args.max_report_files,
            use_existing_reports_only=args.use_existing_reports_only,
        )
    else:
        source_name = args.source_name or "akshare_eastmoney_hist"
        symbols = eligible_stock_symbols(limit=args.limit)
        market_cap, errors = _fetch_akshare_in_batches(
            symbols=symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            source_name=source_name,
            batch_size=args.batch_size,
            request_delay_seconds=args.request_delay_seconds,
            batch_delay_seconds=args.batch_delay_seconds,
            resume=args.resume,
        )
        error_path = REPORT_DIR / "akshare_market_cap_fetch_errors.csv"
        if not errors.empty:
            errors.to_csv(error_path, index=False, encoding="utf-8-sig")
        if market_cap.empty:
            raise RuntimeError(f"AkShare returned no market-cap rows; see {error_path}")

    market_cap = detect_market_cap_jump_flags(market_cap)
    market_cap = fill_stabilized_market_cap(market_cap)

    stage_path = RAW_EXTERNAL_DIR / "market_cap_history_staged.parquet"
    save_market_cap_history(market_cap, stage_path)
    save_market_cap_quality_report(market_cap, REPORT_DIR / "market_cap_history_staged_quality.csv")
    print(f"Staged market-cap rows: {len(market_cap)}")
    print(f"Staged market-cap symbols: {market_cap['symbol'].nunique()}")
    print(f"Staged market-cap data: {stage_path}")

    if args.publish:
        save_market_cap_history(market_cap, MARKET_CAP_PARQUET)
        save_market_cap_quality_report(market_cap, MARKET_CAP_QUALITY_CSV)
        print(f"Published market-cap data: {MARKET_CAP_PARQUET}")
        print(f"Published market-cap quality report: {MARKET_CAP_QUALITY_CSV}")


def build_market_cap_from_tdx_finance(
    start_date,
    end_date,
    report_start_date,
    source_name="tdx_finance_gpcw",
    limit=None,
    max_report_files=None,
    use_existing_reports_only=False,
):
    daily = pd.read_parquet(
        CLEAN_DAILY_PARQUET,
        columns=["date", "symbol", "market", "code", "instrument_type", "close"],
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily[
        (daily["instrument_type"] == "stock")
        & daily["market"].isin(["sh", "sz"])
        & daily["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
    ].copy()
    if limit is not None:
        symbols = set(daily["symbol"].drop_duplicates().sort_values().head(limit))
        daily = daily[daily["symbol"].isin(symbols)].copy()
    if daily.empty:
        raise RuntimeError("No Shanghai/Shenzhen stock daily bars are available for market-cap construction")

    reports = fetch_tdx_finance_share_reports(
        report_start_date=report_start_date,
        max_report_files=max_report_files,
        use_existing_reports_only=use_existing_reports_only,
    )
    if reports.empty:
        raise RuntimeError("No usable TDX financial share reports were parsed")

    shares = _expand_share_reports_to_daily(reports, daily)
    merged = daily.merge(shares, on=["symbol", "date"], how="left")
    merged["total_cap"] = merged["close"] * merged["total_shares"]
    merged["float_cap"] = merged["close"] * merged["float_a_shares"]
    raw = merged[
        [
            "date",
            "market",
            "code",
            "symbol",
            "total_cap",
            "float_cap",
            "effective_report_date",
        ]
    ].copy()
    raw["external_code"] = raw["code"]
    raw["jump_event_type"] = raw["effective_report_date"].notna().map(
        {True: "tdx_finance_share_update", False: ""}
    )
    return normalize_market_cap_history(raw, source_name=source_name)


def fetch_tdx_finance_share_reports(
    report_start_date="2017-01-01",
    max_report_files=None,
    use_existing_reports_only=False,
):
    file_list = (
        _existing_tdx_finance_file_list()
        if use_existing_reports_only
        else _fetch_tdx_finance_file_list()
    )
    min_report_date = pd.Timestamp(report_start_date)
    file_list = file_list[
        (file_list["report_date"] >= min_report_date)
        & (file_list["filesize"] > 1024)
        & file_list["filename"].str.startswith("gpcw")
    ].copy()
    file_list = file_list.sort_values("report_date")
    if max_report_files is not None:
        file_list = file_list.tail(max_report_files)
    if file_list.empty:
        return pd.DataFrame()

    RAW_EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    file_list.to_csv(RAW_EXTERNAL_DIR / "tdx_gpcw_filelist.csv", index=False, encoding="utf-8-sig")
    frames = []
    errors = []
    for _, row in file_list.iterrows():
        try:
            if use_existing_reports_only:
                zip_path = RAW_EXTERNAL_DIR / row["filename"]
            else:
                zip_path = _download_tdx_finance_zip(
                    filename=row["filename"],
                    expected_md5=row["md5"],
                    filesize=int(row["filesize"]),
                )
            parsed = _parse_tdx_finance_zip(zip_path)
            if not parsed.empty:
                frames.append(parsed)
            print(f"Parsed TDX finance report: {row['filename']} rows={len(parsed)}")
        except Exception as exc:
            errors.append(
                {
                    "filename": row["filename"],
                    "status": type(exc).__name__,
                    "message": str(exc),
                }
            )
    if errors:
        pd.DataFrame(errors).to_csv(
            REPORT_DIR / "tdx_finance_market_cap_errors.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _existing_tdx_finance_file_list():
    rows = []
    for path in sorted(RAW_EXTERNAL_DIR.glob("gpcw*.zip")):
        match = re.search(r"(\d{8})", path.name)
        if not match or not zipfile.is_zipfile(path):
            continue
        rows.append(
            {
                "filename": path.name,
                "md5": hashlib.md5(path.read_bytes()).hexdigest(),
                "filesize": int(path.stat().st_size),
                "report_date": pd.Timestamp(match.group(1)),
            }
        )
    return pd.DataFrame(rows)


def _fetch_tdx_finance_file_list():
    from mootdx.financial.financial import FinancialList

    content = FinancialList().content()
    text = content.read().decode("utf-8")
    rows = []
    for line in text.strip().splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 3:
            continue
        filename, md5, filesize = parts[:3]
        match = re.search(r"(\d{8})", filename)
        if not match:
            continue
        rows.append(
            {
                "filename": filename,
                "md5": md5,
                "filesize": int(filesize),
                "report_date": pd.Timestamp(match.group(1)),
            }
        )
    return pd.DataFrame(rows)


def _download_tdx_finance_zip(filename, expected_md5, filesize):
    output = RAW_EXTERNAL_DIR / filename
    if output.exists() and zipfile.is_zipfile(output):
        actual_md5 = hashlib.md5(output.read_bytes()).hexdigest()
        if not expected_md5 or actual_md5 == expected_md5:
            return output

    from mootdx.financial.financial import Financial

    download_file = Financial().content(
        downdir=RAW_EXTERNAL_DIR,
        filename=filename,
        filesize=0,
    )
    download_file.close()
    if not output.exists():
        raise FileNotFoundError(f"TDX finance download did not create {output}")
    if not zipfile.is_zipfile(output):
        raise ValueError(f"TDX finance file is not a valid zip: {output}")
    actual_md5 = hashlib.md5(output.read_bytes()).hexdigest()
    if expected_md5 and actual_md5 != expected_md5:
        raise ValueError(f"TDX finance md5 mismatch for {filename}: {actual_md5} != {expected_md5}")
    return output


def _parse_tdx_finance_zip(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        dat_names = [name for name in archive.namelist() if name.lower().endswith(".dat")]
        if not dat_names:
            raise ValueError(f"No .dat member found in {zip_path}")
        data = archive.read(dat_names[0])

    header_format = "<1hI1H3L"
    header_size = struct.calcsize(header_format)
    stock_item_format = "<6s1c1L"
    stock_item_size = struct.calcsize(stock_item_format)
    header = struct.unpack(header_format, data[:header_size])
    report_date = pd.Timestamp(str(header[1]))
    stock_count = int(header[2])
    report_size = int(header[4])
    field_count = int(report_size / 4)
    report_format = f"<{field_count}f"
    if field_count <= TDX_TOTAL_SHARE_FIELD_INDEX:
        raise ValueError(f"TDX finance report has too few fields: {field_count}")

    rows = []
    for idx in range(stock_count):
        item_start = header_size + idx * stock_item_size
        item = data[item_start:item_start + stock_item_size]
        if len(item) != stock_item_size:
            continue
        code_raw, _, record_offset = struct.unpack(stock_item_format, item)
        record = data[record_offset:record_offset + report_size]
        if len(record) != report_size:
            continue
        values = struct.unpack(report_format, record)
        total_shares = values[TDX_TOTAL_SHARE_FIELD_INDEX]
        float_a_shares = values[TDX_FLOAT_A_SHARE_FIELD_INDEX] if field_count > TDX_FLOAT_A_SHARE_FIELD_INDEX else None
        code = code_raw.decode("utf-8", errors="ignore")
        market = _infer_cn_stock_market(code)
        if market is None:
            continue
        rows.append(
            {
                "symbol": f"{market}{code}",
                "market": market,
                "code": code,
                "report_date": report_date,
                "effective_date": _statutory_report_effective_date(report_date),
                "total_shares": pd.NA if total_shares <= 0 else float(total_shares),
                "float_a_shares": pd.NA if not float_a_shares or float_a_shares <= 0 else float(float_a_shares),
            }
        )
    return pd.DataFrame(rows)


def _expand_share_reports_to_daily(reports, daily):
    reports = reports.dropna(subset=["symbol", "effective_date", "total_shares"]).copy()
    if reports.empty:
        return pd.DataFrame(columns=["symbol", "date", "total_shares", "float_a_shares", "effective_report_date"])
    reports = reports.sort_values(["symbol", "effective_date", "report_date"])
    reports["total_shares"] = pd.to_numeric(reports["total_shares"], errors="coerce")
    reports["float_a_shares"] = pd.to_numeric(reports["float_a_shares"], errors="coerce")
    reports["float_a_shares"] = reports["float_a_shares"].fillna(reports["total_shares"])
    reports = reports.drop_duplicates(["symbol", "effective_date"], keep="last")

    calendar = daily[["symbol", "date"]].drop_duplicates().sort_values(["symbol", "date"])
    parts = []
    for symbol, symbol_days in calendar.groupby("symbol", sort=False):
        symbol_reports = reports[reports["symbol"] == symbol]
        if symbol_reports.empty:
            continue
        merged = pd.merge_asof(
            symbol_days.sort_values("date"),
            symbol_reports.rename(columns={"effective_date": "date"})[
                ["date", "report_date", "total_shares", "float_a_shares"]
            ].sort_values("date"),
            on="date",
            direction="backward",
        )
        merged = merged.rename(columns={"report_date": "effective_report_date"})
        parts.append(merged)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _statutory_report_effective_date(report_date):
    report_date = pd.Timestamp(report_date)
    month_day = report_date.strftime("%m%d")
    if month_day == "0331":
        return pd.Timestamp(year=report_date.year, month=4, day=30)
    if month_day == "0630":
        return pd.Timestamp(year=report_date.year, month=8, day=31)
    if month_day == "0930":
        return pd.Timestamp(year=report_date.year, month=10, day=31)
    if month_day == "1231":
        return pd.Timestamp(year=report_date.year + 1, month=4, day=30)
    return report_date + pd.Timedelta(days=120)


def _infer_cn_stock_market(code):
    value = str(code).strip()
    if value.startswith(("6", "9")):
        return "sh"
    if value.startswith(("0", "2", "3")):
        return "sz"
    return None


def _fetch_akshare_in_batches(
    symbols,
    start_date,
    end_date,
    source_name,
    batch_size,
    request_delay_seconds,
    batch_delay_seconds,
    resume,
):
    data_path = RAW_EXTERNAL_DIR / "akshare_market_cap_history.parquet"
    error_path = REPORT_DIR / "akshare_market_cap_fetch_errors.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    existing_data = pd.read_parquet(data_path) if resume and data_path.exists() else pd.DataFrame()
    existing_errors = pd.read_csv(error_path) if resume and error_path.exists() else pd.DataFrame()
    done = set(existing_data.get("symbol", pd.Series(dtype=str)).dropna())
    if "symbol" in existing_errors.columns:
        done.update(existing_errors["symbol"].dropna())

    pending = [symbol for symbol in symbols if symbol not in done]
    data_frames = [existing_data] if not existing_data.empty else []
    error_frames = [existing_errors] if not existing_errors.empty else []
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        for symbol in batch:
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            try:
                raw = _fetch_akshare_symbol_market_cap(symbol, start_date, end_date)
                if raw.empty:
                    error_frames.append(pd.DataFrame([{"symbol": symbol, "status": "empty"}]))
                    continue
                raw["market"] = symbol[:2]
                raw["code"] = symbol[2:]
                raw["external_code"] = _to_akshare_code(symbol)
                data_frames.append(normalize_market_cap_history(raw, source_name=source_name))
            except Exception as exc:
                error_frames.append(pd.DataFrame([{"symbol": symbol, "status": type(exc).__name__, "message": str(exc)}]))

        data = pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()
        errors = pd.concat(error_frames, ignore_index=True) if error_frames else pd.DataFrame()
        if not data.empty:
            data.drop_duplicates().to_parquet(data_path, index=False)
        if not errors.empty:
            errors.drop_duplicates().to_csv(error_path, index=False, encoding="utf-8-sig")
        print(f"Fetched market-cap batch {min(offset + batch_size, len(pending))}/{len(pending)} pending symbols")
        if batch_delay_seconds > 0 and offset + batch_size < len(pending):
            time.sleep(batch_delay_seconds)

    data = pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()
    errors = pd.concat(error_frames, ignore_index=True) if error_frames else pd.DataFrame()
    return data.drop_duplicates(), errors.drop_duplicates()


def _fetch_akshare_symbol_market_cap(symbol, start_date, end_date):
    import akshare as ak

    frame = ak.stock_zh_a_hist(
        symbol=_to_akshare_code(symbol),
        period="daily",
        start_date=_compact_date(start_date),
        end_date=_compact_date(end_date),
        adjust="",
    )
    if frame.empty:
        return pd.DataFrame()
    return _normalize_akshare_hist_columns(frame)


def _normalize_akshare_hist_columns(frame):
    rename_map = {}
    for col in frame.columns:
        text = str(col)
        if text in {"date", "\u65e5\u671f"}:
            rename_map[col] = "date"
        elif text in {"total_cap", "\u603b\u5e02\u503c"}:
            rename_map[col] = "total_cap"
        elif text in {"float_cap", "\u6d41\u901a\u5e02\u503c"}:
            rename_map[col] = "float_cap"
    data = frame.rename(columns=rename_map).copy()
    if "total_cap" not in data.columns:
        raise ValueError("AkShare response does not include total market cap column")
    if "float_cap" not in data.columns:
        data["float_cap"] = pd.NA
    return data[["date", "total_cap", "float_cap"]]


def _to_akshare_code(symbol):
    return str(symbol).strip().lower()[2:]


def _compact_date(value):
    return pd.Timestamp(value).strftime("%Y%m%d")


if __name__ == "__main__":
    main()
