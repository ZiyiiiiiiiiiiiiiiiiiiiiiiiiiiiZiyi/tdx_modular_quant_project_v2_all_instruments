# -*- coding: utf-8 -*-
"""Fetch validated adjustment/company-action inputs for formal research runs."""
from __future__ import annotations

import argparse
import time

import pandas as pd
from pandas.errors import EmptyDataError

from config import (
    ADJUSTMENT_FACTORS_PARQUET,
    CLEAN_DAILY_PARQUET,
    CORPORATE_ACTIONS_PARQUET,
    RAW_EXTERNAL_DIR,
    REPORT_DIR,
    START_DATE,
    EXTERNAL_DATA_BATCH_DELAY_SECONDS,
    EXTERNAL_DATA_BATCH_SIZE,
    EXTERNAL_DATA_DIVIDEND_BATCH_SIZE,
    EXTERNAL_DATA_END_DATE,
    EXTERNAL_DATA_FACTOR_HISTORY_START,
    EXTERNAL_DATA_LOGIN_RETRIES,
    EXTERNAL_DATA_LOGIN_RETRY_DELAY_SECONDS,
    EXTERNAL_DATA_REQUEST_DELAY_SECONDS,
    EXTERNAL_DATA_SOCKET_TIMEOUT_SECONDS,
    EXTERNAL_DATA_SYMBOL_LIMIT,
    assert_valid_configuration,
)
from functions.data_sources.adjustment_factors import (
    save_adjustment_factors,
    save_adjustment_factors_quality_report,
)
from functions.data_sources.baostock_provider import fetch_adjustment_factors, fetch_dividend_actions
from functions.data_sources.corporate_actions import (
    save_corporate_actions,
    save_corporate_actions_quality_report,
)


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
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--factor-history-start", default=EXTERNAL_DATA_FACTOR_HISTORY_START)
    parser.add_argument("--end-date", default=EXTERNAL_DATA_END_DATE)
    parser.add_argument("--limit", type=int, default=EXTERNAL_DATA_SYMBOL_LIMIT, help="Validation subset only.")
    parser.add_argument("--skip-dividends", action="store_true")
    parser.add_argument("--batch-size", type=int, default=EXTERNAL_DATA_BATCH_SIZE)
    parser.add_argument(
        "--dividend-batch-size",
        type=int,
        default=EXTERNAL_DATA_DIVIDEND_BATCH_SIZE,
        help="Dividend symbols staged per checkpoint. Keep this small because each symbol queries multiple years.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=EXTERNAL_DATA_REQUEST_DELAY_SECONDS,
        help="Pause between BaoStock symbol requests. BaoStock is sensitive to fast loops.",
    )
    parser.add_argument(
        "--batch-delay-seconds",
        type=float,
        default=EXTERNAL_DATA_BATCH_DELAY_SECONDS,
        help="Pause after each staged batch is written.",
    )
    parser.add_argument("--login-retries", type=int, default=EXTERNAL_DATA_LOGIN_RETRIES)
    parser.add_argument("--login-retry-delay-seconds", type=float, default=EXTERNAL_DATA_LOGIN_RETRY_DELAY_SECONDS)
    parser.add_argument(
        "--socket-timeout-seconds",
        type=float,
        default=EXTERNAL_DATA_SOCKET_TIMEOUT_SECONDS,
        help="Abort a stalled BaoStock socket request so a later run can resume from staged data.",
    )
    parser.add_argument("--publish", action="store_true", help="Publish completed full-universe results.")
    parser.add_argument("--resume", action="store_true", help="Resume a staged fetch.")
    args = parser.parse_args()
    args.end_date = args.end_date or pd.Timestamp.today().date().isoformat()
    if args.publish and args.limit is not None:
        raise ValueError("A limited validation fetch cannot be published as production data")
    symbols = eligible_stock_symbols(limit=args.limit)
    if not symbols:
        raise RuntimeError("No eligible Shanghai/Shenzhen stock symbols in cleaned daily data")

    stage_label = "validation" if args.limit is not None else "full"
    factor_stage = RAW_EXTERNAL_DIR / f"baostock_adjustment_{stage_label}.parquet"
    factor_error_stage = RAW_EXTERNAL_DIR / f"baostock_adjustment_{stage_label}_errors.csv"
    factor_completion_stage = RAW_EXTERNAL_DIR / f"baostock_adjustment_{stage_label}_completed_symbols.csv"
    factors, factor_errors = _fetch_in_batches(
        symbols=symbols,
        fetcher=lambda batch: fetch_adjustment_factors(
            batch,
            args.factor_history_start,
            args.end_date,
            request_delay_seconds=args.request_delay_seconds,
            login_retries=args.login_retries,
            login_retry_delay_seconds=args.login_retry_delay_seconds,
            socket_timeout_seconds=args.socket_timeout_seconds,
        ),
        data_path=factor_stage,
        error_path=factor_error_stage,
        completion_path=factor_completion_stage,
        batch_size=args.batch_size,
        resume=args.resume,
        batch_delay_seconds=args.batch_delay_seconds,
    )
    if factors.empty:
        raise RuntimeError("BaoStock returned no validated adjustment factors")
    save_adjustment_factors_quality_report(factors, REPORT_DIR / f"baostock_adjustment_{stage_label}_quality.csv")
    if args.publish:
        covered = set(factors["symbol"].dropna())
        failed = set(factor_errors["symbol"].dropna()) if "symbol" in factor_errors else set()
        unresolved = set(symbols) - covered - failed
        if unresolved:
            raise RuntimeError(f"Fetch completeness cannot be established; unresolved symbols: {len(unresolved)}")
        save_adjustment_factors(factors, ADJUSTMENT_FACTORS_PARQUET)
        save_adjustment_factors_quality_report(factors)
        factor_errors.to_csv(
            REPORT_DIR / "baostock_adjustment_fetch_errors.csv", index=False, encoding="utf-8-sig"
        )

    if not args.skip_dividends:
        action_stage = RAW_EXTERNAL_DIR / f"baostock_dividend_{stage_label}.parquet"
        action_error_stage = RAW_EXTERNAL_DIR / f"baostock_dividend_{stage_label}_errors.csv"
        action_completion_stage = RAW_EXTERNAL_DIR / f"baostock_dividend_{stage_label}_completed_symbols.csv"
        actions, action_errors = _fetch_in_batches(
            symbols=symbols,
            fetcher=lambda batch: fetch_dividend_actions(
                batch,
                pd.Timestamp(args.start_date).year,
                pd.Timestamp(args.end_date).year,
                request_delay_seconds=args.request_delay_seconds,
                login_retries=args.login_retries,
                login_retry_delay_seconds=args.login_retry_delay_seconds,
                socket_timeout_seconds=args.socket_timeout_seconds,
            ),
            data_path=action_stage,
            error_path=action_error_stage,
            completion_path=action_completion_stage,
            batch_size=args.dividend_batch_size,
            resume=args.resume,
            batch_delay_seconds=args.batch_delay_seconds,
        )
        save_corporate_actions_quality_report(actions, REPORT_DIR / f"baostock_dividend_{stage_label}_quality.csv")
        if args.publish:
            save_corporate_actions(actions, CORPORATE_ACTIONS_PARQUET)
            save_corporate_actions_quality_report(actions)
            action_errors.to_csv(
                REPORT_DIR / "baostock_dividend_fetch_errors.csv", index=False, encoding="utf-8-sig"
            )
    print(f"Validated adjustment symbols: {factors['symbol'].nunique()}/{len(symbols)}")
    print(f"Staged adjustment data: {factor_stage}")
    if args.publish:
        print(f"Published adjustment data: {ADJUSTMENT_FACTORS_PARQUET}")
    if not args.skip_dividends:
        print(f"Staged corporate action data: {action_stage}")
        if args.publish:
            print(f"Published corporate action data: {CORPORATE_ACTIONS_PARQUET}")


