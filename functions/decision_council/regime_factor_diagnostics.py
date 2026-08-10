"""Read-only factor and family diagnostics conditioned on factual market states.

This module deliberately distinguishes the saved audit-sample factor proposals
from the wider candidate-gate family scores.  It never grants trading authority:
full-universe rolling OOS evidence is a separate research gate.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = (5, 10, 20)
FAMILY_PREFIX = "cabinet_family_"
FAMILY_SUFFIX = "_score"
DAILY_METRIC_COLUMNS = [
    "date", "rank_ic", "sample_count", "direction_accuracy",
    "top_bottom_spread", "score_scope", "score_level", "score_name",
    "economic_family", "module", "horizon_days", "state_dimension",
    "state_label",
]
PARTITION_MANIFEST_COLUMNS = [
    "partition", "row_count", "date_count", "first_date", "last_date",
    "family_count", "size_bytes", "sha256",
]
STABILITY_COLUMNS = [
    "score_scope", "score_level", "score_name", "economic_family", "module",
    "horizon_days", "calendar_month", "observed_days", "observed_rows",
    "mean_daily_rank_ic", "positive_ic_day_ratio", "mean_top_bottom_spread",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normal_two_sided_p(z_value: float) -> float:
    if not np.isfinite(z_value):
        return np.nan
    return float(math.erfc(abs(float(z_value)) / math.sqrt(2.0)))


def _newey_west_mean_se(values: pd.Series, lag: int | None = None) -> float:
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    count = len(array)
    if count < 3:
        return np.nan
    lag = int(min(lag if lag is not None else max(round(count ** (1 / 3)), 1), count - 1))
    centered = array - array.mean()
    long_run_variance = float(np.dot(centered, centered) / count)
    for offset in range(1, lag + 1):
        covariance = float(np.dot(centered[offset:], centered[:-offset]) / count)
        long_run_variance += 2.0 * (1.0 - offset / (lag + 1.0)) * covariance
    return float(math.sqrt(max(long_run_variance, 0.0) / count))


def _benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(p_values, errors="coerce")
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = numeric.dropna().clip(0.0, 1.0)
    if valid.empty:
        return result
    ordered = valid.sort_values()
    total = len(ordered)
    adjusted = np.minimum.accumulate(
        (ordered.to_numpy(dtype=float) * total / np.arange(1, total + 1))[::-1]
    )[::-1]
    result.loc[ordered.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def _daily_metrics(
    frame: pd.DataFrame,
    *,
    score_column: str,
    outcome_column: str,
    minimum_names: int = 10,
) -> pd.DataFrame:
    rows: list[dict] = []
    required = ["date", "symbol", score_column, outcome_column]
    data = frame.loc[:, required].copy()
    data[score_column] = pd.to_numeric(data[score_column], errors="coerce")
    data[outcome_column] = pd.to_numeric(data[outcome_column], errors="coerce")
    data = data.dropna(subset=required)
    for date, group in data.groupby("date", sort=True):
        if len(group) < int(minimum_names):
            continue
        score = group[score_column]
        outcome = group[outcome_column]
        if score.nunique() < 2 or outcome.nunique() < 2:
            continue
        rank_ic = score.corr(outcome, method="spearman")
        score_median = float(score.median())
        outcome_median = float(outcome.median())
        score_side = np.sign(score - score_median)
        outcome_side = np.sign(outcome - outcome_median)
        comparable = score_side.ne(0) & outcome_side.ne(0)
        direction_accuracy = float(score_side[comparable].eq(outcome_side[comparable]).mean()) if comparable.any() else np.nan
        percentile = score.rank(method="first", pct=True)
        top = outcome[percentile.gt(0.8)]
        bottom = outcome[percentile.le(0.2)]
        rows.append(
            {
                "date": pd.Timestamp(date),
                "rank_ic": float(rank_ic),
                "sample_count": int(len(group)),
                "direction_accuracy": direction_accuracy,
                "top_bottom_spread": float(top.mean() - bottom.mean()) if not top.empty and not bottom.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def summarize_daily_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarize daily IC with autocorrelation-robust inference and FDR."""
    if daily.empty:
        return pd.DataFrame()
    keys = [
        "score_scope", "score_level", "score_name", "economic_family", "module",
        "horizon_days", "state_dimension", "state_label",
    ]
    rows: list[dict] = []
    for group_key, group in daily.groupby(keys, dropna=False, sort=True):
        ic = pd.to_numeric(group["rank_ic"], errors="coerce").dropna()
        se = _newey_west_mean_se(ic)
        mean_ic = float(ic.mean()) if not ic.empty else np.nan
        z_value = mean_ic / se if np.isfinite(se) and se > 0 else np.nan
        standard_deviation = float(ic.std(ddof=1)) if len(ic) > 1 else np.nan
        row = dict(zip(keys, group_key))
        row.update(
            {
                "first_date": pd.to_datetime(group["date"]).min(),
                "last_date": pd.to_datetime(group["date"]).max(),
                "observed_days": int(group["date"].nunique()),
                "observed_rows": int(pd.to_numeric(group["sample_count"], errors="coerce").sum()),
                "mean_daily_rank_ic": mean_ic,
                "std_daily_rank_ic": standard_deviation,
                "ic_ir": mean_ic / standard_deviation if np.isfinite(standard_deviation) and standard_deviation > 0 else np.nan,
                "positive_ic_day_ratio": float(ic.gt(0).mean()) if not ic.empty else np.nan,
                "mean_direction_accuracy": float(pd.to_numeric(group["direction_accuracy"], errors="coerce").mean()),
                "mean_top_bottom_spread": float(pd.to_numeric(group["top_bottom_spread"], errors="coerce").mean()),
                "newey_west_se": se,
                "newey_west_z": z_value,
                "p_value": _normal_two_sided_p(z_value),
                "ci95_lower": mean_ic - 1.96 * se if np.isfinite(se) else np.nan,
                "ci95_upper": mean_ic + 1.96 * se if np.isfinite(se) else np.nan,
            }
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    fdr_keys = ["score_scope", "score_level", "horizon_days", "state_dimension", "state_label"]
    summary["fdr_q_value"] = summary.groupby(fdr_keys, dropna=False)["p_value"].transform(_benjamini_hochberg)
    summary["fdr_10pct_pass"] = summary["fdr_q_value"].le(0.10)
    summary["minimum_30_days_pass"] = summary["observed_days"].ge(30)
    summary["diagnostic_only"] = True
    return summary.sort_values(keys).reset_index(drop=True)


def _attach_states(daily: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    merged = daily.merge(states, on="date", how="left", validate="many_to_one")
    parts = []
    for dimension, column in (
        ("all", None),
        ("safety_structural_state", "safety_structural_state"),
        ("safety_policy_band", "safety_policy_band"),
    ):
        part = merged.copy()
        part["state_dimension"] = dimension
        part["state_label"] = "all" if column is None else part[column].fillna("unknown").astype(str)
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def _score_diagnostics(
    scores: pd.DataFrame,
    outcomes: pd.DataFrame,
    states: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    score_scope: str,
    score_level: str,
) -> pd.DataFrame:
    base = scores.merge(outcomes, on=["date", "symbol"], how="inner", validate="many_to_one")
    meta = metadata.set_index("score_name").to_dict("index") if not metadata.empty else {}
    rows = []
    for score_name, group in base.groupby("score_name", sort=True):
        details = meta.get(str(score_name), {})
        for horizon in HORIZONS:
            daily = _daily_metrics(group, score_column="score", outcome_column=f"forward_return_{horizon}d")
            if daily.empty:
                continue
            daily["score_scope"] = score_scope
            daily["score_level"] = score_level
            daily["score_name"] = str(score_name)
            daily["economic_family"] = str(details.get("economic_family", score_name if score_level == "family" else "unknown"))
            daily["module"] = str(details.get("module", score_name if score_level == "family" else "unknown"))
            daily["horizon_days"] = int(horizon)
            rows.append(_attach_states(daily, states))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _load_partitioned_family_scores(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    partition_dir = run_dir / "_audit" / "cg"
    files = sorted(partition_dir.glob("cg_*.csv"))
    frames = []
    manifest_rows = []
    for path in files:
        header = pd.read_csv(path, nrows=0)
        family_columns = [column for column in header.columns if column.startswith(FAMILY_PREFIX) and column.endswith(FAMILY_SUFFIX)]
        usecols = ["signal_date", "symbol", *family_columns]
        frame = pd.read_csv(path, usecols=usecols)
        frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce")
        frames.append(frame)
        manifest_rows.append(
            {
                "partition": path.name,
                "row_count": int(len(frame)),
                "date_count": int(frame["signal_date"].nunique()),
                "first_date": frame["signal_date"].min(),
                "last_date": frame["signal_date"].max(),
                "family_count": int(len(family_columns)),
                "size_bytes": int(path.stat().st_size),
                "sha256": _sha256(path),
            }
        )
    if not frames:
        return (
            pd.DataFrame(columns=["date", "symbol", "score_name", "score"]),
            pd.DataFrame(manifest_rows, columns=PARTITION_MANIFEST_COLUMNS),
        )
    wide = pd.concat(frames, ignore_index=True)
    family_columns = [column for column in wide.columns if column.startswith(FAMILY_PREFIX) and column.endswith(FAMILY_SUFFIX)]
    long = wide.melt(id_vars=["signal_date", "symbol"], value_vars=family_columns, var_name="score_name", value_name="score")
    long["score_name"] = long["score_name"].str.removeprefix(FAMILY_PREFIX).str.removesuffix(FAMILY_SUFFIX)
    return (
        long.rename(columns={"signal_date": "date"}),
        pd.DataFrame(manifest_rows, columns=PARTITION_MANIFEST_COLUMNS),
    )


def build_regime_factor_diagnostics(run_dir: str | Path, output_dir: str | Path | None = None) -> dict:
    run_dir = Path(run_dir).resolve()
    output_dir = Path(output_dir).resolve() if output_dir is not None else run_dir / "regime_factor_diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)

    outcome_path = run_dir / "governance_layer_validation_candidate_detail.csv"
    daily_path = run_dir / "governance_daily_result.csv"
    proposal_path = run_dir / "governance_alpha_proposals.csv"
    semantic_path = run_dir / "governance_factor_semantic_contract.csv"
    outcomes = pd.read_csv(
        outcome_path,
        usecols=["signal_date", "symbol", "forward_return_5d", "forward_return_10d", "forward_return_20d"],
    ).rename(columns={"signal_date": "date"})
    outcomes["date"] = pd.to_datetime(outcomes["date"], errors="coerce")
    outcomes = outcomes.drop_duplicates(["date", "symbol"], keep="last")

    daily = pd.read_csv(daily_path, usecols=["date", "regime_name", "policy_band_state"])
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    states = daily.rename(
        columns={"regime_name": "safety_structural_state", "policy_band_state": "safety_policy_band"}
    ).drop_duplicates("date", keep="last")

    semantic = pd.read_csv(semantic_path)
    factor_metadata = semantic.rename(columns={"factor_name": "score_name"})[
        ["score_name", "economic_family", "module"]
    ].drop_duplicates("score_name", keep="last")
    proposals = pd.read_csv(proposal_path, usecols=["decision_date", "symbol", "model_name", "predicted_return_5d"])
    proposals = proposals.rename(
        columns={"decision_date": "date", "model_name": "score_name", "predicted_return_5d": "score"}
    )
    proposals["date"] = pd.to_datetime(proposals["date"], errors="coerce")

    family_scores, partition_manifest = _load_partitioned_family_scores(run_dir)
    family_names = sorted(family_scores["score_name"].dropna().astype(str).unique()) if not family_scores.empty else []
    family_metadata = pd.DataFrame(
        [{"score_name": name, "economic_family": name, "module": name} for name in family_names]
    )

    factor_daily = _score_diagnostics(
        proposals, outcomes, states, factor_metadata,
        score_scope="proposal_audit_conditional", score_level="factor",
    )
    family_daily = _score_diagnostics(
        family_scores, outcomes, states, family_metadata,
        score_scope="candidate_gate_conditional", score_level="family",
    )
    daily_metrics = pd.concat([factor_daily, family_daily], ignore_index=True)
    if daily_metrics.empty:
        daily_metrics = pd.DataFrame(columns=DAILY_METRIC_COLUMNS)
    summary = summarize_daily_metrics(daily_metrics)
    if summary.empty:
        summary = pd.DataFrame(
            columns=[
                "score_scope", "score_level", "score_name",
                "economic_family", "module", "horizon_days",
                "state_dimension", "state_label", "first_date", "last_date",
                "observed_days", "observed_rows", "mean_daily_rank_ic",
                "std_daily_rank_ic", "ic_ir", "positive_ic_day_ratio",
                "mean_direction_accuracy", "mean_top_bottom_spread",
                "newey_west_se", "newey_west_z", "p_value", "ci95_lower",
                "ci95_upper", "fdr_q_value", "fdr_10pct_pass",
                "minimum_30_days_pass", "diagnostic_only",
            ]
        )

    stability = daily_metrics.copy()
    if not stability.empty:
        stability["calendar_month"] = pd.to_datetime(stability["date"]).dt.to_period("M").astype(str)
        stability = (
            stability.groupby(
                ["score_scope", "score_level", "score_name", "economic_family", "module", "horizon_days", "calendar_month"],
                dropna=False,
            )
            .agg(observed_days=("date", "nunique"), observed_rows=("sample_count", "sum"), mean_daily_rank_ic=("rank_ic", "mean"), positive_ic_day_ratio=("rank_ic", lambda x: float(pd.Series(x).gt(0).mean())), mean_top_bottom_spread=("top_bottom_spread", "mean"))
            .reset_index()
        )
    else:
        stability = pd.DataFrame(columns=STABILITY_COLUMNS)

    daily_metrics.to_csv(output_dir / "governance_regime_factor_ic_daily.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "governance_regime_factor_summary.csv", index=False, encoding="utf-8-sig")
    summary[summary["score_level"].eq("family")].to_csv(
        output_dir / "governance_regime_factor_family_summary.csv", index=False, encoding="utf-8-sig"
    )
    stability.to_csv(output_dir / "governance_regime_factor_stability.csv", index=False, encoding="utf-8-sig")
    partition_manifest.to_csv(output_dir / "governance_candidate_gate_partition_manifest.csv", index=False, encoding="utf-8-sig")

    source_files = [outcome_path, daily_path, proposal_path, semantic_path]
    manifest = {
        "contract": "post_run_read_only_no_decision_authority",
        "source_run": str(run_dir),
        "output_dir": str(output_dir),
        "date_start": str(outcomes["date"].min().date()),
        "date_end": str(outcomes["date"].max().date()),
        "candidate_outcome_rows": int(len(outcomes)),
        "candidate_outcome_dates": int(outcomes["date"].nunique()),
        "proposal_rows": int(len(proposals)),
        "proposal_symbol_days": int(proposals[["date", "symbol"]].drop_duplicates().shape[0]),
        "factor_count": int(proposals["score_name"].nunique()),
        "candidate_partition_count": int(len(partition_manifest)),
        "candidate_partition_rows": int(partition_manifest["row_count"].sum()) if not partition_manifest.empty else 0,
        "candidate_partition_dates": int(family_scores["date"].nunique()) if not family_scores.empty else 0,
        "family_count": int(len(family_names)),
        "daily_metric_rows": int(len(daily_metrics)),
        "summary_rows": int(len(summary)),
        "scope_contracts": {
            "factor": "proposal_audit_conditional; saved proposal audit symbols only",
            "family": "candidate_gate_conditional; saved candidate-gate partitions joined to saved forward outcomes",
            "full_universe_oos": "unavailable; research gate remains blocked",
        },
        "inference": "daily cross-sectional Spearman IC; Newey-West mean SE; Benjamini-Hochberg FDR within scope/level/horizon/state",
        "source_sha256": {path.name: _sha256(path) for path in source_files},
        "research_gate": "blocked",
        "production_gate": "blocked",
    }
    (output_dir / "regime_factor_diagnostics_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return manifest
