"""Rolling, non-ML calibration for governance entry probabilities.

The calibrator only uses candidate observations whose forward horizon has
already matured inside the backtest loop. It is intentionally simple and
auditable: bucketed empirical win rates and payoff estimates, with conservative
fallbacks when there is not enough history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import pandas as pd


CALIBRATION_FEATURE_COLUMNS = (
    "alpha_percentile",
    "expected_return_5d",
    "aggregate_confidence",
    "volatility_20",
    "entry_orderflow_confirm_count",
    "entry_quality_score",
)


@dataclass
class RollingEntryCalibrator:
    min_bucket_samples: int = 30
    min_global_samples: int = 80
    max_history_rows: int = 80_000
    cost_buffer: float = 0.0015
    pending_rows: list[dict] = field(default_factory=list)
    history_rows: list[dict] = field(default_factory=list)
    _history_version: int = 0
    _stats_cache: dict[int, dict] = field(default_factory=dict)
    _negative_drift_streak: int = 0
    _nonnegative_recovery_streak: int = 0
    _drifted_latched: bool = False
    _last_drift_history_version: int = -1
    warmup_manifest: dict = field(default_factory=dict)

    def warmup_from_feature_history(
        self,
        features: pd.DataFrame,
        *,
        trade_start,
        horizon_days: int = 10,
        lookback_sessions: int = 252,
        candidates_per_session: int = 40,
        score_columns: tuple[str, ...] = (),
    ) -> dict:
        """Seed calibration only with labels fully observable before trade_start.

        This is deliberately independent of account state.  It uses the
        preloaded PIT feature history, next-session nominal open as entry, and
        a later nominal close whose date is strictly before the trading window.
        """
        if features is None or features.empty:
            self.warmup_manifest = {"status": "empty", "matured_rows": 0}
            return dict(self.warmup_manifest)
        data = features.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data = data[data["date"].lt(pd.Timestamp(trade_start))].copy()
        if data.empty:
            self.warmup_manifest = {"status": "empty", "matured_rows": 0}
            return dict(self.warmup_manifest)
        sessions = pd.Index(data["date"].dropna().drop_duplicates().sort_values())
        sessions = sessions[-max(int(lookback_sessions) + int(horizon_days) + 2, 1):]
        data = data[data["date"].isin(sessions)].sort_values(["symbol", "date"])
        open_col = "open_nominal" if "open_nominal" in data.columns else "open"
        close_col = "close_nominal" if "close_nominal" in data.columns else "close"
        usable_score_columns = [
            str(column)
            for column in score_columns
            if str(column) in data.columns
        ]
        score_col = next(
            (
                column
                for column in (
                    "expected_return_5d",
                    "alpha_percentile",
                    "aggregate_confidence",
                    "ret_20",
                )
                if column in data.columns
            ),
            None,
        )
        if (
            not usable_score_columns
            and score_col is None
        ) or open_col not in data.columns or close_col not in data.columns:
            self.warmup_manifest = {
                "status": "missing_columns",
                "matured_rows": 0,
                "score_column": score_col or "",
            }
            return dict(self.warmup_manifest)
        grouped = data.groupby("symbol", sort=False)
        data["_warmup_entry_price"] = grouped[open_col].shift(-1)
        data["_warmup_exit_price"] = grouped[close_col].shift(-int(horizon_days))
        data["_warmup_exit_date"] = grouped["date"].shift(-int(horizon_days))
        if usable_score_columns:
            ranked = pd.DataFrame(index=data.index)
            for column in usable_score_columns:
                ranked[column] = (
                    pd.to_numeric(data[column], errors="coerce")
                    .groupby(data["date"])
                    .rank(pct=True)
                )
            data["_warmup_score"] = ranked.mean(axis=1, skipna=True)
            score_identity = "factor_cabinet_rank_mean"
        else:
            data["_warmup_score"] = pd.to_numeric(data[score_col], errors="coerce")
            score_identity = str(score_col)
        data["_warmup_alpha_pct"] = data.groupby("date")["_warmup_score"].rank(pct=True)
        eligible = data[
            data["_warmup_entry_price"].gt(0.0)
            & data["_warmup_exit_price"].gt(0.0)
            & data["_warmup_exit_date"].lt(pd.Timestamp(trade_start))
            & data["_warmup_score"].notna()
        ].copy()
        eligible = (
            eligible.sort_values(["date", "_warmup_score", "symbol"], ascending=[True, False, True])
            .groupby("date", sort=False)
            .head(max(int(candidates_per_session), 1))
        )
        rows = []
        date_index = {pd.Timestamp(value): index for index, value in enumerate(sessions)}
        for _, row in eligible.iterrows():
            entry_price = float(row["_warmup_entry_price"])
            exit_price = float(row["_warmup_exit_price"])
            forward_return = exit_price / entry_price - 1.0
            rows.append(
                {
                    "symbol": str(row["symbol"]),
                    "entry_day_index": int(date_index.get(pd.Timestamp(row["date"]), 0)),
                    "horizon_days": int(horizon_days),
                    "forward_return": float(forward_return),
                    "win": bool(forward_return > 0.0),
                    "alpha_bucket": _alpha_bucket(row["_warmup_alpha_pct"]),
                    "flow_bucket": _flow_bucket(row.get("entry_orderflow_confirm_count", 0)),
                    "regime_bucket": "unknown",
                    "expected_return_5d": _safe_float(row.get("expected_return_5d"), 0.0),
                    "calibration_forecast_score": _safe_float(
                        row.get("_warmup_score"), 0.0
                    ),
                    "calibration_score_contract": score_identity,
                }
            )
        self.history_rows = rows[-int(self.max_history_rows):]
        self.pending_rows = []
        self._history_version += 1
        self._stats_cache.clear()
        self.warmup_manifest = {
            "status": "ready" if len(rows) >= int(self.min_global_samples) else "insufficient",
            "matured_rows": int(len(rows)),
            "unique_sessions": int(eligible["date"].nunique()) if not eligible.empty else 0,
            "trade_start": str(pd.Timestamp(trade_start).date()),
            "horizon_days": int(horizon_days),
            "lookback_sessions": int(lookback_sessions),
            "score_column": score_identity,
            "score_column_count": int(len(usable_score_columns) or 1),
            "latest_label_date": (
                str(pd.Timestamp(eligible["_warmup_exit_date"].max()).date())
                if not eligible.empty
                else ""
            ),
        }
        if (
            int(self.warmup_manifest["unique_sessions"])
            < min(int(lookback_sessions), int(self.min_global_samples))
        ):
            self.warmup_manifest["status"] = "insufficient_sessions"
        return dict(self.warmup_manifest)

    def mature(self, *, day_index: int, price_frame: pd.DataFrame) -> int:
        """Move pending candidate snapshots into history once their horizon is observable."""
        if not self.pending_rows:
            return 0
        if price_frame is None or price_frame.empty or "symbol" not in price_frame.columns:
            return 0
        close_col = "close_nominal" if "close_nominal" in price_frame.columns else "close"
        open_col = "open_nominal" if "open_nominal" in price_frame.columns else "open"
        if close_col not in price_frame.columns or open_col not in price_frame.columns:
            return 0
        prices = (
            price_frame[["symbol", open_col, close_col]]
            .dropna()
            .drop_duplicates("symbol", keep="last")
            .set_index("symbol")
        )
        matured: list[dict] = []
        remaining: list[dict] = []
        for row in self.pending_rows:
            symbol = str(row["symbol"])
            if symbol not in prices.index:
                remaining.append(row)
                continue
            entry_price = float(row.get("entry_price", 0.0) or 0.0)
            entry_index = int(row.get("entry_observation_index", row["entry_day_index"] + 1))
            if entry_price <= 0.0:
                if int(day_index) < entry_index:
                    remaining.append(row)
                    continue
                entry_price = _safe_float(prices.at[symbol, open_col], 0.0)
                if entry_price <= 0.0:
                    remaining.append(row)
                    continue
                row["entry_price"] = entry_price
                row["entry_price_basis"] = "next_observed_open"
                row["entry_observed_index"] = int(day_index)
                # The requested horizon starts at the factual entry observation,
                # not at the decision-day close.
                row["maturity_index"] = int(day_index) + int(row["horizon_days"]) - 1
            if int(row["maturity_index"]) > int(day_index):
                remaining.append(row)
                continue
            exit_price = _safe_float(prices.at[symbol, close_col], 0.0)
            if entry_price <= 0.0 or exit_price <= 0.0:
                continue
            outcome = dict(row)
            outcome["exit_day_index"] = int(day_index)
            outcome["exit_price"] = exit_price
            outcome["forward_return"] = exit_price / entry_price - 1.0
            outcome["win"] = bool(outcome["forward_return"] > 0.0)
            matured.append(outcome)
        self.pending_rows = remaining
        if matured:
            self.history_rows.extend(matured)
            if len(self.history_rows) > self.max_history_rows:
                self.history_rows = self.history_rows[-self.max_history_rows :]
            self._history_version += 1
            self._stats_cache.clear()
        return len(matured)

    def schedule_candidates(
        self,
        candidates: pd.DataFrame,
        *,
        day_index: int,
        horizon_days: int,
        regime_name: str,
        score_column: str = "cabinet_native_final_score",
    ) -> None:
        """Store today's candidate features for future calibration outcomes."""
        if candidates is None or candidates.empty:
            return
        data = candidates.copy()
        data = data.dropna(subset=["symbol"])
        if data.empty:
            return
        available_score_column = next(
            (
                column
                for column in (
                    score_column,
                    "cabinet_native_final_score",
                    "primary_score",
                    "expected_return_5d",
                )
                if column in data.columns
            ),
            None,
        )
        for _, row in data.iterrows():
            payload = {
                "symbol": str(row["symbol"]),
                "entry_day_index": int(day_index),
                "entry_observation_index": int(day_index) + 1,
                "maturity_index": int(day_index) + int(horizon_days),
                "horizon_days": int(horizon_days),
                "entry_price": 0.0,
                "entry_price_basis": "pending_next_observed_open",
                "regime_bucket": _regime_bucket(regime_name),
                "alpha_bucket": _alpha_bucket(row.get("alpha_percentile", 0.5)),
                "flow_bucket": _flow_bucket(row.get("entry_orderflow_confirm_count", 0)),
                "calibration_forecast_score": _safe_float(
                    row.get(available_score_column), 0.0
                ),
                "calibration_score_contract": str(
                    available_score_column or "missing_score"
                ),
            }
            for column in CALIBRATION_FEATURE_COLUMNS:
                payload[column] = _safe_float(row.get(column), 0.0)
            self.pending_rows.append(payload)

    def score_candidates(
        self,
        candidates: pd.DataFrame,
        *,
        regime_name: str,
        horizon_days: int,
    ) -> pd.DataFrame:
        """Attach calibrated probability and expected-edge fields to candidates."""
        data = candidates.copy()
        if data.empty:
            return data
        stats_bundle = self._stats_bundle(int(horizon_days))
        scored = data.reset_index(drop=True)
        scored["_alpha_bucket"] = scored["alpha_percentile"].map(_alpha_bucket) if "alpha_percentile" in scored.columns else "p00_50"
        scored["_flow_bucket"] = scored.get("entry_orderflow_confirm_count", pd.Series(0, index=scored.index)).map(_flow_bucket)
        scored["_regime_bucket"] = _regime_bucket(regime_name)

        fallback = _fallback_frame(scored, horizon_days=horizon_days, cost_buffer=self.cost_buffer)
        exact = _lookup_stats(
            scored,
            stats_bundle.get("exact", pd.DataFrame()),
            key_columns=["_alpha_bucket", "_flow_bucket", "_regime_bucket"],
        )
        alpha_only = _lookup_stats(
            scored,
            stats_bundle.get("alpha", pd.DataFrame()),
            key_columns=["_alpha_bucket"],
        )
        global_stats = stats_bundle.get("global")
        stat_columns = (
            "sample_count",
            "effective_sample_size",
            "p_win",
            "p_win_lower",
            "avg_win",
            "avg_loss",
            "loss_cvar95",
        )
        exact_effective = pd.to_numeric(
            exact["effective_sample_size"], errors="coerce"
        ).fillna(0.0)
        alpha_effective = pd.to_numeric(
            alpha_only["effective_sample_size"], errors="coerce"
        ).fillna(0.0)
        exact_usable = exact_effective.gt(0.0)
        alpha_usable = alpha_effective.gt(0.0)
        for column in stat_columns:
            exact[column] = pd.to_numeric(exact[column], errors="coerce")
            alpha_only[column] = pd.to_numeric(alpha_only[column], errors="coerce")
            scored[column] = exact[column].where(exact_usable, alpha_only[column])
            if global_stats is not None:
                scored[column] = scored[column].where(
                    exact_usable | alpha_usable,
                    global_stats[column],
                )
            scored[column] = pd.to_numeric(scored[column], errors="coerce").fillna(fallback[column])

        global_n_eff = float(global_stats["effective_sample_size"]) if global_stats is not None else 0.0
        trust = scored["effective_sample_size"].astype(float) / (
            scored["effective_sample_size"].astype(float) + 40.0
        )
        if global_stats is not None:
            for column in ("p_win", "p_win_lower", "avg_win", "avg_loss"):
                scored[column] = (
                    trust * scored[column].astype(float)
                    + (1.0 - trust) * float(global_stats[column])
                )

        # Forecasts remain in gross return units. Concrete action costs are
        # deducted exactly once after a lot and side are known.
        edge = (
            scored["p_win"].astype(float) * scored["avg_win"].astype(float)
            - (1.0 - scored["p_win"].astype(float)) * scored["avg_loss"].astype(float)
        )
        conservative_edge = (
            scored["p_win_lower"].astype(float) * scored["avg_win"].astype(float)
            - (1.0 - scored["p_win_lower"].astype(float)) * scored["avg_loss"].astype(float)
        )
        volatility = pd.to_numeric(scored.get("volatility_20", pd.Series(0.02, index=scored.index)), errors="coerce").fillna(0.02).clip(lower=0.005)
        scored[f"p_win_{horizon_days}d_calibrated"] = scored["p_win"].astype(float)
        scored[f"p_win_{horizon_days}d_wilson_lower"] = scored["p_win_lower"].astype(float)
        scored[f"avg_win_{horizon_days}d_by_bucket"] = scored["avg_win"].astype(float)
        scored[f"avg_loss_{horizon_days}d_by_bucket"] = scored["avg_loss"].astype(float)
        scored[f"downside_cvar_{horizon_days}d_by_bucket"] = scored[
            "loss_cvar95"
        ].astype(float)
        scored[f"expected_edge_{horizon_days}d"] = edge.astype(float)
        scored[f"conservative_expected_edge_{horizon_days}d"] = conservative_edge.astype(float)
        scored[f"edge_to_risk_{horizon_days}d"] = (edge / volatility).astype(float)
        scored[f"conservative_edge_to_risk_{horizon_days}d"] = (conservative_edge / volatility).astype(float)
        scored[f"entry_calibration_sample_count_{horizon_days}d"] = scored["sample_count"].fillna(0).astype(int)
        scored[f"entry_calibration_effective_sample_size_{horizon_days}d"] = (
            scored["effective_sample_size"].fillna(0.0).astype(float)
        )
        history = pd.DataFrame(self.history_rows)
        if not history.empty and "horizon_days" in history.columns:
            history = history[
                pd.to_numeric(history["horizon_days"], errors="coerce").eq(
                    int(horizon_days)
                )
            ]
        # In-memory histories created before the score-identity migration do
        # not carry the new field. Keep them testable/auditable without
        # changing the live contract, whose scheduled rows always persist the
        # factor-cabinet score explicitly.
        if (
            not history.empty
            and "calibration_forecast_score" not in history.columns
            and "expected_return_5d" in history.columns
        ):
            history = history.copy()
            history["calibration_forecast_score"] = history[
                "expected_return_5d"
            ]
            history["calibration_score_contract"] = (
                "legacy_expected_return_5d_compatibility"
            )
        unique_sessions = 0
        if not history.empty:
            session_column = (
                "entry_day_index"
                if "entry_day_index" in history.columns
                else ("date" if "date" in history.columns else None)
            )
            if session_column is not None:
                unique_sessions = int(history[session_column].nunique())
        scored[f"entry_calibration_unique_session_count_{horizon_days}d"] = (
            unique_sessions
        )
        rank_ic = float("nan")
        calibration_slope = float("nan")
        if (
            not history.empty
            and len(history) >= int(self.min_global_samples)
            and {"calibration_forecast_score", "forward_return"}.issubset(
                history.columns
            )
        ):
            forecast = pd.to_numeric(
                history["calibration_forecast_score"], errors="coerce"
            )
            realized = pd.to_numeric(history["forward_return"], errors="coerce")
            valid = forecast.notna() & realized.notna()
            if int(valid.sum()) >= int(self.min_global_samples):
                rank_ic = float(forecast[valid].corr(realized[valid], method="spearman"))
                variance = float(forecast[valid].var())
                if variance > 1e-12:
                    calibration_slope = float(
                        forecast[valid].cov(realized[valid]) / variance
                    )
        negative_drift = pd.notna(rank_ic) and (
            float(rank_ic) <= 0.0
            or (pd.notna(calibration_slope) and float(calibration_slope) <= 0.0)
        )
        nonnegative_direction = (
            pd.notna(rank_ic)
            and pd.notna(calibration_slope)
            and float(rank_ic) >= 0.0
            and float(calibration_slope) >= 0.0
        )
        if self._last_drift_history_version != self._history_version:
            if negative_drift:
                self._negative_drift_streak += 1
                self._nonnegative_recovery_streak = 0
                if self._negative_drift_streak >= 3:
                    self._drifted_latched = True
            elif nonnegative_direction:
                self._negative_drift_streak = 0
                if self._drifted_latched:
                    self._nonnegative_recovery_streak += 1
                    if self._nonnegative_recovery_streak >= 2:
                        self._drifted_latched = False
                        self._nonnegative_recovery_streak = 0
                else:
                    self._nonnegative_recovery_streak = 0
            self._last_drift_history_version = self._history_version
        drifted = bool(self._drifted_latched)
        calibrated = pd.Series(
            global_n_eff >= float(self.min_global_samples) and not drifted,
            index=scored.index,
        )
        state = pd.Series("prior_only", index=scored.index)
        state.loc[calibrated] = "calibrated"
        if drifted:
            recovering = bool(
                self._nonnegative_recovery_streak > 0
                and nonnegative_direction
            )
            state.loc[
                scored["effective_sample_size"].ge(float(self.min_bucket_samples))
            ] = "recovering" if recovering else "drifted"
        scored[f"entry_calibration_state_{horizon_days}d"] = state
        scored[f"forecast_authority_weight_{horizon_days}d"] = (
            trust.clip(0.0, 1.0) * calibrated.astype(float)
        )
        scored[f"forecast_rank_ic_{horizon_days}d"] = rank_ic
        scored[f"forecast_calibration_slope_{horizon_days}d"] = calibration_slope
        scored[f"forecast_cost_inclusion_state_{horizon_days}d"] = "gross_only"
        scored[f"forecast_entry_price_basis_{horizon_days}d"] = "next_observed_open"
        scored[f"entry_calibration_trust_{horizon_days}d"] = (
            trust.clip(0.0, 1.0)
        )
        cluster_se = (
            volatility
            / scored["effective_sample_size"].astype(float).clip(lower=1.0).pow(0.5)
        )
        scored[f"forecast_cluster_se_{horizon_days}d"] = cluster_se
        scored[f"forecast_shrunk_mean_{horizon_days}d"] = edge.astype(float)
        scored[f"forecast_robust_edge_{horizon_days}d"] = (
            edge.astype(float) - 0.50 * cluster_se
        )
        scored[f"forecast_drift_streak_{horizon_days}d"] = int(
            self._negative_drift_streak
        )
        scored[f"forecast_recovery_streak_{horizon_days}d"] = int(
            self._nonnegative_recovery_streak
        )
        scored[f"forecast_score_identity_{horizon_days}d"] = (
            "factor_cabinet_score_contract"
        )
        scored = scored.drop(
            columns=["_alpha_bucket", "_flow_bucket", "_regime_bucket", *stat_columns]
        )
        return scored

    def _stats_bundle(self, horizon_days: int) -> dict:
        cached = self._stats_cache.get(int(horizon_days))
        if cached is not None and cached.get("version") == self._history_version:
            return cached
        history = pd.DataFrame(self.history_rows)
        if history.empty or "horizon_days" not in history.columns:
            bundle = {"version": self._history_version, "exact": pd.DataFrame(), "alpha": pd.DataFrame(), "global": None}
            self._stats_cache[int(horizon_days)] = bundle
            return bundle
        history = history[history["horizon_days"].astype(int).eq(int(horizon_days))].copy()
        if history.empty:
            bundle = {"version": self._history_version, "exact": pd.DataFrame(), "alpha": pd.DataFrame(), "global": None}
            self._stats_cache[int(horizon_days)] = bundle
            return bundle
        exact = _group_stats(history, ["alpha_bucket", "flow_bucket", "regime_bucket"])
        alpha = _group_stats(history, ["alpha_bucket"])
        global_stats = _empirical_stats(history, min_samples=self.min_global_samples)
        bundle = {
            "version": self._history_version,
            "exact": exact.rename(columns={
                "alpha_bucket": "_alpha_bucket",
                "flow_bucket": "_flow_bucket",
                "regime_bucket": "_regime_bucket",
            }),
            "alpha": alpha.rename(columns={"alpha_bucket": "_alpha_bucket"}),
            "global": global_stats,
        }
        self._stats_cache[int(horizon_days)] = bundle
        return bundle


