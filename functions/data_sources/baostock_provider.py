# -*- coding: utf-8 -*-
"""BaoStock provider adapters for auditable A-share adjustment inputs."""
from __future__ import annotations

from dataclasses import dataclass
import time

import pandas as pd

from config import BAOSTOCK_ADJUSTMENT_SOURCE, BAOSTOCK_CORPORATE_ACTION_SOURCE
from functions.data_sources.adjustment_factors import normalize_provider_adjustment_factors
from functions.data_sources.corporate_actions import normalize_corporate_actions


@dataclass(frozen=True)
class ProviderFetchResult:
    data: pd.DataFrame
    errors: pd.DataFrame


def to_baostock_code(symbol: str) -> str | None:
    value = str(symbol).strip().lower()
    if value[:2] not in {"sh", "sz"} or len(value) != 8:
        return None
    return f"{value[:2]}.{value[2:]}"


def _import_baostock():
    try:
        import baostock as bs
    except ImportError as exc:
        raise RuntimeError(
            "BaoStock is not installed in the selected interpreter."
        ) from exc
    return bs


def _result_to_frame(result):
    rows = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def fetch_adjustment_factors(
    symbols,
    start_date,
    end_date,
    request_delay_seconds=0.35,
    login_retries=3,
    login_retry_delay_seconds=5.0,
):
    bs = _import_baostock()
    login_result = _login_with_retry(bs, login_retries, login_retry_delay_seconds)
    frames = []
    errors = []
    try:
        for symbol in symbols:
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            provider_code = to_baostock_code(symbol)
            if provider_code is None:
                errors.append({"symbol": symbol, "status": "unsupported_market_or_type"})
                continue
            result = bs.query_adjust_factor(
                code=provider_code,
                start_date=str(start_date),
                end_date=str(end_date),
            )
            if result.error_code != "0":
                errors.append({"symbol": symbol, "status": result.error_msg})
                continue
            frame = _result_to_frame(result)
            if frame.empty:
                frame = pd.DataFrame(
                    {
                        "code": [provider_code],
                        "dividOperateDate": [str(start_date)],
                        "foreAdjustFactor": [pd.NA],
                        "backAdjustFactor": [1.0],
                        "action_type": ["provider_confirmed_identity"],
                    }
                )
            else:
                first_date = pd.to_datetime(frame["dividOperateDate"], errors="coerce").min()
                if pd.notna(first_date) and pd.Timestamp(start_date) < first_date:
                    anchor = pd.DataFrame(
                        {
                            "code": [provider_code],
                            "dividOperateDate": [str(start_date)],
                            "foreAdjustFactor": [pd.NA],
                            "backAdjustFactor": [1.0],
                            "action_type": ["provider_confirmed_identity"],
                        }
                    )
                    frame = pd.concat([anchor, frame], ignore_index=True)
            frame["external_code"] = frame["code"]
            frame["symbol"] = symbol
            frames.append(frame)
    finally:
        bs.logout()
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    normalized = normalize_provider_adjustment_factors(raw, BAOSTOCK_ADJUSTMENT_SOURCE)
    return ProviderFetchResult(normalized, pd.DataFrame(errors))


def fetch_dividend_actions(
    symbols,
    start_year,
    end_year,
    request_delay_seconds=0.35,
    login_retries=3,
    login_retry_delay_seconds=5.0,
):
    bs = _import_baostock()
    login_result = _login_with_retry(bs, login_retries, login_retry_delay_seconds)
    frames = []
    errors = []
    try:
        for symbol in symbols:
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            provider_code = to_baostock_code(symbol)
            if provider_code is None:
                continue
            for year in range(int(start_year), int(end_year) + 1):
                result = bs.query_dividend_data(code=provider_code, year=str(year), yearType="report")
                if result.error_code != "0":
                    errors.append({"symbol": symbol, "year": year, "status": result.error_msg})
                    continue
                frame = _result_to_frame(result)
                if frame.empty:
                    continue
                frame["external_code"] = frame["code"]
                frame["market"] = symbol[:2]
                frame["code"] = symbol[2:]
                frame["action_date"] = frame.get("dividOperateDate")
                frame["action_type"] = "dividend"
                frame["cash_dividend"] = frame.get("dividCashPsBeforeTax")
                frame["stock_dividend_ratio"] = frame.get("dividStocksPs")
                frame["rights_issue_ratio"] = pd.NA
                frame["rights_issue_price"] = pd.NA
                frame["notes"] = "BaoStock dividend disclosure"
                frames.append(frame)
    finally:
        bs.logout()
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    normalized = normalize_corporate_actions(raw, BAOSTOCK_CORPORATE_ACTION_SOURCE)
    return ProviderFetchResult(normalized, pd.DataFrame(errors))


def _login_with_retry(bs, retries, delay_seconds):
    last_result = None
    for attempt in range(1, int(retries) + 1):
        last_result = bs.login()
        if last_result.error_code == "0":
            return last_result
        if attempt < int(retries) and delay_seconds > 0:
            time.sleep(delay_seconds)
    raise RuntimeError(f"BaoStock login failed: {last_result.error_msg}")
