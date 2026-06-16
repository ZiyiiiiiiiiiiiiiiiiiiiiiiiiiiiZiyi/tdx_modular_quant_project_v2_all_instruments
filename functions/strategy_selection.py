# -*- coding: utf-8 -*-
import pandas as pd

from config import FEATURE_DAILY_PARQUET, PROCESSED_DIR, REPORT_DIR
from functions.date_window import assert_date_window, filter_date_window, window_identity


def get_rebalance_dates(df, freq="ME"):
    """Return actual trading dates used for rebalancing."""
    dates = df[["date"]].drop_duplicates().sort_values("date").copy()
    dates["date"] = pd.to_datetime(dates["date"])

    if freq in {"D", "DAILY"}:
        rebalance_dates = dates["date"]
    elif freq == "ME":
        rebalance_dates = dates.groupby(dates["date"].dt.to_period("M"))["date"].max()
    elif freq == "QE":
        rebalance_dates = dates.groupby(dates["date"].dt.to_period("Q"))["date"].max()
    elif freq.startswith("W"):
        rebalance_dates = dates.groupby(dates["date"].dt.to_period("W"))["date"].max()
    else:
        raise ValueError("Unsupported rebalance frequency. Use 'D', 'ME', 'QE', or 'W-FRI'.")

    return rebalance_dates.reset_index(drop=True)


def select_instruments_by_score(
    df,
    score_col="score_mom_lowvol",
    top_n=20,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    require_trading=True,
    exclude_abnormal=True,
    ascending=False,
):
    """Select instruments by score on rebalance dates."""
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])

    if start_date is not None:
        data = data[data["date"] >= pd.to_datetime(start_date)]
    if end_date is not None:
        data = data[data["date"] <= pd.to_datetime(end_date)]
    if include_types is not None and "instrument_type" in data.columns:
        data = data[data["instrument_type"].isin(include_types)]
    if require_trading and "is_trading" in data.columns:
        data = data[data["is_trading"] == True]
    if exclude_abnormal and "abnormal_jump" in data.columns:
        data = data[data["abnormal_jump"] == False]

    data = data.dropna(subset=[score_col, "close", "symbol"])
    if data.empty:
        print("Warning: no available data after strategy filters.")
        return pd.DataFrame()

    rebalance_dates = get_rebalance_dates(data, freq=freq)
    rows = []

    for rebalance_date in rebalance_dates:
        one_day = data[data["date"] == rebalance_date].copy()
        if one_day.empty:
            continue

        one_day = one_day.sort_values(score_col, ascending=ascending)
        selected = one_day.head(top_n).copy()
        if selected.empty:
            continue

        selected["rebalance_date"] = rebalance_date
        selected["rank"] = range(1, len(selected) + 1)
        selected["score"] = selected[score_col]
        selected["weight"] = 1.0 / len(selected)

        keep_cols = [
            "rebalance_date",
            "rank",
            "symbol",
            "code",
            "market",
            "instrument_type",
            "score",
            "weight",
            "close",
        ]
        for col in keep_cols:
            if col not in selected.columns:
                selected[col] = pd.NA

        rows.append(selected[keep_cols])

    if not rows:
        print("Warning: no strategy selection rows generated.")
        return pd.DataFrame()

    selection = pd.concat(rows, ignore_index=True)
    return selection.sort_values(["rebalance_date", "rank"])


