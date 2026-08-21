# Tool 3 (torque_statistics) and Tool 4 (torque_trend_analysis).

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import linregress

from arol_analytics.analytics._common import (
    TimeRange,
    failed_closures,
    filter_events,
    log_duration,
    real_closures,
    successful_closures,
)

logger = logging.getLogger(__name__)

VALID_FILTER_STATUS = {"successful_only", "failed_only", "all_real", "all"}
VALID_TORQUE_GROUP_BY = {"overall", "per_head", "daily"}

BIMODAL_WARNING = (
    "torque is bimodal (~0 Nm during no-load, nonzero during real closures) -- "
    "statistics over filter_status='all' mix both populations and may be misleading; "
    "prefer 'successful_only' or 'all_real'."
)


def torque_statistics(
    events: pd.DataFrame,
    filter_status: str = "successful_only",
    group_by: str = "overall",
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Torque distribution statistics (count, mean, median, std, min, max, Q1,
    Q3, IQR, IQR-outlier count) with flexible filtering and grouping.

    filter_status: "successful_only" (default), "failed_only", "all_real"
    (excludes no-load), or "all" (everything, including no-load -- noisy, see
    warning below).
    group_by: "overall", "per_head", or "daily".

    Returns a dict with `summary`, `warning` (set when filter_status="all"),
    `table` (one row per group, includes coefficient_of_variation), and
    `flagged_high_variability` (per_head groups whose CV is > 2 sigma above
    the across-head average).
    """
    if filter_status not in VALID_FILTER_STATUS:
        raise ValueError(f"filter_status must be one of {sorted(VALID_FILTER_STATUS)}, got {filter_status!r}")
    if group_by not in VALID_TORQUE_GROUP_BY:
        raise ValueError(f"group_by must be one of {sorted(VALID_TORQUE_GROUP_BY)}, got {group_by!r}")

    events = filter_events(events, head_filter, time_range)
    subset = _apply_status_filter(events, filter_status)
    if subset.empty:
        return {"summary": "No events match the given filters.", "filter_status": filter_status, "group_by": group_by, "table": []}

    with log_duration(f"torque_statistics(filter_status={filter_status}, group_by={group_by})"):
        key = _group_key(subset, group_by)
        table = subset.groupby(key, observed=True)["torque_nm"].apply(_describe).unstack().reset_index(names="group")
        table["coefficient_of_variation"] = table["std"] / table["mean"].replace(0, np.nan)
        table = table.sort_values("group").reset_index(drop=True)

        flagged: list[str] = []
        if group_by == "per_head" and len(table) >= 2:
            cv = table["coefficient_of_variation"].dropna()
            if len(cv) >= 2:
                avg, std = cv.mean(), cv.std(ddof=0)
                if std > 0:
                    mask = table["coefficient_of_variation"] > (avg + 2 * std)
                    flagged = table.loc[mask, "group"].astype(str).tolist()

    warning = BIMODAL_WARNING if filter_status == "all" else None
    summary = f"Torque stats ({filter_status}, {group_by}): {len(table)} group(s)."
    if warning:
        summary += " WARNING: " + warning
    if flagged:
        summary += f" High-variability heads: {flagged}."

    table["group"] = table["group"].astype(str)
    return {
        "summary": summary,
        "filter_status": filter_status,
        "group_by": group_by,
        "warning": warning,
        "table": table.to_dict(orient="records"),
        "flagged_high_variability": flagged,
    }


def torque_trend_analysis(
    events: pd.DataFrame,
    head_filter: list[str] | None = None,
    window_size: int | str = 1000,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Detect drift/trends in torque over time, per head, on successful closures.

    window_size: either an int (rolling window in number of events) or a
    pandas offset string (e.g. "7D") for a time-based rolling window.

    Per head: a moving average/std of torque, a linear-regression slope
    (Nm/day) with significance (p < 0.05), and changepoints (moving-average
    shifts of more than 2x the head's overall torque std within a short lag).

    The returned `plot_series` is downsampled to one point per day per head
    (mean of the moving average that day) -- returning the full per-event
    series for ~30M events would be impractically large.

    Returns a dict with `summary`, `window_size`, `per_head_trend` (slope_nm_per_day,
    p_value, r_squared, direction, significant, n_events), `changepoints`, `plot_series`.
    """
    events = filter_events(events, head_filter, time_range)
    successful = successful_closures(events)
    if successful.empty:
        return {"summary": "No successful closures match the given filters.", "per_head_trend": {}, "changepoints": [], "plot_series": {}}

    heads = sorted(successful["head_id"].astype(str).unique().tolist())
    per_head_trend: dict[str, dict[str, Any]] = {}
    plot_series: dict[str, list[dict[str, Any]]] = {}
    changepoints: list[dict[str, Any]] = []

    with log_duration(f"torque_trend_analysis over {len(heads)} heads"):
        for i, h in enumerate(heads, start=1):
            sub = successful[successful["head_id"] == h].sort_values("timestamp")
            torque = sub["torque_nm"].reset_index(drop=True)
            ts = sub["timestamp"].reset_index(drop=True)
            if len(torque) < 2:
                continue

            rolling_mean, rolling_std = _rolling(torque, ts, window_size)

            days_since_start = (ts - ts.iloc[0]).dt.total_seconds() / 86400.0
            reg = linregress(days_since_start, torque)
            significant = bool(reg.pvalue < 0.05)
            direction = "stable"
            if significant and abs(reg.slope) > 1e-9:
                direction = "increasing" if reg.slope > 0 else "decreasing"

            per_head_trend[h] = {
                "slope_nm_per_day": float(reg.slope),
                "p_value": float(reg.pvalue),
                "r_squared": float(reg.rvalue ** 2),
                "direction": direction,
                "significant": significant,
                "n_events": int(len(torque)),
            }

            changepoints.extend(_find_changepoints(h, ts, rolling_mean, torque, window_size))

            plot_df = pd.DataFrame({"timestamp": ts, "moving_avg": rolling_mean, "moving_std": rolling_std}).dropna()
            if not plot_df.empty:
                daily = plot_df.set_index("timestamp").resample("D").mean().reset_index()
                daily["timestamp"] = daily["timestamp"].astype(str)
                plot_series[h] = daily.to_dict(orient="records")

            if i % 10 == 0 or i == len(heads):
                logger.info("torque_trend_analysis: processed %d/%d heads", i, len(heads))

    n_significant = sum(1 for v in per_head_trend.values() if v["significant"])
    n_increasing = sum(1 for v in per_head_trend.values() if v["direction"] == "increasing")
    n_decreasing = sum(1 for v in per_head_trend.values() if v["direction"] == "decreasing")
    mean_r_squared = float(np.mean([v["r_squared"] for v in per_head_trend.values()])) if per_head_trend else float("nan")
    summary = (
        f"Torque trend across {len(per_head_trend)} heads: {n_significant} show a statistically significant "
        f"trend ({n_increasing} increasing, {n_decreasing} decreasing). {len(changepoints)} changepoint(s) detected."
    )
    if per_head_trend and mean_r_squared < 0.01:
        summary += (
            f" CAVEAT: mean r² across heads is only {mean_r_squared:.4f} -- with this many events, p < 0.05 is easy "
            f"to hit even when time explains almost none of the variance. Read 'significant' as statistically real, "
            f"not necessarily practically meaningful; check r_squared and slope_nm_per_day before acting on it."
        )

    return {
        "summary": summary,
        "window_size": window_size,
        "per_head_trend": per_head_trend,
        "changepoints": changepoints,
        "plot_series": plot_series,
    }


def _apply_status_filter(events: pd.DataFrame, filter_status: str) -> pd.DataFrame:
    if filter_status == "successful_only":
        return successful_closures(events)
    if filter_status == "failed_only":
        return failed_closures(events)
    if filter_status == "all_real":
        return real_closures(events)
    return events  # "all"


def _group_key(events: pd.DataFrame, group_by: str) -> pd.Series:
    if group_by == "overall":
        return pd.Series("overall", index=events.index)
    if group_by == "per_head":
        return events["head_id"]
    return events["timestamp"].dt.floor("D")  # daily


def _describe(s: pd.Series) -> pd.Series:
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = int(((s < lower) | (s > upper)).sum())
    return pd.Series(
        {
            "count": int(s.count()),
            "mean": s.mean(),
            "median": s.median(),
            "std": s.std(),
            "min": s.min(),
            "max": s.max(),
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
            "outlier_count": outliers,
        }
    )


def _rolling(series: pd.Series, ts: pd.Series, window_size: int | str) -> tuple[pd.Series, pd.Series]:
    if isinstance(window_size, str):
        indexed = series.copy()
        indexed.index = pd.DatetimeIndex(ts)
        mean = indexed.rolling(window_size).mean().reset_index(drop=True)
        std = indexed.rolling(window_size).std().reset_index(drop=True)
        return mean, std
    min_periods = max(2, window_size // 10)
    return series.rolling(window_size, min_periods=min_periods).mean(), series.rolling(window_size, min_periods=min_periods).std()


def _find_changepoints(
    head_id: str, ts: pd.Series, rolling_mean: pd.Series, torque: pd.Series, window_size: int | str
) -> list[dict[str, Any]]:
    overall_std = torque.std()
    if not overall_std or overall_std <= 0:
        return []
    lag = max(10, window_size // 10) if isinstance(window_size, int) else 10
    shift = rolling_mean.diff(lag).abs()
    flagged = shift > 2 * overall_std
    if not flagged.any():
        return []
    run_id = (flagged != flagged.shift()).cumsum()
    points = []
    for _, idx in ts[flagged].groupby(run_id[flagged]).groups.items():
        first = idx[0]
        points.append({"head_id": head_id, "timestamp": str(ts.loc[first]), "shift_nm": float(shift.loc[first])})
    return points
