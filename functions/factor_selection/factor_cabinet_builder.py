"""Build the final factor cabinet consumed by the state machine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

import pandas as pd


DEFAULT_V1_CONTRACT = Path(
    "results/decision_council/fast_factor_judge/"
    "hs300_csi500_a500_strict/run20260705_180001_095951/factor_pool_contract.csv"
)
DEFAULT_APPEAL_ROOT = Path("results/decision_council/factor_appeal_judge")
OUTPUT_ROOT = Path("results/factor_cabinet")
ROLE_QUOTA = {
    "strict_entry_alpha": (6, 40),
    "proxy_entry_alpha": (20, 40),
    "timing_filter": (15, 25),
    "risk_override": (15, 25),
    "liquidity_filter": (10, 20),
    "hold_validation": (10, 20),
}


def build_factor_cabinet(
    *,
    v1_contract_path: str | Path = DEFAULT_V1_CONTRACT,
    appeal_run_dir: str | Path | None = None,
    output_root: str | Path = OUTPUT_ROOT,
    min_factors: int = 60,
    max_factors: int = 120,
) -> dict[str, Path]:
    v1 = _load_v1(v1_contract_path)
    v2 = _load_v2(appeal_run_dir)
    candidates = pd.concat([v1, v2], ignore_index=True)
    if candidates.empty:
        raise ValueError("No cabinet candidates available")
    candidates["cabinet_score"] = candidates.apply(_cabinet_score, axis=1)
    deduped, dedup_report = _near_relative_dedup(candidates)
    deduped = _assign_proxy_entry_roles(deduped)
    selected, quota_report = _select_by_role(deduped, min_factors=min_factors, max_factors=max_factors)
    run_id = datetime.now().strftime("run%Y%m%d_%H%M%S_%f")
    output = Path(output_root) / run_id
    output.mkdir(parents=True, exist_ok=False)
    selected.to_csv(output / "factor_cabinet.csv", index=False, encoding="utf-8-sig")
    (output / "factor_cabinet.json").write_text(
        json.dumps({"run_id": run_id, "factors": selected.to_dict("records")}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    dedup_report.to_csv(output / "near_relative_dedup_report.csv", index=False, encoding="utf-8-sig")
    _correlation_cluster_placeholder(selected).to_csv(output / "correlation_cluster_report.csv", index=False, encoding="utf-8-sig")
    quota_report.to_csv(output / "role_quota_report.csv", index=False, encoding="utf-8-sig")
    (output / "factor_cabinet_report.md").write_text(_render_report(selected, quota_report), encoding="utf-8")
    return {
        "output_dir": output,
        "factor_cabinet_json": output / "factor_cabinet.json",
        "factor_cabinet_csv": output / "factor_cabinet.csv",
        "factor_cabinet_report": output / "factor_cabinet_report.md",
        "near_relative_dedup_report": output / "near_relative_dedup_report.csv",
        "correlation_cluster_report": output / "correlation_cluster_report.csv",
        "role_quota_report": output / "role_quota_report.csv",
    }


def _load_v1(path: str | Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    data = data[data.get("admitted", False).astype(str).str.lower().eq("true")].copy()
    if data.empty:
        return pd.DataFrame()
    data["source"] = "v1_fast_strict"
    data["decision"] = data["verdict"]
    data["cabinet_role"] = data.apply(_cabinet_role_from_v1, axis=1)
    data["strict_entry_alpha"] = data["cabinet_role"].eq("strict_entry_alpha")
    return data


def _load_v2(appeal_run_dir: str | Path | None) -> pd.DataFrame:
    run_dir = _resolve_appeal_run_dir(appeal_run_dir)
    if run_dir is None:
        return pd.DataFrame()
    parts = []
    for filename in ("admitted_v2.csv", "watchlist_v2.csv"):
        path = run_dir / filename
        if path.exists():
            parts.append(pd.read_csv(path))
    parts = [part for part in parts if part is not None and not part.empty]
    if not parts:
        return pd.DataFrame()
    data = pd.concat(parts, ignore_index=True)
    data["source"] = "v2_appeal"
    data["decision"] = data["new_decision"]
    data["module"] = data.get("factor_type", "")
    data["family"] = data.get("factor_family", "")
    data["role"] = data.get("new_role", "")
    data["cabinet_role"] = data["new_role"].map(lambda role: "proxy_entry_alpha" if str(role) == "entry_alpha_proxy" else str(role))
    data["near_relative_key"] = data["factor_type"].astype(str) + ":" + data["factor_family"].astype(str) + ":" + data["factor_name"].astype(str)
    data["score"] = pd.to_numeric(data.get("ic_ir"), errors="coerce").fillna(0.0)
    data["strict_entry_alpha"] = False
    return data


def _resolve_appeal_run_dir(appeal_run_dir: str | Path | None) -> Path | None:
    if appeal_run_dir:
        run_dir = Path(appeal_run_dir)
        if not _is_consumable_appeal_run(run_dir, allow_legacy=True):
            raise ValueError(f"Appeal run is incomplete or not consumable: {run_dir}")
        return run_dir
    if not DEFAULT_APPEAL_ROOT.exists():
        return None
    candidates = sorted(
        (path for path in DEFAULT_APPEAL_ROOT.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for run_dir in candidates:
        if _is_consumable_appeal_run(run_dir, allow_legacy=True):
            return run_dir
    return None


def _is_consumable_appeal_run(run_dir: Path, *, allow_legacy: bool) -> bool:
    manifest_path = run_dir / "artifact_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if str(manifest.get("status", "")).lower() != "complete":
            return False
        if str(manifest.get("run_kind", "production")).lower() != "production":
            return False
        return (run_dir / "appeal_summary.csv").exists() and (run_dir / "admitted_v2.csv").exists()
    if not allow_legacy:
        return False
    # Backward compatibility is intentionally strict: test artifacts whose
    # admitted output was renamed must never become the implicit production run.
    return (
        (run_dir / "appeal_manifest.csv").exists()
        and (run_dir / "appeal_summary.csv").exists()
        and (run_dir / "admitted_v2.csv").exists()
    )


def _cabinet_role_from_v1(row) -> str:
    role = str(row.get("role", ""))
    module = str(row.get("module", "")).lower()
    family = str(row.get("family", "")).lower()
    if role == "entry_alpha":
        if any(token in module + family for token in ("trend", "breakout", "orderflow", "quality", "value", "event", "relative_strength")):
            return "proxy_entry_alpha"
        return "strict_entry_alpha"
    return role


def _cabinet_score(row) -> float:
    rank_ic = abs(_num(row.get("best_rank_ic_mean", row.get("rank_ic")), 0.0))
    ic_ir = _num(row.get("best_ic_ir", row.get("ic_ir")), 0.0)
    spread = _num(row.get("best_cost_adjusted_top_bottom_spread", row.get("top_bottom_spread")), 0.0)
    turnover = _num(row.get("avg_turnover_mean"), 0.5)
    coverage = _num(row.get("coverage"), 1.0)
    stability = _num(row.get("positive_ic_ratio"), 0.52)
    turnover_score = max(1.0 - turnover, 0.0)
    return 0.30 * rank_ic + 0.25 * ic_ir + 0.20 * max(spread, 0.0) + 0.10 * stability + 0.10 * turnover_score + 0.05 * coverage


def _num(value, default: float = 0.0) -> float:
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return float(default)
    return float(value)


def _assign_proxy_entry_roles(candidates: pd.DataFrame) -> pd.DataFrame:
    data = candidates.copy()
    if data.empty:
        return data
    text = (
        data.get("module", pd.Series("", index=data.index)).astype(str).str.lower()
        + "|"
        + data.get("family", pd.Series("", index=data.index)).astype(str).str.lower()
        + "|"
        + data.get("factor_name", pd.Series("", index=data.index)).astype(str).str.lower()
    )
    proxy_tokens = (
        "trend",
        "breakout",
        "turtle",
        "macd",
        "rsi",
        "large_order",
        "orderflow",
        "volume_price",
        "amount_shock",
        "value_proxy",
        "barra",
        "quality",
        "efficiency",
    )
    role = data.get("cabinet_role", pd.Series("", index=data.index)).astype(str)
    eligible = role.isin(["timing_filter", "hold_validation", "liquidity_filter"]) & text.apply(
        lambda item: any(token in item for token in proxy_tokens)
    )
    current_proxy_count = int(role.eq("proxy_entry_alpha").sum())
    needed = max(ROLE_QUOTA["proxy_entry_alpha"][0] - current_proxy_count, 0)
    if needed <= 0:
        return data
    selected_index = data.loc[eligible].sort_values("cabinet_score", ascending=False).head(needed).index
    data.loc[selected_index, "cabinet_role"] = "proxy_entry_alpha"
    data.loc[selected_index, "role"] = "entry_alpha_proxy"
    data.loc[selected_index, "proxy_entry_reason"] = "admitted_non_entry_alpha_used_for_basket_entry_proxy"
    return data


def _near_relative_dedup(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    kept = []
    for key, group in candidates.sort_values(["cabinet_score", "factor_name"], ascending=[False, True]).groupby("near_relative_key", dropna=False):
        limit = 2 if _cross_regime_stable(group) else 1
        keep = group.head(limit)
        drop = group.iloc[limit:]
        kept.append(keep)
        for _, row in keep.iterrows():
            rows.append({"near_relative_key": key, "factor_name": row["factor_name"], "action": "keep", "reason": f"top_{limit}_by_cabinet_score"})
        for _, row in drop.iterrows():
            rows.append({"near_relative_key": key, "factor_name": row["factor_name"], "action": "drop", "reason": "near_relative_limit"})
    return pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(), pd.DataFrame(rows)


def _cross_regime_stable(group: pd.DataFrame) -> bool:
    return bool(pd.to_numeric(group.get("positive_ic_ratio", 0.0), errors="coerce").fillna(0.0).max() >= 0.58)


def _select_by_role(candidates: pd.DataFrame, *, min_factors: int, max_factors: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_parts = []
    quota_rows = []
    used = set()
    for role, (min_count, max_count) in ROLE_QUOTA.items():
        group = candidates[candidates["cabinet_role"].astype(str).eq(role)].sort_values("cabinet_score", ascending=False)
        take = group.head(max_count).copy()
        selected_parts.append(take)
        used.update(take["factor_name"].astype(str))
        quota_rows.append({"role": role, "target_min": min_count, "target_max": max_count, "selected": int(len(take)), "pass": bool(len(take) >= min_count)})
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
    protected = candidates[
        candidates.get("source", pd.Series("", index=candidates.index)).astype(str).eq("v2_appeal")
        & candidates.get("decision", pd.Series("", index=candidates.index)).astype(str).eq("promote_candidate")
        & candidates.get("factor_type", pd.Series("", index=candidates.index)).astype(str).isin({"breakout", "orderflow_proxy"})
    ].copy()
    if not protected.empty:
        selected = pd.concat(
            [selected[~selected["factor_name"].astype(str).isin(protected["factor_name"].astype(str))], protected],
            ignore_index=True,
        )
        protected_names = set(protected["factor_name"].astype(str))
        trimmed = []
        for role, (_, role_max) in ROLE_QUOTA.items():
            group = selected[selected["cabinet_role"].astype(str).eq(role)].copy()
            group["_protected"] = group["factor_name"].astype(str).isin(protected_names)
            group = group.sort_values(["_protected", "cabinet_score"], ascending=[False, False]).head(role_max)
            trimmed.append(group.drop(columns="_protected"))
        selected = pd.concat(trimmed, ignore_index=True) if trimmed else selected
    if len(selected) < min_factors:
        extra = candidates[~candidates["factor_name"].astype(str).isin(used)].sort_values("cabinet_score", ascending=False).head(min_factors - len(selected))
        selected = pd.concat([selected, extra], ignore_index=True)
    selected = selected.sort_values(["cabinet_role", "cabinet_score"], ascending=[True, False]).head(max_factors).reset_index(drop=True)
    return selected, pd.DataFrame(quota_rows)


def _correlation_cluster_placeholder(selected: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cluster_id, (_, group) in enumerate(selected.groupby("family", dropna=False), start=1):
        for _, row in group.iterrows():
            rows.append({"cluster_id": cluster_id, "factor_name": row["factor_name"], "family": row.get("family", ""), "cluster_size": int(len(group)), "reason": "family_cluster_proxy"})
    return pd.DataFrame(rows)


def _latest_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    dirs = [path for path in root.iterdir() if path.is_dir() and path.name.startswith("run")]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)[0] if dirs else None


def _render_report(selected: pd.DataFrame, quota: pd.DataFrame) -> str:
    role_counts = selected["cabinet_role"].value_counts().to_dict() if not selected.empty else {}
    failures = quota[~quota["pass"].astype(bool)].to_dict("records") if not quota.empty else []
    return "\n".join([
        "# Factor Cabinet Report",
        "",
        f"Factor count: {len(selected)}",
        f"Role distribution: {role_counts}",
        f"Quota failures: {failures}",
        "",
        "State machine should read factor_cabinet.json only, not raw admitted pools.",
    ])
