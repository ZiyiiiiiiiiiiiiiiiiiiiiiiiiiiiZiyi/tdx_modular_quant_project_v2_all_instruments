"""Full-stock-universe fixed-factor and rolling conditional OOS diagnostics."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pads

from functions.decision_council.regime_factor_diagnostics import _attach_states, summarize_daily_metrics


def _cross_sectional_ic_rows(frame: pd.DataFrame, factor_columns: list[str], horizon: int) -> list[dict]:
    rows: list[dict] = []
    outcome_column = f"forward_return_{horizon}d"
    for date, group in frame.groupby("date", sort=True):
        outcome = pd.to_numeric(group[outcome_column], errors="coerce")
        valid_outcome = outcome.notna()
        if valid_outcome.sum() < 30 or outcome[valid_outcome].nunique() < 2:
            continue
        factors = group.loc[valid_outcome, factor_columns].apply(pd.to_numeric, errors="coerce")
        outcome_rank = outcome[valid_outcome].rank(method="average")
        factor_rank = factors.rank(method="average")
        correlations = factor_rank.corrwith(outcome_rank, axis=0)
        counts = factors.notna().sum()
        for raw_column, rank_ic in correlations.items():
            if counts.get(raw_column, 0) < 30 or pd.isna(rank_ic):
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date), "raw_column": raw_column,
                    "horizon_days": int(horizon), "rank_ic": float(rank_ic),
                    "sample_count": int(counts[raw_column]),
                }
            )
    return rows


def build_rolling_conditional_selection(
    factor_daily: pd.DataFrame,
    *,
    minimum_train_days: int = 126,
    embargo_sessions: int = 20,
    minimum_state_days: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select one factor per family using only purged prior daily IC."""
    data = factor_daily.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    dates = pd.Index(sorted(data["date"].dropna().unique()))
    months = sorted(data["date"].dt.to_period("M").unique())
    selections = []
    evaluations = []
    for month in months:
        test = data[data["date"].dt.to_period("M").eq(month)]
        if test.empty:
            continue
        test_start = pd.Timestamp(test["date"].min())
        position = int(dates.searchsorted(test_start, side="left"))
        train_end_position = position - int(embargo_sessions) - 1
        if train_end_position < int(minimum_train_days) - 1:
            continue
        train_dates = dates[: train_end_position + 1][-int(minimum_train_days):]
        train = data[data["date"].isin(train_dates)]
        for horizon in sorted(test["horizon_days"].unique()):
            test_h = test[test["horizon_days"].eq(horizon)]
            train_h = train[train["horizon_days"].eq(horizon)]
            for state_label in sorted(test_h["safety_structural_state"].fillna("unknown").unique()):
                test_state = test_h[test_h["safety_structural_state"].fillna("unknown").eq(state_label)]
                train_state = train_h[train_h["safety_structural_state"].fillna("unknown").eq(state_label)]
                for family in sorted(test_state["economic_family"].dropna().unique()):
                    family_state = train_state[train_state["economic_family"].eq(family)]
                    state_day_count = int(family_state["date"].nunique())
                    fallback_used = state_day_count < int(minimum_state_days)
                    fit = train_h[train_h["economic_family"].eq(family)] if fallback_used else family_state
                    ranking = fit.groupby("score_name")["rank_ic"].agg(["mean", "count"]).query("count >= 20").sort_values(["mean", "count"], ascending=[False, False])
                    if ranking.empty:
                        continue
                    selected_factor = str(ranking.index[0])
                    selected_test = test_state[test_state["score_name"].eq(selected_factor)]
                    if selected_test.empty:
                        continue
                    selections.append(
                        {
                            "test_month": str(month), "horizon_days": int(horizon),
                            "state_label": state_label, "economic_family": family,
                            "selected_factor": selected_factor,
                            "train_start": pd.Timestamp(train_dates.min()), "train_end": pd.Timestamp(train_dates.max()),
                            "embargo_sessions": int(embargo_sessions), "train_state_days": state_day_count,
                            "state_fallback_to_all": bool(fallback_used),
                            "train_mean_rank_ic": float(ranking.iloc[0]["mean"]),
                            "train_observations": int(ranking.iloc[0]["count"]),
                        }
                    )
                    evaluations.append(
                        {
                            "test_month": str(month), "horizon_days": int(horizon),
                            "state_label": state_label, "economic_family": family,
                            "selected_factor": selected_factor,
                            "test_days": int(selected_test["date"].nunique()),
                            "test_mean_rank_ic": float(selected_test["rank_ic"].mean()),
                            "test_positive_ic_ratio": float(selected_test["rank_ic"].gt(0).mean()),
                            "test_sample_rows": int(selected_test["sample_count"].sum()),
                        }
                    )
    return pd.DataFrame(selections), pd.DataFrame(evaluations)