def _empirical_stats(frame: pd.DataFrame, *, min_samples: int) -> dict | None:
    if frame is None or frame.empty or len(frame) < int(min_samples):
        return None
    returns = pd.to_numeric(frame["forward_return"], errors="coerce").dropna()
    if len(returns) < int(min_samples):
        return None
    wins = returns[returns > 0.0]
    losses = returns[returns <= 0.0]
    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = abs(float(losses.mean())) if not losses.empty else 0.0
    return {
        "sample_count": int(len(returns)),
        "effective_sample_size": float(
            frame.loc[returns.index, "entry_day_index"].nunique()
            if "entry_day_index" in frame.columns
            else len(returns)
        ),
        "p_win": float((returns > 0.0).mean()),
        "p_win_lower": _wilson_lower(int((returns > 0.0).sum()), int(len(returns))),
        "avg_win": max(avg_win, 0.002),
        "avg_loss": max(avg_loss, 0.002),
        "loss_cvar95": _loss_cvar95(returns),
    }


def _group_stats(frame: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    output_columns = list(key_columns) + [
        "sample_count",
        "effective_sample_size",
        "p_win",
        "p_win_lower",
        "avg_win",
        "avg_loss",
        "loss_cvar95",
    ]
    if frame is None or frame.empty or "forward_return" not in frame.columns:
        return pd.DataFrame(columns=output_columns)
    data = frame.copy()
    data["forward_return"] = pd.to_numeric(data["forward_return"], errors="coerce")
    data = data.dropna(subset=["forward_return"])
    if data.empty:
        return pd.DataFrame(columns=output_columns)

    grouped = data.groupby(key_columns, dropna=False)
    result = grouped["forward_return"].agg(
        sample_count="count",
        p_win=lambda values: float((values > 0.0).mean()),
        p_win_lower=lambda values: _wilson_lower(int((values > 0.0).sum()), int(len(values))),
        avg_win=lambda values: max(float(values[values > 0.0].mean()) if (values > 0.0).any() else 0.0, 0.002),
        avg_loss=lambda values: max(abs(float(values[values <= 0.0].mean())) if (values <= 0.0).any() else 0.0, 0.002),
        loss_cvar95=lambda values: _loss_cvar95(values),
    ).reset_index()
    if "entry_day_index" in data.columns:
        effective = (
            grouped["entry_day_index"]
            .nunique()
            .rename("effective_sample_size")
            .reset_index()
        )
        result = result.merge(effective, on=key_columns, how="left")
    else:
        result["effective_sample_size"] = result["sample_count"]
    result["sample_count"] = pd.to_numeric(result["sample_count"], errors="coerce").fillna(0).astype(int)
    result["effective_sample_size"] = pd.to_numeric(
        result["effective_sample_size"], errors="coerce"
    ).fillna(0.0)
    return result[output_columns]


def _lookup_stats(scored: pd.DataFrame, table: pd.DataFrame, *, key_columns: list[str]) -> pd.DataFrame:
    stat_columns = [
        "sample_count",
        "effective_sample_size",
        "p_win",
        "p_win_lower",
        "avg_win",
        "avg_loss",
        "loss_cvar95",
    ]
    empty = pd.DataFrame({column: pd.NA for column in stat_columns}, index=scored.index)
    if table is None or table.empty:
        return empty
    missing = [column for column in key_columns + stat_columns if column not in table.columns]
    if missing:
        return empty
    left = scored[key_columns].reset_index(drop=True)
    merged = left.merge(table[key_columns + stat_columns], on=key_columns, how="left")
    merged.index = scored.index
    return merged[stat_columns]


def _fallback_frame(scored: pd.DataFrame, *, horizon_days: int, cost_buffer: float) -> pd.DataFrame:
    index = scored.index
    alpha = (
        pd.to_numeric(scored.get("alpha_percentile", pd.Series(0.5, index=index)), errors="coerce")
        .fillna(0.5)
        .clip(0.0, 1.0)
    )
    expected = (
        pd.to_numeric(scored.get("expected_return_5d", pd.Series(0.0, index=index)), errors="coerce")
        .fillna(0.0)
    )
    confidence = (
        pd.to_numeric(scored.get("aggregate_confidence", pd.Series(0.5, index=index)), errors="coerce")
        .fillna(0.5)
        .clip(0.0, 1.0)
    )
    flow = (
        pd.to_numeric(scored.get("entry_orderflow_confirm_count", pd.Series(0.0, index=index)), errors="coerce")
        .fillna(0.0)
        .clip(0.0, 4.0)
        / 4.0
    )
    expected_scaled = (expected / 0.03).clip(-1.0, 1.0)
    p_win = (
        0.47
        + 0.10 * (alpha - 0.5)
        + 0.05 * expected_scaled
        + 0.03 * (confidence - 0.5)
        + 0.03 * (flow - 0.5)
    ).clip(0.35, 0.65)
    p_win_lower = (p_win - 0.08).clip(0.30, 0.58)
    scale = max(float(horizon_days) / 5.0, 1.0)
    avg_win = (0.018 * scale + expected.clip(lower=0.0) * 0.50).clip(lower=0.002)
    avg_loss = (0.016 * scale + (-expected.clip(upper=0.0)) * 0.50).clip(lower=0.002)
    return pd.DataFrame(
        {
            "sample_count": 0,
            "effective_sample_size": 0.0,
            "p_win": p_win.astype(float),
            "p_win_lower": p_win_lower.astype(float),
            "avg_win": avg_win.astype(float),
            "avg_loss": avg_loss.astype(float),
            "loss_cvar95": 0.15,
        },
        index=index,
    )


def _fallback_stats(row, *, horizon_days: int, cost_buffer: float) -> dict:
    alpha = _safe_float(row.get("alpha_percentile"), 0.5)
    expected = _safe_float(row.get("expected_return_5d"), 0.0)
    confidence = _safe_float(row.get("aggregate_confidence"), 0.5)
    flow = min(max(_safe_float(row.get("entry_orderflow_confirm_count"), 0.0) / 4.0, 0.0), 1.0)
    p_win = (
        0.47
        + 0.10 * (alpha - 0.5)
        + 0.05 * max(min(expected / 0.03, 1.0), -1.0)
        + 0.03 * (confidence - 0.5)
        + 0.03 * (flow - 0.5)
    )
    scale = max(float(horizon_days) / 5.0, 1.0)
    return {
        "sample_count": 0,
        "effective_sample_size": 0.0,
        "p_win": float(min(max(p_win, 0.35), 0.65)),
        "p_win_lower": float(min(max(p_win - 0.08, 0.30), 0.58)),
        "avg_win": float(0.018 * scale + max(expected, 0.0) * 0.50),
        "avg_loss": float(0.016 * scale + abs(min(expected, 0.0)) * 0.50),
        "loss_cvar95": 0.15,
    }


def _loss_cvar95(values) -> float:
    """Positive loss magnitude in the empirical worst five-percent tail."""
    returns = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if returns.empty:
        return 0.15
    cutoff = float(returns.quantile(0.05))
    tail = returns[returns <= cutoff]
    if tail.empty:
        tail = returns.nsmallest(1)
    return max(abs(float(tail.mean())), 0.002)


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = float(wins) / float(n)
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return max(0.0, float((centre - margin) / denom))


def _alpha_bucket(value) -> str:
    numeric = min(max(_safe_float(value, 0.5), 0.0), 1.0)
    if numeric >= 0.90:
        return "p90_100"
    if numeric >= 0.80:
        return "p80_90"
    if numeric >= 0.65:
        return "p65_80"
    if numeric >= 0.50:
        return "p50_65"
    return "p00_50"


def _flow_bucket(value) -> str:
    numeric = int(_safe_float(value, 0.0))
    if numeric >= 3:
        return "flow3p"
    if numeric >= 1:
        return "flow1_2"
    return "flow0"


def _regime_bucket(regime_name: str) -> str:
    regime = str(regime_name).lower()
    if regime in {"bull", "rebound"}:
        return "risk_on"
    if regime in {"neutral", "weak"}:
        return "neutral_weak"
    return "risk_off"


def _safe_float(value, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])