def _fetch_in_batches(
    symbols,
    fetcher,
    data_path,
    error_path,
    completion_path,
    batch_size,
    resume,
    batch_delay_seconds,
):
    data_path.parent.mkdir(parents=True, exist_ok=True)
    existing_data = pd.read_parquet(data_path) if resume and data_path.exists() else pd.DataFrame()
    try:
        existing_errors = pd.read_csv(error_path) if resume and error_path.exists() else pd.DataFrame()
    except EmptyDataError:
        existing_errors = pd.DataFrame()
    try:
        existing_completed = pd.read_csv(completion_path) if resume and completion_path.exists() else pd.DataFrame()
    except EmptyDataError:
        existing_completed = pd.DataFrame()
    done = set(existing_data.get("symbol", pd.Series(dtype=str)).dropna())
    if "symbol" in existing_errors.columns:
        done.update(existing_errors["symbol"].dropna())
    if "symbol" in existing_completed.columns:
        done.update(existing_completed["symbol"].dropna())
    pending = [symbol for symbol in symbols if symbol not in done]
    completed_symbols = set(existing_completed.get("symbol", pd.Series(dtype=str)).dropna())
    print(
        f"Resume checkpoint: completed={len(done)}, pending={len(pending)}, "
        f"batch_size={batch_size}, completion_file={completion_path.name}",
        flush=True,
    )
    data_frames = [existing_data] if not existing_data.empty else []
    error_frames = [existing_errors] if not existing_errors.empty else []
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        result = fetcher(batch)
        if not result.data.empty:
            data_frames.append(result.data)
        if not result.errors.empty:
            error_frames.append(result.errors)
        data = pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()
        errors = pd.concat(error_frames, ignore_index=True) if error_frames else pd.DataFrame()
        data.to_parquet(data_path, index=False)
        if not errors.empty:
            errors.to_csv(error_path, index=False, encoding="utf-8-sig")
        completed_symbols.update(batch)
        pd.DataFrame({"symbol": sorted(completed_symbols)}).to_csv(
            completion_path, index=False, encoding="utf-8-sig"
        )
        print(
            f"Fetched and checkpointed {min(offset + batch_size, len(pending))}/{len(pending)} pending symbols",
            flush=True,
        )
        if batch_delay_seconds > 0 and offset + batch_size < len(pending):
            time.sleep(batch_delay_seconds)
    data = pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()
    errors = pd.concat(error_frames, ignore_index=True) if error_frames else pd.DataFrame()
    return data.drop_duplicates(), errors.drop_duplicates()


if __name__ == "__main__":
    main()