def build_full_universe_factor_oos(
    *,
    run_dir: str | Path,
    cache_manifest_path: str | Path,
    feature_path: str | Path,
    output_dir: str | Path,
) -> dict:
    run_dir = Path(run_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_manifest_path = Path(cache_manifest_path).resolve()
    cache_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
    cache_path = Path(cache_manifest["parquet_path"])
    feature_path = Path(feature_path).resolve()

    cabinet = json.loads(Path(cache_manifest["factor_cabinet_path"]).read_text(encoding="utf-8"))
    factor_meta = pd.DataFrame(cabinet["factors"])
    factor_meta = factor_meta.rename(columns={"factor_name": "score_name"})
    if "economic_family" not in factor_meta.columns:
        factor_meta["economic_family"] = factor_meta["family"]
    else:
        economic = factor_meta["economic_family"].astype("string")
        factor_meta["economic_family"] = economic.where(
            economic.notna() & economic.str.strip().ne(""),
            factor_meta["family"].astype("string"),
        )
    semantic_path = run_dir / "governance_factor_semantic_contract.csv"
    if semantic_path.exists():
        semantic = pd.read_csv(semantic_path, usecols=["factor_name", "economic_family"])
        semantic_map = semantic.drop_duplicates("factor_name").set_index("factor_name")["economic_family"]
        mapped_economic = factor_meta["score_name"].map(semantic_map)
        factor_meta["economic_family"] = mapped_economic.where(mapped_economic.notna(), factor_meta["economic_family"])
    factor_meta["module"] = factor_meta["module"].fillna("unknown").astype(str)
    raw_columns = [column for column in cache_manifest["raw_columns"] if column in set(factor_meta["raw_column"])]
    meta_by_raw = factor_meta.drop_duplicates("raw_column").set_index("raw_column")

    start = pd.Timestamp(cache_manifest["date_min"])
    end = pd.Timestamp(cache_manifest["date_max"])
    prices = pd.read_parquet(
        feature_path,
        columns=["date", "symbol", "close_nominal", "instrument_type"],
        filters=[("date", ">=", start), ("date", "<=", end)],
    )
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices = prices[prices["instrument_type"].astype(str).eq("stock")].copy()
    prices["close_nominal"] = pd.to_numeric(prices["close_nominal"], errors="coerce")
    prices = prices.dropna(subset=["date", "symbol", "close_nominal"]).sort_values(["symbol", "date"])
    for horizon in (5, 10, 20):
        prices[f"forward_return_{horizon}d"] = prices.groupby("symbol", sort=False)["close_nominal"].shift(-horizon) / prices["close_nominal"] - 1.0
    outcomes = prices[["date", "symbol", "forward_return_5d", "forward_return_10d", "forward_return_20d"]]

    daily_rows = []
    dataset = pads.dataset(cache_path, format="parquet")
    for fragment in sorted(dataset.get_fragments(), key=lambda item: str(item.path)):
        part = fragment.to_table(columns=["date", "symbol", *raw_columns]).to_pandas()
        part["date"] = pd.to_datetime(part["date"], errors="coerce")
        part = part.merge(outcomes, on=["date", "symbol"], how="inner", validate="one_to_one")
        for horizon in (5, 10, 20):
            daily_rows.extend(_cross_sectional_ic_rows(part, raw_columns, horizon))
    factor_daily = pd.DataFrame(daily_rows)
    factor_daily["score_name"] = factor_daily["raw_column"].map(meta_by_raw["score_name"])
    factor_daily["economic_family"] = factor_daily["raw_column"].map(meta_by_raw["economic_family"])
    factor_daily["module"] = factor_daily["raw_column"].map(meta_by_raw["module"])
    directions = factor_daily["raw_column"].map(meta_by_raw.get("direction", pd.Series("higher_better", index=meta_by_raw.index))).fillna("higher_better")
    factor_daily["rank_ic"] = factor_daily["rank_ic"] * np.where(directions.eq("lower_better"), -1.0, 1.0)

    states = pd.read_csv(run_dir / "governance_daily_result.csv", usecols=["date", "regime_name", "policy_band_state"])
    states["date"] = pd.to_datetime(states["date"], errors="coerce")
    states = states.rename(columns={"regime_name": "safety_structural_state", "policy_band_state": "safety_policy_band"}).drop_duplicates("date")
    factor_daily = factor_daily.merge(states, on="date", how="left", validate="many_to_one")

    factor_for_summary = factor_daily.assign(
        score_scope="full_stock_universe_fixed_factor_oos", score_level="factor",
        direction_accuracy=np.nan, top_bottom_spread=np.nan,
    )
    factor_summary_daily = _attach_states(
        factor_for_summary.drop(columns=["safety_structural_state", "safety_policy_band"]), states
    )
    factor_summary = summarize_daily_metrics(factor_summary_daily)

    family_daily = factor_daily.groupby(
        ["date", "horizon_days", "economic_family", "safety_structural_state", "safety_policy_band"], dropna=False,
    ).agg(rank_ic=("rank_ic", "mean"), sample_count=("sample_count", "median"), factor_count=("score_name", "nunique")).reset_index()
    family_daily["score_name"] = family_daily["economic_family"]
    family_daily["module"] = family_daily["economic_family"]
    family_daily["score_scope"] = "full_stock_universe_fixed_factor_oos"
    family_daily["score_level"] = "family_equal_factor_mean"
    family_daily["direction_accuracy"] = np.nan
    family_daily["top_bottom_spread"] = np.nan
    family_summary = summarize_daily_metrics(
        _attach_states(family_daily.drop(columns=["safety_structural_state", "safety_policy_band"]), states)
    )

    selections, rolling = build_rolling_conditional_selection(factor_daily)
    factor_daily.to_csv(output_dir / "full_universe_factor_ic_daily.csv", index=False, encoding="utf-8-sig")
    factor_summary.to_csv(output_dir / "full_universe_factor_summary.csv", index=False, encoding="utf-8-sig")
    family_daily.to_csv(output_dir / "full_universe_family_ic_daily.csv", index=False, encoding="utf-8-sig")
    family_summary.to_csv(output_dir / "full_universe_family_summary.csv", index=False, encoding="utf-8-sig")
    selections.to_csv(output_dir / "rolling_conditional_factor_selections.csv", index=False, encoding="utf-8-sig")
    rolling.to_csv(output_dir / "rolling_conditional_factor_evaluation.csv", index=False, encoding="utf-8-sig")

    manifest = {
        "contract": "full_stock_universe_fixed_factor_oos_and_rolling_conditional_research",
        "source_run": str(run_dir), "factor_cache_manifest": str(cache_manifest_path),
        "factor_cache_contract": cache_manifest.get("cache_version"),
        "factor_cabinet_hash": cache_manifest.get("cabinet_manifest_hash"),
        "factor_selection_latest_upstream_end": "2024-12-31",
        "oos_start": str(start.date()), "oos_end": str(end.date()),
        "stock_price_rows": int(len(prices)), "stock_symbols": int(prices["symbol"].nunique()),
        "factor_count": int(factor_daily["score_name"].nunique()),
        "daily_factor_ic_rows": int(len(factor_daily)),
        "rolling_selection_rows": int(len(selections)), "rolling_evaluation_rows": int(len(rolling)),
        "rolling_contract": "126 prior sessions, 20-session embargo, monthly test; state fallback requires fewer than 20 state days",
        "decision_authority": "none_research_only",
        "research_gate": "pending_result_review",
        "production_gate": "blocked",
    }
    (output_dir / "full_universe_factor_oos_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
