# -*- coding: utf-8 -*-
import os
import struct
import pandas as pd

def classify_tdx_instrument(market, code):
    code = str(code).zfill(6)

    if market == "sh" and code.startswith("900"):
        return "b_share"
    if market == "sz" and code.startswith("200"):
        return "b_share"

    if market == "sh" and code.startswith(("600", "601", "603", "605", "688")):
        return "stock"
    if market == "sz" and code.startswith(("000", "001", "002", "003", "300", "301")):
        return "stock"
    if market == "bj" and code.startswith(("4", "8")):
        return "stock"

    if market == "sh" and code.startswith(("510", "511", "512", "513", "515", "516", "517", "518", "519", "588", "589")):
        return "etf_fund"
    if market == "sz" and code.startswith(("159", "160", "161", "162", "163", "164", "165", "166", "167", "168", "169")):
        return "etf_fund"

    if market == "sh" and code.startswith(("000", "880", "881", "882", "883", "884", "885", "886")):
        return "index"
    if market == "sz" and code.startswith(("399", "980", "981", "982", "983", "984", "985", "986")):
        return "index"

    if market == "sh" and code.startswith(("110", "113", "118")):
        return "convertible_bond"
    if market == "sz" and code.startswith(("123", "127", "128")):
        return "convertible_bond"

    if market == "sh" and code.startswith(("010", "019", "100", "105", "106", "107", "120", "122", "124", "130", "132", "133", "134", "135", "136", "137", "138", "139")):
        return "bond"
    if market == "sz" and code.startswith(("10", "11", "12")):
        return "bond"

    return "unknown"

def collect_tdx_day_files(tdx_dir, include_markets, include_types):
    rows = []
    for market in include_markets:
        folder = tdx_dir / "vipdoc" / market / "lday"
        if not folder.exists():
            print(f"[WARN] Folder not found: {folder}")
            continue

        for filename in os.listdir(folder):
            if not filename.endswith(".day"):
                continue

            raw = filename.replace(".day", "")
            if not raw.startswith(market):
                continue

            code = raw.replace(market, "")
            symbol = f"{market}{code}"
            instrument_type = classify_tdx_instrument(market, code)

            if instrument_type not in include_types:
                continue

            rows.append({
                "market": market,
                "code": str(code).zfill(6),
                "symbol": symbol,
                "instrument_type": instrument_type,
                "file_path": str(folder / filename),
            })

    return sorted(rows, key=lambda x: (x["market"], x["code"]))

def read_tdx_day_file(file_path, market, code, symbol, instrument_type):
    records = []

    with open(file_path, "rb") as f:
        while True:
            data = f.read(32)
            if not data or len(data) < 32:
                break

            try:
                date, open_p, high_p, low_p, close_p, amount, volume, reserved = struct.unpack("<IIIIIfII", data)
            except Exception:
                continue

            records.append({
                "date": pd.to_datetime(str(date), errors="coerce"),
                "market": market,
                "code": str(code).zfill(6),
                "symbol": symbol,
                "instrument_type": instrument_type,
                "open": open_p / 100.0,
                "high": high_p / 100.0,
                "low": low_p / 100.0,
                "close": close_p / 100.0,
                "amount": float(amount),
                "volume": float(volume),
            })

    df = pd.DataFrame(records)
    if df.empty:
        return df

    df = df.dropna(subset=["date"])
    df = df.sort_values("date")
    return df
