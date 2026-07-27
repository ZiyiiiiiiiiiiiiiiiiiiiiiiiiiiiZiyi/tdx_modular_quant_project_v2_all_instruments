"""Paper-entry competing-risk diagnostics for governance candidates."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd


SURVIVAL_AUDIT_VERSION = "candidate_competing_risk_v1"


def build_candidate_competing_risk_reports(
    candidate_detail: pd.DataFrame,
    *,
    close_history_getter: Callable[[str], pd.DataFrame],
    feature_columns: Iterable[str],
    entry_mask_column: str,
    horizon_days: int,
    profit_barrier: float,
    loss_barrier: float,
    bootstrap_samples: int = 1000,
    minimum_entry_dates: int = 5,
    confidence: float = 0.90,
) -> dict[str, pd.DataFrame]:
    """Estimate profit/loss cumulative incidence for paper candidate entries."""
    features = tuple(dict.fromkeys(str(column) for column in feature_columns))
    required = {"signal_date", "symbol", entry_mask_column, *features}
    missing = sorted(required - set(candidate_detail.columns))
    if missing:
        raise ValueError(f"competing-risk audit is missing columns: {missing}")
    horizon = int(horizon_days)
    profit = float(profit_barrier)
    loss = abs(float(loss_barrier))
    if horizon <= 0 or profit <= 0.0 or loss <= 0.0:
        raise ValueError("horizon and absolute profit/loss barriers must be positive")
    if int(bootstrap_samples) <= 0 or int(minimum_entry_dates) <= 1:
        raise ValueError("bootstrap and minimum date settings are invalid")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    data = candidate_detail.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    mask = _as_bool(data[entry_mask_column])
    entries = data[mask].dropna(subset=["signal_date", "symbol"]).copy()
    for feature in features:
        entries[feature] = pd.to_numeric(entries[feature], errors="coerce")
        percentile = entries.groupby("signal_date", sort=False)[feature].rank(pct=True, method="average")
        entries[f"{feature}__cohort"] = np.select(
            # Strict upper boundary keeps an n=3 cross section at 1/1/1.
            # Using >= here incorrectly assigned both ranks 2 and 3 high.
            [percentile.le(1.0 / 3.0), percentile.gt(2.0 / 3.0)],
            ["low", "high"],
            default="middle",
        )
    event_rows = []
    for row in entries.itertuples(index=False):
        signal_date = pd.Timestamp(getattr(row, "signal_date"))
        symbol = str(getattr(row, "symbol"))
        path = _future_path(close_history_getter(symbol), signal_date, horizon)
        event_type = "missing_path"
        event_day = np.nan
        event_return = np.nan
        observed_days = 0
        entry_price = np.nan
        if path is not None and not path.empty:
            entry_price = float(path.iloc[0]["close"])
            future = path.iloc[1:].copy()
            future["paper_return"] = future["close"] / entry_price - 1.0
            observed_days = min(len(future), horizon)
            event_type = "censored"
            event_day = observed_days
            if not future.empty:
                for day, value in enumerate(future["paper_return"].iloc[:horizon], start=1):
                    if float(value) >= profit:
                        event_type, event_day, event_return = "profit_barrier", day, float(value)
                        break
                    if float(value) <= -loss:
                        event_type, event_day, event_return = "loss_barrier", day, float(value)
                        break
                if event_type == "censored":
                    event_return = float(future["paper_return"].iloc[min(observed_days, horizon) - 1]) if observed_days else np.nan
        result = {
            "signal_date": signal_date,
            "symbol": symbol,
            "entry_price": entry_price,
            "observed_days": observed_days,
            "event_day": event_day,
            "event_type": event_type,
            "event_return": event_return,
            "horizon_days": horizon,
            "profit_barrier": profit,
            "loss_barrier": -loss,
            "survival_audit_version": SURVIVAL_AUDIT_VERSION,
        }
        for feature in features:
            result[feature] = getattr(row, feature)
            result[f"{feature}__cohort"] = getattr(row, f"{feature}__cohort")
        event_rows.append(result)
    events = pd.DataFrame(event_rows)
    curves = []
    summaries = []
    for feature in features:
        cohort_column = f"{feature}__cohort"
        for cohort in ("low", "high"):
            subset = events[events.get(cohort_column, pd.Series(dtype=str)).eq(cohort)].copy() if not events.empty else pd.DataFrame()
            curve = _cumulative_incidence_curve(subset, horizon)
            if not curve.empty:
                curve.insert(0, "feature", feature)
                curve.insert(1, "cohort", cohort)
                curves.append(curve)
        low = events[events.get(cohort_column, pd.Series(dtype=str)).eq("low")].copy() if not events.empty else pd.DataFrame()
        high = events[events.get(cohort_column, pd.Series(dtype=str)).eq("high")].copy() if not events.empty else pd.DataFrame()
        summaries.append(_cohort_difference_summary(
            feature, low, high, horizon=horizon, samples=int(bootstrap_samples),
            minimum_dates=int(minimum_entry_dates), confidence=float(confidence),
        ))
    curve_frame = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    return {
        "governance_failure_lab_competing_risk_events": events,
        "governance_failure_lab_competing_risk_curves": curve_frame,
        "governance_failure_lab_competing_risk_summary": pd.DataFrame(summaries),
    }


def _future_path(history, signal_date, horizon):
    if history is None or history.empty or not {"date", "close"}.issubset(history.columns):
        return None
    data = history[["date", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna().drop_duplicates("date", keep="last").sort_values("date")
    entry = data.index[data["date"].eq(pd.Timestamp(signal_date))]
    if len(entry) == 0:
        return None
    location = data.index.get_loc(entry[-1])
    if not isinstance(location, (int, np.integer)):
        return None
    return data.iloc[int(location):int(location) + int(horizon) + 1].reset_index(drop=True)


def _cumulative_incidence_curve(events, horizon):
    valid = events[events["event_type"].isin({"profit_barrier", "loss_barrier", "censored"})].copy() if not events.empty else pd.DataFrame()
    if valid.empty:
        return pd.DataFrame()
    survival = 1.0
    profit_cif = 0.0
    loss_cif = 0.0
    rows = []
    for day in range(1, horizon + 1):
        at_risk = int((pd.to_numeric(valid["event_day"], errors="coerce") >= day).sum())
        profit_events = int((valid["event_type"].eq("profit_barrier") & valid["event_day"].eq(day)).sum())
        loss_events = int((valid["event_type"].eq("loss_barrier") & valid["event_day"].eq(day)).sum())
        if at_risk > 0:
            profit_cif += survival * profit_events / at_risk
            loss_cif += survival * loss_events / at_risk
            survival *= 1.0 - (profit_events + loss_events) / at_risk
        rows.append({
            "day": day, "at_risk": at_risk, "profit_event_count": profit_events,
            "loss_event_count": loss_events, "survival_probability": survival,
            "profit_cumulative_incidence": profit_cif, "loss_cumulative_incidence": loss_cif,
            "survival_audit_version": SURVIVAL_AUDIT_VERSION,
        })
    return pd.DataFrame(rows)


def _cohort_difference_summary(feature, low, high, *, horizon, samples, minimum_dates, confidence):
    low_rates = _terminal_incidence(low, horizon)
    high_rates = _terminal_incidence(high, horizon)
    loss_difference = high_rates[1] - low_rates[1]
    profit_difference = high_rates[0] - low_rates[0]
    dates = sorted(set(low.get("signal_date", pd.Series(dtype="datetime64[ns]")).dropna()) | set(high.get("signal_date", pd.Series(dtype="datetime64[ns]")).dropna()))
    lower = upper = np.nan
    status = "insufficient_entry_dates"
    if len(dates) >= minimum_dates and not low.empty and not high.empty:
        rng = np.random.default_rng(_survival_seed(feature, horizon))
        boot = []
        for _ in range(samples):
            chosen = rng.choice(dates, size=len(dates), replace=True)
            low_sample = pd.concat([low[low["signal_date"].eq(date)] for date in chosen], ignore_index=True)
            high_sample = pd.concat([high[high["signal_date"].eq(date)] for date in chosen], ignore_index=True)
            boot.append(_terminal_incidence(high_sample, horizon)[1] - _terminal_incidence(low_sample, horizon)[1])
        alpha = (1.0 - confidence) / 2.0
        lower, upper = float(np.quantile(boot, alpha)), float(np.quantile(boot, 1.0 - alpha))
        if lower > 0.0:
            status = "high_score_increases_loss_incidence"
        elif upper < 0.0:
            status = "high_score_reduces_loss_incidence"
        else:
            status = "inconclusive"
    return {
        "feature": feature,
        "horizon_days": horizon,
        "low_entry_count": len(low),
        "high_entry_count": len(high),
        "entry_date_count": len(dates),
        "low_profit_cumulative_incidence": low_rates[0],
        "high_profit_cumulative_incidence": high_rates[0],
        "profit_incidence_difference_high_minus_low": profit_difference,
        "low_loss_cumulative_incidence": low_rates[1],
        "high_loss_cumulative_incidence": high_rates[1],
        "loss_incidence_difference_high_minus_low": loss_difference,
        "loss_difference_ci_lower": lower,
        "loss_difference_ci_upper": upper,
        "evidence_status": status,
        "causal_interpretation_allowed": False,
        "survival_audit_version": SURVIVAL_AUDIT_VERSION,
    }


def _terminal_incidence(events, horizon):
    curve = _cumulative_incidence_curve(events, horizon)
    if curve.empty:
        return np.nan, np.nan
    last = curve.iloc[-1]
    return float(last["profit_cumulative_incidence"]), float(last["loss_cumulative_incidence"])


def _survival_seed(feature, horizon):
    return int(hashlib.sha256(f"{feature}|{horizon}|{SURVIVAL_AUDIT_VERSION}".encode("utf-8")).hexdigest()[:8], 16)


def _as_bool(values):
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    return values.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})
