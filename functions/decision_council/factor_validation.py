"""Post-run factor validation reports for governance research.

These diagnostics mirror common platform/research workflows: factor coverage,
Rank IC, quantile spread, turnover, and redundancy clusters. They are read-only
audits and do not alter orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import time

from functions.decision_council.factor_registry import build_factor_registry, factor_registry_snapshot


def build_factor_research_reports(
    feature_data: pd.DataFrame,
    *,
    registry: dict[str, dict] | None = None,
    horizons=(5, 10, 20),
    quantiles: int = 5,
    progress_callback=None,
    emit_quantile_rows: bool = True,
    cluster_max_factors: int = 300,
    max_rows: int | None = None,
    include_missing_factors: bool = True,
    deadline_monotonic: float | None = None,
) -> dict[str, pd.DataFrame]:
    registry = registry or build_factor_registry()
    snapshot = factor_registry_snapshot(registry)
    if feature_data is None or feature_data.empty:
        return {
            "governance_factor_registry_snapshot": snapshot,
            "governance_factor_validation_report": pd.DataFrame(),
            "governance_factor_ic_timeseries": pd.DataFrame(),
            "governance_factor_layer_return_report": pd.DataFrame(),
            "governance_factor_quantile_report": pd.DataFrame(),
            "governance_factor_cluster_report": pd.DataFrame(),
        }

    close_col = "close_nominal" if "close_nominal" in feature_data.columns else "close"
    if close_col not in feature_data.columns:
        return {
            "governance_factor_registry_snapshot": snapshot,
            "governance_factor_validation_report": pd.DataFrame(),
            "governance_factor_ic_timeseries": pd.DataFrame(),
            "governance_factor_layer_return_report": pd.DataFrame(),
            "governance_factor_quantile_report": pd.DataFrame(),
            "governance_factor_cluster_report": pd.DataFrame(),
        }

    factor_columns = [meta["raw_column"] for meta in registry.values() if meta.get("raw_column") in feature_data.columns]
    required = ["date", "symbol", close_col, *factor_columns]
    data = feature_data.loc[:, [column for column in required if column in feature_data.columns]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    data = data.dropna(subset=["date", "symbol", close_col]).sort_values(["symbol", "date"])
    if data.empty:
        return {
            "governance_factor_registry_snapshot": snapshot,
            "governance_factor_validation_report": pd.DataFrame(),
            "governance_factor_ic_timeseries": pd.DataFrame(),
            "governance_factor_layer_return_report": pd.DataFrame(),
            "governance_factor_quantile_report": pd.DataFrame(),
            "governance_factor_cluster_report": pd.DataFrame(),
        }
    original_row_count = int(len(data))
    data = _sample_factor_research_data(data, max_rows=max_rows)
    sampled_row_count = int(len(data))
    for horizon in horizons:
        data[f"forward_return_{int(horizon)}d"] = data.groupby("symbol", sort=False)[close_col].shift(-int(horizon)) / data[close_col] - 1.0

    validation_rows: list[dict] = []
    quantile_rows: list[dict] = []
    ic_rows: list[dict] = []
    registry_items = sorted(registry.items())
    total_factors = len(registry_items)
    for factor_index, (factor_name, meta) in enumerate(registry_items, start=1):
        _check_validation_deadline(deadline_monotonic, factor_name=factor_name, horizon=None)
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "factor_validation",
                    "factor_name": factor_name,
                    "current": factor_index,
                    "total": total_factors,
                }
            )
        raw_column = meta.get("raw_column")
        if raw_column not in data.columns:
            if include_missing_factors:
                validation_rows.append(_missing_factor_row(meta, "missing_feature_column"))
            continue
        factor_values = pd.to_numeric(data[raw_column], errors="coerce")
        direction_sign = _factor_direction_sign(meta.get("direction", "higher_better"))
        coverage_ratio = float(factor_values.notna().mean()) if len(factor_values) else 0.0
        for horizon in horizons:
            _check_validation_deadline(deadline_monotonic, factor_name=factor_name, horizon=horizon)
            fwd_col = f"forward_return_{int(horizon)}d"
            frame = data[["date", "symbol", raw_column, fwd_col]].copy()
            frame[raw_column] = pd.to_numeric(frame[raw_column], errors="coerce")
            frame[raw_column] = frame[raw_column] * direction_sign
            frame[fwd_col] = pd.to_numeric(frame[fwd_col], errors="coerce")
            frame = frame.dropna(subset=["date", "symbol", raw_column, fwd_col])
            if frame.empty:
                validation_rows.append(_empty_factor_row(meta, horizon, coverage_ratio, "missing_forward_outcomes"))
                continue
            ic_frame = _daily_rank_ic_frame(frame, raw_column, fwd_col)
            ic_series = ic_frame["rank_ic"] if "rank_ic" in ic_frame.columns else pd.Series(dtype=float)
            ic_rows.extend(ic_frame.assign(
                factor_name=meta["factor_name"],
                module=meta.get("module", "unknown"),
                candidate_pool=meta.get("candidate_pool", "unknown"),
                raw_column=raw_column,
                horizon_days=int(horizon),
            ).to_dict("records"))
            top_bottom = _top_bottom_spread(frame, raw_column, fwd_col, quantiles=quantiles)
            turnover = _top_bucket_turnover(frame, raw_column, quantiles=quantiles)
            validation_rows.append(
                _validation_row(
                    meta,
                    horizon=horizon,
                    coverage_ratio=coverage_ratio,
                    sample_count=len(frame),
                    ic_series=ic_series,
                    top_bottom=top_bottom,
                    turnover_mean=turnover,
                )
            )
            if emit_quantile_rows:
                quantile_rows.extend(_quantile_rows(meta, frame, raw_column, fwd_col, horizon, quantiles=quantiles))

    quantile_report = pd.DataFrame(quantile_rows)
    return {
        "governance_factor_registry_snapshot": snapshot,
        "governance_factor_validation_report": pd.DataFrame(validation_rows),
        "governance_factor_ic_timeseries": pd.DataFrame(ic_rows),
        "governance_factor_layer_return_report": quantile_report,
        "governance_factor_quantile_report": quantile_report,
        "governance_factor_cluster_report": build_factor_cluster_report(data, registry, max_factors=cluster_max_factors),
        "governance_factor_validation_runtime_audit": pd.DataFrame(
            [{
                "original_rows": original_row_count,
                "sampled_rows": sampled_row_count,
                "max_rows": int(max_rows) if max_rows is not None else None,
                "sampled": bool(max_rows is not None and original_row_count > int(max_rows)),
                "factor_count": int(len([meta for meta in registry.values() if meta.get("raw_column") in data.columns])),
                "horizons": "|".join(str(int(h)) for h in horizons),
                "emit_quantile_rows": bool(emit_quantile_rows),
                "cluster_max_factors": int(cluster_max_factors),
                "include_missing_factors": bool(include_missing_factors),
            }]
        ),
    }


def _check_validation_deadline(deadline_monotonic, *, factor_name: str, horizon) -> None:
    if deadline_monotonic is None:
        return
    if time.monotonic() > float(deadline_monotonic):
        raise TimeoutError(
            f"factor validation deadline exceeded at factor={factor_name}, horizon={horizon}"
        )


def _factor_direction_sign(direction) -> float:
    value = str(direction or "higher_better").strip().lower()
    if value in {"lower_better", "lower", "descending", "inverse", "-1", "-1.0"}:
        return -1.0
    if value in {"higher_better", "higher", "ascending", "long", "1", "1.0"}:
        return 1.0
    raise ValueError(f"Unsupported factor direction: {direction!r}")


def _sample_factor_research_data(data: pd.DataFrame, *, max_rows: int | None) -> pd.DataFrame:
    """Bound post-run research diagnostics without changing trading decisions."""
    if max_rows is None or int(max_rows) <= 0 or len(data) <= int(max_rows):
        return data
    limit = int(max_rows)
    dates = pd.Index(pd.to_datetime(data["date"], errors="coerce").dropna().sort_values().unique())
    if dates.empty:
        return data.sample(n=limit, random_state=17).sort_values(["symbol", "date"])
    median_rows_per_date = max(int(data.groupby("date", sort=False).size().median()), 1)
    target_dates = max(min(len(dates), limit // median_rows_per_date), 1)
    positions = np.linspace(0, len(dates) - 1, num=target_dates, dtype=int)
    selected_dates = set(pd.Timestamp(dates[int(pos)]) for pos in positions)
    sampled = data[data["date"].isin(selected_dates)].copy()
    if len(sampled) <= limit:
        return sampled.sort_values(["symbol", "date"])
    per_date = max(int(limit / max(len(selected_dates), 1)), 1)
    sampled = (
        sampled.groupby("date", group_keys=False, sort=True)
        .apply(lambda group: group.sample(n=min(len(group), per_date), random_state=17))
        .reset_index(drop=True)
    )
    if len(sampled) > limit:
        sampled = sampled.sample(n=limit, random_state=17)
    return sampled.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_factor_cluster_report(
    data: pd.DataFrame,
    registry: dict[str, dict],
    *,
    corr_threshold: float = 0.85,
    max_factors: int = 300,
) -> pd.DataFrame:
    if int(max_factors) <= 0:
        return pd.DataFrame()
    columns = [meta["raw_column"] for meta in registry.values() if meta.get("raw_column") in data.columns]
    if len(columns) > int(max_factors):
        formal = [
            meta["raw_column"]
            for meta in registry.values()
            if meta.get("candidate_pool") == "governance_formal" and meta.get("raw_column") in data.columns
        ]
        candidate = [column for column in columns if column not in set(formal)]
        columns = [*formal, *candidate[: max(int(max_factors) - len(formal), 0)]]
    if len(columns) < 2:
        return pd.DataFrame()
    sample = data[["date", "symbol", *columns]].copy()
    sample["row_key"] = sample["date"].astype(str) + "|" + sample["symbol"].astype(str)
    wide = sample.set_index("row_key")[columns].apply(pd.to_numeric, errors="coerce")
    valid_columns = [
        column
        for column in wide.columns
        if wide[column].notna().sum() >= 30 and wide[column].nunique(dropna=True) >= 2
    ]
    if len(valid_columns) < 2:
        return pd.DataFrame()
    wide = wide.loc[:, valid_columns]
    corr = wide.rank(pct=True).corr(method="spearman", min_periods=30).abs()
    name_by_column = {meta["raw_column"]: factor_name for factor_name, meta in registry.items()}
    module_by_column = {meta["raw_column"]: meta.get("module", "unknown") for meta in registry.values()}
    pool_by_column = {meta["raw_column"]: meta.get("candidate_pool", "unknown") for meta in registry.values()}
    rows = []
    visited: set[str] = set()
    cluster_id = 0
    for column in corr.columns:
        if column in visited:
            continue
        cluster_id += 1
        related = corr.index[corr[column].fillna(0.0).ge(float(corr_threshold))].tolist()
        if column not in related:
            related.append(column)
        for item in related:
            visited.add(item)
        representative = related[0]
        for item in related:
            peers = corr.loc[item, [peer for peer in related if peer != item]].dropna()
            rows.append(
                {
                    "cluster_id": int(cluster_id),
                    "factor_name": name_by_column.get(item, item),
                    "raw_column": item,
                    "module": module_by_column.get(item, "unknown"),
                    "candidate_pool": pool_by_column.get(item, "unknown"),
                    "cluster_size": int(len(related)),
                    "avg_abs_corr": float(peers.mean()) if not peers.empty else 0.0,
                    "max_abs_corr": float(peers.max()) if not peers.empty else 0.0,
                    "representative_factor": name_by_column.get(representative, representative),
                    "cluster_weight_cap": 0.25,
                    "drop_or_downweight": bool(len(related) > 1 and item != representative),
                    "reason": "rank_corr_cluster_ge_0.85" if len(related) > 1 else "standalone_factor",
                }
            )
    return pd.DataFrame(rows).sort_values(["cluster_size", "cluster_id", "factor_name"], ascending=[False, True, True]).reset_index(drop=True)


def _daily_rank_ic_frame(frame: pd.DataFrame, factor_col: str, fwd_col: str) -> pd.DataFrame:
    rows = []
    for date, group in frame.groupby("date", sort=True):
        if len(group) < 10:
            continue
        factor_rank = group[factor_col].rank()
        forward_rank = group[fwd_col].rank()
        if factor_rank.nunique(dropna=True) < 2 or forward_rank.nunique(dropna=True) < 2:
            continue
        corr = factor_rank.corr(forward_rank, method="pearson")
        if pd.notna(corr):
            rows.append({"date": pd.Timestamp(date), "rank_ic": float(corr), "sample_count": int(len(group))})
    return pd.DataFrame(rows)


def _top_bottom_spread(frame: pd.DataFrame, factor_col: str, fwd_col: str, *, quantiles: int) -> dict:
    tagged = _assign_quantiles(frame, factor_col, quantiles)
    if tagged.empty:
        return {"top": np.nan, "bottom": np.nan, "spread": np.nan, "hit_rate": np.nan}
    grouped = tagged.groupby("quantile")[fwd_col].mean()
    top = float(grouped.get(int(quantiles), np.nan))
    bottom = float(grouped.get(1, np.nan))
    daily = tagged.pivot_table(index="date", columns="quantile", values=fwd_col, aggfunc="mean")
    if int(quantiles) in daily.columns and 1 in daily.columns:
        daily_spread = daily[int(quantiles)] - daily[1]
        hit_rate = float((daily_spread.dropna() > 0.0).mean()) if not daily_spread.dropna().empty else np.nan
    else:
        hit_rate = np.nan
    return {"top": top, "bottom": bottom, "spread": top - bottom if np.isfinite(top) and np.isfinite(bottom) else np.nan, "hit_rate": hit_rate}


def _quantile_rows(meta: dict, frame: pd.DataFrame, factor_col: str, fwd_col: str, horizon: int, *, quantiles: int) -> list[dict]:
    tagged = _assign_quantiles(frame, factor_col, quantiles)
    if tagged.empty:
        return []
    rows = []
    daily_mean = tagged.groupby("date")[fwd_col].transform("mean")
    tagged["_forward_excess_return"] = pd.to_numeric(tagged[fwd_col], errors="coerce") - pd.to_numeric(daily_mean, errors="coerce")
    for (date, quantile), group in tagged.groupby(["date", "quantile"], dropna=False):
        returns = pd.to_numeric(group[fwd_col], errors="coerce").dropna()
        excess = pd.to_numeric(group["_forward_excess_return"], errors="coerce").dropna()
        rows.append(
            {
                "factor_name": meta["factor_name"],
                "module": meta.get("module", "unknown"),
                "candidate_pool": meta.get("candidate_pool", "unknown"),
                "date": pd.Timestamp(date),
                "horizon_days": int(horizon),
                "quantile": int(quantile),
                "member_count": int(len(returns)),
                "sample_count": int(len(returns)),
                "forward_return_mean": float(returns.mean()) if not returns.empty else np.nan,
                "forward_return_median": float(returns.median()) if not returns.empty else np.nan,
                "forward_excess_return_mean": float(excess.mean()) if not excess.empty else np.nan,
                "hit_rate": float((returns > 0.0).mean()) if not returns.empty else np.nan,
                "turnover": np.nan,
                "drawdown": _max_drawdown(returns) if not returns.empty else np.nan,
            }
        )
    return rows


def _assign_quantiles(frame: pd.DataFrame, factor_col: str, quantiles: int) -> pd.DataFrame:
    parts = []
    for _, group in frame.groupby("date", sort=True):
        clean = group.dropna(subset=[factor_col]).copy()
        if len(clean) < int(quantiles):
            continue
        pct_rank = clean[factor_col].rank(method="first", pct=True)
        clean["quantile"] = np.ceil(pct_rank * int(quantiles)).clip(1, int(quantiles)).astype(int)
        parts.append(clean)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _top_bucket_turnover(frame: pd.DataFrame, factor_col: str, *, quantiles: int) -> float:
    tagged = _assign_quantiles(frame, factor_col, quantiles)
    if tagged.empty:
        return np.nan
    previous: set[str] | None = None
    turnovers = []
    for _, group in tagged[tagged["quantile"].eq(int(quantiles))].groupby("date", sort=True):
        current = set(group["symbol"].astype(str))
        if previous is not None and (current or previous):
            overlap = len(current & previous)
            base = max(len(current | previous), 1)
            turnovers.append(1.0 - overlap / base)
        previous = current
    return float(np.mean(turnovers)) if turnovers else np.nan


def _validation_row(meta: dict, *, horizon: int, coverage_ratio: float, sample_count: int, ic_series: pd.Series, top_bottom: dict, turnover_mean: float) -> dict:
    rank_ic_mean = float(ic_series.mean()) if not ic_series.empty else np.nan
    rank_ic_std = float(ic_series.std(ddof=0)) if not ic_series.empty else np.nan
    ic_ir = abs(rank_ic_mean) / rank_ic_std if rank_ic_std and np.isfinite(rank_ic_std) and rank_ic_std > 1e-12 else np.nan
    positive_ratio = float((ic_series > 0.0).mean()) if not ic_series.empty else np.nan
    fail_reasons = []
    if coverage_ratio < float(meta.get("min_coverage", 0.60)):
        fail_reasons.append("coverage_below_threshold")
    if not np.isfinite(rank_ic_mean) or abs(rank_ic_mean) < float(meta.get("min_abs_rank_ic", 0.015)):
        fail_reasons.append("rank_ic_too_weak")
    if not np.isfinite(ic_ir) or ic_ir < float(meta.get("min_ic_ir", 0.20)):
        fail_reasons.append("ic_ir_too_weak")
    if not np.isfinite(positive_ratio) or positive_ratio < float(meta.get("min_rank_ic_positive_ratio", 0.52)):
        fail_reasons.append("positive_ic_ratio_too_low")
    if int(horizon) == 10 and (not np.isfinite(top_bottom.get("spread", np.nan)) or top_bottom.get("spread", np.nan) <= float(meta.get("min_top_bottom_spread_10d", 0.0))):
        fail_reasons.append("top_bottom_spread_10d_not_positive")
    if sample_count < int(meta.get("min_sample_count", 500)):
        fail_reasons.append("sample_count_below_threshold")
    return {
        "factor_name": meta["factor_name"],
        "module": meta.get("module", "unknown"),
        "candidate_pool": meta.get("candidate_pool", "unknown"),
        "raw_column": meta.get("raw_column", ""),
        "horizon_days": int(horizon),
        "coverage_ratio": float(coverage_ratio),
        "rank_ic_mean": rank_ic_mean,
        "rank_ic_std": rank_ic_std,
        "ic_ir": ic_ir,
        "rank_ic_positive_ratio": positive_ratio,
        "top_bucket_return": top_bottom.get("top", np.nan),
        "bottom_bucket_return": top_bottom.get("bottom", np.nan),
        "top_bottom_spread": top_bottom.get("spread", np.nan),
        "top_bottom_hit_rate": top_bottom.get("hit_rate", np.nan),
        "turnover_mean": turnover_mean,
        "max_drawdown_top_bucket": np.nan,
        "industry_exposure_max": np.nan,
        "size_corr": np.nan,
        "liquidity_corr": np.nan,
        "sample_count": int(sample_count),
        "pass_flag": not fail_reasons,
        "fail_reasons": "|".join(fail_reasons),
    }


def _missing_factor_row(meta: dict, reason: str) -> dict:
    row = _empty_factor_row(meta, 0, 0.0, reason)
    row["horizon_days"] = 0
    return row


def _empty_factor_row(meta: dict, horizon: int, coverage_ratio: float, reason: str) -> dict:
    return {
        "factor_name": meta["factor_name"],
        "module": meta.get("module", "unknown"),
        "candidate_pool": meta.get("candidate_pool", "unknown"),
        "raw_column": meta.get("raw_column", ""),
        "horizon_days": int(horizon),
        "coverage_ratio": float(coverage_ratio),
        "rank_ic_mean": np.nan,
        "rank_ic_std": np.nan,
        "ic_ir": np.nan,
        "rank_ic_positive_ratio": np.nan,
        "top_bucket_return": np.nan,
        "bottom_bucket_return": np.nan,
        "top_bottom_spread": np.nan,
        "top_bottom_hit_rate": np.nan,
        "turnover_mean": np.nan,
        "max_drawdown_top_bucket": np.nan,
        "industry_exposure_max": np.nan,
        "size_corr": np.nan,
        "liquidity_corr": np.nan,
        "sample_count": 0,
        "pass_flag": False,
        "fail_reasons": str(reason),
    }


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").dropna()).cumprod()
    if equity.empty:
        return np.nan
    return float((equity / equity.cummax() - 1.0).min())
