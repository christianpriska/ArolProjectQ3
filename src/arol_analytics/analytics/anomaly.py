# Tool 5: anomaly_detection.

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration, real_closures, successful_closures

logger = logging.getLogger(__name__)

VALID_METHODS = {"zscore", "iqr", "threshold"}


def anomaly_detection(
    events: pd.DataFrame,
    method: str = "zscore",
    threshold_range: tuple[float, float] | None = None,
    sensitivity: float = 3.0,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
    max_events_returned: int = 500,
) -> dict[str, Any]:
    """Flag anomalous closure events by torque, plus hours with an elevated failure rate.

    method: "zscore" (per-head mean/std computed on successful closures, flag
    |torque - mean| > sensitivity*std), "iqr" (per-head Q1/Q3 computed on
    successful closures, flag outside Q1-1.5*IQR / Q3+1.5*IQR), or "threshold"
    (flag outside the given threshold_range, required for this method).
    All methods evaluate against "real" (non-idle) closures -- a no-load
    event's ~0 Nm torque isn't a meaningful anomaly.

    Failure-rate spikes are detected independently: hourly failure rate vs.
    the overall hourly mean/std, flagged when > mean + 2*std.

    The `anomalies` list is capped at max_events_returned (sorted by deviation
    magnitude, worst first); `total_anomalies` is the true, uncapped count.

    Returns a dict with `summary`, `method`, `total_anomalies`, `anomalies`,
    `anomalies_truncated`, `anomaly_count_per_head`, `elevated_failure_rate_windows`.
    """
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {sorted(VALID_METHODS)}, got {method!r}")
    if method == "threshold" and threshold_range is None:
        raise ValueError("threshold_range is required when method='threshold'")

    events = filter_events(events, head_filter, time_range)
    real = real_closures(events)
    if real.empty:
        return {"summary": "No real (non-idle) closures match the given filters.", "total_anomalies": 0, "anomalies": []}

    with log_duration(f"anomaly_detection(method={method}) over {len(real):,} events"):
        flagged = _flag_by_torque(real, method, threshold_range, sensitivity)
        spike_windows = _failure_rate_spikes(real)

    total_anomalies = int(len(flagged))
    per_head_counts = flagged["head_id"].value_counts().to_dict() if total_anomalies else {}
    n_heads_flagged = flagged["head_id"].nunique() if total_anomalies else 0

    top_head = max(per_head_counts, key=per_head_counts.get) if per_head_counts else None
    summary = f"{total_anomalies:,} anomalies detected across {n_heads_flagged} heads."
    if top_head:
        summary += f" {top_head} shows the most anomalies ({per_head_counts[top_head]:,} events)."
    if spike_windows:
        summary += f" {len(spike_windows)} hour(s) with elevated failure rate."

    events_out: list[dict[str, Any]] = []
    if total_anomalies:
        top = flagged.sort_values("deviation", ascending=False).head(max_events_returned)
        top = top[["timestamp", "head_id", "torque_nm", "status_code", "reason"]].copy()
        top["timestamp"] = top["timestamp"].astype(str)
        top["head_id"] = top["head_id"].astype(str)
        events_out = top.to_dict(orient="records")

    return {
        "summary": summary,
        "method": method,
        "total_anomalies": total_anomalies,
        "anomalies": events_out,
        "anomalies_truncated": total_anomalies > max_events_returned,
        "anomaly_count_per_head": {str(k): int(v) for k, v in per_head_counts.items()},
        "elevated_failure_rate_windows": spike_windows,
    }


def _flag_by_torque(
    real: pd.DataFrame,
    method: str,
    threshold_range: tuple[float, float] | None,
    sensitivity: float,
) -> pd.DataFrame:
    if method == "threshold":
        lo, hi = threshold_range
        flagged = real[(real["torque_nm"] < lo) | (real["torque_nm"] > hi)].copy()
        if flagged.empty:
            return flagged
        flagged["lower"] = lo
        flagged["upper"] = hi
    else:
        baseline = successful_closures(real)
        stats = baseline.groupby("head_id", observed=True)["torque_nm"].agg(
            mean="mean", std="std", q1=lambda s: s.quantile(0.25), q3=lambda s: s.quantile(0.75)
        )
        stats["iqr"] = stats["q3"] - stats["q1"]
        if method == "zscore":
            stats["lower"] = stats["mean"] - sensitivity * stats["std"]
            stats["upper"] = stats["mean"] + sensitivity * stats["std"]
        else:  # iqr
            stats["lower"] = stats["q1"] - 1.5 * stats["iqr"]
            stats["upper"] = stats["q3"] + 1.5 * stats["iqr"]

        merged = real.merge(stats[["lower", "upper"]], left_on="head_id", right_index=True, how="left")
        mask = (merged["torque_nm"] < merged["lower"]) | (merged["torque_nm"] > merged["upper"])
        flagged = merged[mask.fillna(False)].copy()
        if flagged.empty:
            return flagged

    below = flagged["torque_nm"] < flagged["lower"]
    flagged["reason"] = np.where(
        below,
        "torque " + flagged["torque_nm"].round(3).astype(str) + " Nm below expected lower bound " + flagged["lower"].round(3).astype(str),
        "torque " + flagged["torque_nm"].round(3).astype(str) + " Nm above expected upper bound " + flagged["upper"].round(3).astype(str),
    )
    flagged["deviation"] = np.maximum(flagged["lower"] - flagged["torque_nm"], flagged["torque_nm"] - flagged["upper"])
    return flagged


def _failure_rate_spikes(real: pd.DataFrame) -> list[dict[str, Any]]:
    hourly = real.set_index("timestamp").resample("h")["is_reject"].agg(failure_rate="mean", n_events="size")
    hourly = hourly[hourly["n_events"] > 0]
    if len(hourly) < 2:
        return []
    avg, std = hourly["failure_rate"].mean(), hourly["failure_rate"].std(ddof=0)
    if not std or std <= 0:
        return []
    spikes = hourly[hourly["failure_rate"] > avg + 2 * std]
    return [
        {"hour_start": str(idx), "failure_rate": float(row["failure_rate"]), "n_events": int(row["n_events"])}
        for idx, row in spikes.iterrows()
    ]
