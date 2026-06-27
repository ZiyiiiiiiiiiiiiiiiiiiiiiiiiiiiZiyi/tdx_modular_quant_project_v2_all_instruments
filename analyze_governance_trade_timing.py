# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _default_run_dir() -> Path:
    root = Path("results/governance/hs300_csi500_a500_strict")
    candidates = sorted(
        root.rglob("governance_trade_pairs.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No governance_trade_pairs.csv found under results/governance.")
    return candidates[0].parent


def _load_prices(symbols: list[str], start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    feature_path = Path("data/processed/tdx_daily_features.parquet")
    if not feature_path.exists():
        raise FileNotFoundError(str(feature_path))
    import pyarrow.dataset as ds

    dataset = ds.dataset(str(feature_path), format="parquet")
    price_col = "trade_close" if "trade_close" in dataset.schema.names else "close"
    table = dataset.to_table(
        columns=["date", "symbol", price_col],
        filter=(
            ds.field("symbol").isin(symbols)
            & (ds.field("date") >= start_date.to_pydatetime())
            & (ds.field("date") <= end_date.to_pydatetime())
        ),
    )
    prices = table.to_pandas()
    if prices.empty:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    prices = prices.rename(columns={price_col: "close"})
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    return prices.dropna(subset=["date", "symbol", "close"]).sort_values(["symbol", "date"])


def _window_text(dates: pd.Series, index: int, half_window: int) -> str:
    left = max(index - half_window, 0)
    right = min(index + half_window, len(dates) - 1)
    return f"{dates.iloc[left].date()} -> {dates.iloc[right].date()}"


def _rank_points(frame: pd.DataFrame, *, mode: str, min_gap_days: int, top_n: int) -> list[dict]:
    ascending = mode == "buy"
    ranked = frame.sort_values("close", ascending=ascending).reset_index(drop=False)
    selected: list[dict] = []
    for _, row in ranked.iterrows():
        date = pd.Timestamp(row["date"])
        if any(abs((date - pd.Timestamp(item["date"])).days) < min_gap_days for item in selected):
            continue
        selected.append({"date": date, "price": float(row["close"]), "position": int(row["index"])})
        if len(selected) >= top_n:
            break
    return selected


def build_trade_timing_diagnostics(
    run_dir: Path,
    *,
    min_gap_days: int = 10,
    window_days: int = 5,
    top_n: int = 3,
) -> pd.DataFrame:
    trade_path = run_dir / "governance_trade_pairs.csv"
    if not trade_path.exists():
        raise FileNotFoundError(str(trade_path))
    trades = pd.read_csv(trade_path)
    if trades.empty:
        return pd.DataFrame()
    trades = trades[trades.get("close_reason", "").astype(str).ne("inventory_underflow")].copy()
    trades["entry_date"] = pd.to_datetime(trades["entry_date"], errors="coerce")
    trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="coerce")
    trades = trades.dropna(subset=["symbol", "entry_date", "exit_date"])
    if trades.empty:
        return pd.DataFrame()

    symbols = trades["symbol"].astype(str).drop_duplicates().tolist()
    prices = _load_prices(symbols, trades["entry_date"].min(), trades["exit_date"].max())
    price_groups = {symbol: group.reset_index(drop=True) for symbol, group in prices.groupby("symbol")}
    rows: list[dict] = []

    for _, trade in trades.iterrows():
        symbol = str(trade["symbol"])
        series = price_groups.get(symbol, pd.DataFrame())
        if series.empty:
            continue
        window = series[(series["date"] >= trade["entry_date"]) & (series["date"] <= trade["exit_date"])].reset_index(drop=True)
        if window.empty:
            continue
        dates = window["date"]
        cost_basis = float(pd.to_numeric(pd.Series([trade.get("cost_basis")]), errors="coerce").iloc[0])
        exit_net = float(pd.to_numeric(pd.Series([trade.get("exit_net_price")]), errors="coerce").iloc[0])
        shares = float(pd.to_numeric(pd.Series([trade.get("exit_shares")]), errors="coerce").iloc[0])

        best_sells = _rank_points(window, mode="sell", min_gap_days=min_gap_days, top_n=top_n)
        best_buys = _rank_points(window, mode="buy", min_gap_days=min_gap_days, top_n=top_n)
        max_rank = max(len(best_sells), len(best_buys), top_n)
        for rank in range(max_rank):
            sell = best_sells[rank] if rank < len(best_sells) else {}
            buy = best_buys[rank] if rank < len(best_buys) else {}
            sell_price = sell.get("price")
            buy_price = buy.get("price")
            rows.append(
                {
                    "trade_id": trade.get("trade_id", ""),
                    "symbol": symbol,
                    "entry_date": trade["entry_date"].date(),
                    "exit_date": trade["exit_date"].date(),
                    "rank": rank + 1,
                    "actual_cost_basis": cost_basis,
                    "actual_exit_net_price": exit_net,
                    "shares": shares,
                    "actual_realized_pnl": trade.get("realized_pnl_amount"),
                    "sell_reason": trade.get("sell_reason", trade.get("close_reason", "")),
                    "best_sell_date": sell.get("date").date() if sell else "",
                    "best_sell_window": _window_text(dates, sell["position"], window_days) if sell else "",
                    "best_sell_price": sell_price,
                    "sell_missed_pct_vs_cost": ((sell_price - exit_net) / cost_basis) if sell_price and cost_basis > 0 else pd.NA,
                    "sell_missed_amount": ((sell_price - exit_net) * shares) if sell_price else pd.NA,
                    "sell_was_better_than_actual": bool(sell_price is not None and sell_price > exit_net),
                    "best_buy_date": buy.get("date").date() if buy else "",
                    "best_buy_window": _window_text(dates, buy["position"], window_days) if buy else "",
                    "best_buy_price": buy_price,
                    "buy_missed_pct_vs_cost": ((cost_basis - buy_price) / cost_basis) if buy_price and cost_basis > 0 else pd.NA,
                    "buy_missed_amount": ((cost_basis - buy_price) * shares) if buy_price else pd.NA,
                    "buy_was_better_than_actual": bool(buy_price is not None and buy_price < cost_basis),
                    "min_gap_days": min_gap_days,
                    "tolerance_window_days": window_days,
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="", help="Directory containing governance_trade_pairs.csv")
    parser.add_argument("--min-gap-days", type=int, default=10)
    parser.add_argument("--window-days", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=3)
    args = parser.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir()
    diagnostics = build_trade_timing_diagnostics(
        run_dir,
        min_gap_days=args.min_gap_days,
        window_days=args.window_days,
        top_n=args.top_n,
    )
    output_path = run_dir / "governance_trade_timing_opportunities.csv"
    diagnostics.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"run_dir={run_dir}")
    print(f"rows={len(diagnostics)}")
    print(f"output={output_path}")
    if not diagnostics.empty:
        print(diagnostics.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