def run_strategy_selection(
    score_col="score_mom_lowvol",
    top_n=20,
    freq="ME",
    include_types=("stock", "etf_fund"),
    start_date=None,
    end_date=None,
    strategy_name="strategy_selection",
    df_features=None,
    df_selection=None,
):
    """
    Generate or persist one strategy selection table.

    Multi-strategy mode writes data/processed/{strategy_name}.parquet and a
    matching summary report.
    """
    output_file = PROCESSED_DIR / f"{strategy_name}.parquet"
    summary_file = REPORT_DIR / f"strategy_selection_summary_{strategy_name}.csv"

    if df_selection is not None:
        selection = df_selection.copy()
    else:
        if df_features is None:
            df_features = pd.read_parquet(FEATURE_DAILY_PARQUET)
        selection = select_instruments_by_score(
            df=df_features,
            score_col=score_col,
            top_n=top_n,
            freq=freq,
            include_types=include_types,
            start_date=start_date,
            end_date=end_date,
        )

    if "rebalance_date" in selection.columns:
        selection = filter_date_window(
            selection,
            "rebalance_date",
            start_date=start_date,
            end_date=end_date,
        )
        assert_date_window(
            selection,
            "rebalance_date",
            start_date=start_date,
            end_date=end_date,
            label=f"strategy selection {strategy_name}",
        )
    elif not selection.empty:
        raise ValueError(f"Strategy selection {strategy_name} is missing rebalance_date")
    identity = window_identity(start_date, end_date)
    selection["configured_start_date"] = identity["start_date"]
    selection["configured_end_date"] = identity["end_date"]
    selection["date_window"] = f"{identity['start_date'] or '-'} -> {identity['end_date'] or '-'}"
    if "rank" in selection.columns and "rebalance_date" in selection.columns:
        selection = selection.sort_values(["rebalance_date", "rank"])

    selection.to_parquet(output_file, index=False)

    summary = _build_selection_summary(
        selection=selection,
        strategy_name=strategy_name,
        score_col=score_col,
    )
    summary["configured_start_date"] = identity["start_date"]
    summary["configured_end_date"] = identity["end_date"]

    summary.to_csv(summary_file, index=False, encoding="utf-8-sig")

    print("Saved strategy selection:", output_file)
    print("Saved strategy summary:", summary_file)
    print("Selection shape:", selection.shape)

    return selection


def _build_selection_summary(selection, *, strategy_name, score_col):
    base_columns = [
        "strategy_name",
        "rebalance_date",
        "selected_count",
        "avg_score",
        "min_score",
        "max_score",
        "signal_candidate_count",
        "signal_trigger_count",
        "signal_trigger_rate",
        "strategy_params_version",
        "strategy_params_hash",
        "requested_model",
        "runtime_model",
        "training_window_days",
        "training_sample_count",
        "label_purge_periods",
        "prior_p",
        "prior_strength",
        "prior_source",
        "posterior_alpha",
        "posterior_beta",
        "posterior_sample_count",
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "price_basis_selection_mode",
    ]
    if selection.empty:
        return pd.DataFrame(columns=base_columns)

    score_agg_col = "score" if "score" in selection.columns else score_col
    agg_spec = {
        "selected_count": ("symbol", "count"),
        "avg_score": (score_agg_col, "mean"),
        "min_score": (score_agg_col, "min"),
        "max_score": (score_agg_col, "max"),
    }
    first_value_cols = [
        "signal_candidate_count",
        "signal_trigger_count",
        "signal_trigger_rate",
        "strategy_params_version",
        "strategy_params_hash",
        "requested_model",
        "runtime_model",
        "training_window_days",
        "training_sample_count",
        "label_purge_periods",
        "prior_p",
        "prior_strength",
        "prior_source",
        "posterior_alpha",
        "posterior_beta",
        "posterior_sample_count",
        "adjustment_coverage_ratio",
        "adjustment_coverage_threshold",
        "price_basis_selection_mode",
    ]
    for column in first_value_cols:
        if column in selection.columns:
            agg_spec[column] = (column, "first")

    summary = selection.groupby("rebalance_date").agg(**agg_spec).reset_index()
    summary.insert(0, "strategy_name", strategy_name)
    if "signal_trigger_rate" not in summary.columns:
        candidate = pd.to_numeric(summary.get("signal_candidate_count"), errors="coerce")
        trigger = pd.to_numeric(summary.get("signal_trigger_count"), errors="coerce")
        if candidate is not None and trigger is not None:
            summary["signal_trigger_rate"] = trigger / candidate.replace(0, pd.NA)
    return summary


if __name__ == "__main__":
    run_strategy_selection(
        score_col="score_mom_lowvol",
        top_n=20,
        freq="ME",
        include_types=("stock", "etf_fund"),
        start_date=None,
        end_date=None,
    )
