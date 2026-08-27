# Tool 8 (capping_speed_analysis) and Tool 9 (idle_analysis).

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration, real_closures

logger = logging.getLogger(__name__)


def capping_speed_analysis(
    events: pd.DataFrame,
    idle_periods: pd.DataFrame | None = None,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
    exclude_idle: bool = True,
) -> dict[str, Any]:
    """Analyze production speed (pieces/hour), both machine-wide and per head.

    Two different things are reported, deliberately not conflated (a code
    review flagged the earlier version of this tool for only returning the
    per-head-average number under the generic name "overall speed", which
    reads as "how fast is the machine" when it's actually "how fast is one
    head" -- on the full archive the two differ by ~29x):

    - `machine_wide_throughput_pph`: true production rate of the whole
      machine -- inferred_closure_count summed across ALL heads per hour,
      i.e. actual pieces/hour, not an average of individual head speeds.
    - `per_head_average_speed_pph`: mean of each individual event's
      capping_speed_pph (already accounts for inferred_closure_count -- see
      normalize.compute_derived_metrics) -- useful for "is a head slower than
      its peers", not for "how much does the machine make".

    No Load (status 2) closures are always excluded -- they have no
    meaningful throughput. If exclude_idle=True and idle_periods is supplied,
    events whose timestamp falls inside a known idle window are removed from
    production, and a speed sample whose interval since the previous closure
    crosses an idle boundary is excluded from the per-head speed statistics.
    The post-idle closure itself remains in machine-wide production totals:
    only its misleading speed sample is discarded. Without idle_periods,
    exclude_idle is a no-op (logged as a warning) since there is nothing to
    filter against.

    Returns a dict with `summary`, `machine_wide_throughput_pph`,
    `machine_wide_timeline` (each hour tagged `gap_affected` -- see below),
    `per_head_average_speed_pph`, `per_head_timeline`, `per_head_variability`
    (mean/std/CV per head), `speed_anomalies` (hours where machine-wide
    throughput is > 2 sigma from its own hourly average, tagged "slowdown" or
    "speedup"), `gap_affected_hours`, and
    `idle_affected_speed_samples_excluded`.

    Gap-affected hours: an event with data_quality="gap" (see
    normalize.compute_derived_metrics / closures.py) bundles every closure
    that happened during an unsampled stretch into the single hour where the
    data resumes -- e.g. the 2026-02-04 gap resolves at 14:00 and dumps
    ~6,800 backlogged closures into that one hour, reading as 236,795 pph
    (4x the machine's real peak) instead of the ~6-7 hours they actually
    happened over. The total *count* is still correct (those closures did
    happen), only their *hourly attribution* is wrong, so these hours are
    flagged rather than dropped -- dropping would silently undercount.
    """
    events = filter_events(events, head_filter, time_range)
    production = real_closures(events).dropna(subset=["capping_speed_pph"])
    speed_samples = production
    idle_affected_speed_samples_excluded = 0

    if exclude_idle:
        if idle_periods is not None and not idle_periods.empty:
            production = _drop_events_in_idle_windows(production, idle_periods)
            speed_samples, idle_affected_speed_samples_excluded = _drop_idle_affected_speed_samples(
                production, idle_periods
            )
        else:
            logger.warning("exclude_idle=True but no idle_periods supplied; skipping idle-window filtering")

    if production.empty:
        return {
            "summary": "No production closures match the given filters.",
            "machine_wide_throughput_pph": {},
            "per_head_average_speed_pph": {},
            "idle_affected_speed_samples_excluded": idle_affected_speed_samples_excluded,
            "hours_with_recorded_production": 0,
        }

    with log_duration(f"capping_speed_analysis over {len(production):,} events"):
        indexed = production.set_index("timestamp")

        machine_hourly = indexed["inferred_closure_count"].resample("h").sum()
        machine_hourly = machine_hourly[machine_hourly > 0]
        machine_wide = {
            "mean": float(machine_hourly.mean()),
            "min": float(machine_hourly.min()),
            "max": float(machine_hourly.max()),
            "std": float(machine_hourly.std()),
        }

        gap_events = indexed[indexed["data_quality"] == "gap"]
        gap_closures_by_hour = gap_events["inferred_closure_count"].groupby(gap_events.index.floor("h")).sum()
        gap_hours = set(gap_closures_by_hour.index)

        machine_timeline = [
            {"hour": str(idx), "pieces_per_hour": float(v), "gap_affected": idx in gap_hours}
            for idx, v in machine_hourly.items()
        ]
        gap_affected_hours = [
            {
                "hour": str(idx),
                "pieces_per_hour": float(machine_hourly.get(idx, 0.0)),
                "backlogged_closures": int(n),
                "reason": (
                    f"{int(n)} closures from an unsampled gap were all attributed to this one hour "
                    "when the data resumed -- they really happened over the gap's duration, not in "
                    "this hour alone, so this hour's rate reads inflated (total count is still correct)."
                ),
            }
            for idx, n in gap_closures_by_hour.items()
        ]

        speed_indexed = speed_samples.set_index("timestamp")
        speed = speed_samples["capping_speed_pph"]
        per_head_speed = {"mean": float(speed.mean()), "min": float(speed.min()), "max": float(speed.max()), "std": float(speed.std())}
        per_head_hourly = speed_indexed["capping_speed_pph"].resample("h").mean().dropna()
        per_head_timeline = [{"hour": str(idx), "mean_speed_pph": float(v)} for idx, v in per_head_hourly.items()]

        per_head = speed_samples.groupby("head_id", observed=True)["capping_speed_pph"].agg(mean="mean", std="std")
        per_head["cv"] = per_head["std"] / per_head["mean"].replace(0, np.nan)
        per_head = per_head.reset_index()
        per_head["head_id"] = per_head["head_id"].astype(str)

        anomalies = []
        if len(machine_hourly) >= 2:
            h_avg, h_std = machine_hourly.mean(), machine_hourly.std(ddof=0)
            if h_std and h_std > 0:
                mask = (machine_hourly - h_avg).abs() > 2 * h_std
                for idx, v in machine_hourly[mask].items():
                    anomalies.append({"hour": str(idx), "pieces_per_hour": float(v), "type": "slowdown" if v < h_avg else "speedup"})

    summary = (
        f"Machine-wide throughput: {machine_wide['mean']:.0f} pph, averaged across "
        f"{len(machine_hourly):,} hour(s) with recorded closures "
        f"(range {machine_wide['min']:.0f}-{machine_wide['max']:.0f}). "
        f"Per-head average: {per_head_speed['mean']:.1f} pph/head. "
        f"{len(anomalies)} hour(s) flagged as significant throughput anomalies."
    )
    if idle_affected_speed_samples_excluded:
        summary += (
            f" Excluded {idle_affected_speed_samples_excluded:,} per-head speed sample(s) whose measurement "
            "interval crossed an idle period; their closures remain in production totals."
        )
    if gap_affected_hours:
        summary += (
            f" WARNING: {len(gap_affected_hours)} hour(s) include gap-backlogged closures and read "
            f"artificially high (e.g. {gap_affected_hours[0]['hour']} shows "
            f"{gap_affected_hours[0]['pieces_per_hour']:.0f} pph) -- see gap_affected_hours."
        )

    return {
        "summary": summary,
        "machine_wide_throughput_pph": machine_wide,
        "machine_wide_timeline": machine_timeline,
        "per_head_average_speed_pph": per_head_speed,
        "per_head_timeline": per_head_timeline,
        "per_head_variability": per_head.to_dict(orient="records"),
        "speed_anomalies": anomalies,
        "gap_affected_hours": gap_affected_hours,
        "idle_affected_speed_samples_excluded": idle_affected_speed_samples_excluded,
        "hours_with_recorded_production": int(len(machine_hourly)),
    }


def idle_analysis(
    idle_periods: pd.DataFrame,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Analyze machine idle periods (all 36 heads simultaneously No Load, from
    Layer-1's idle_periods.parquet).

    Returns a dict with `summary`, `utilization_rate` (productive_time /
    total_time), `idle_period_stats` (count, mean/median/max duration, total
    idle seconds), `hourly_idle_pattern` (idle seconds attributed to each
    hour-of-day, 0-23 -- for shift-pattern detection; a period spanning
    several hours has its duration split across the hours it actually
    overlaps), and `top_10_longest_idle_periods`.

    When `time_range` is supplied, idle periods that only partially overlap
    the requested window are clipped to its boundaries before durations and
    utilization are calculated. A window with no overlapping idle period is
    therefore a valid 100%-utilization result, not an unknown value.
    """
    total_window_seconds: float | None = None
    if time_range:
        start, end = pd.Timestamp(time_range[0]), pd.Timestamp(time_range[1])
        if end <= start:
            raise ValueError("time_range end must be after start")

        overlaps = (idle_periods["start_time"] < end) & (idle_periods["end_time"] > start)
        idle_periods = idle_periods.loc[overlaps].copy()
        if not idle_periods.empty:
            idle_periods["start_time"] = idle_periods["start_time"].clip(lower=start)
            idle_periods["end_time"] = idle_periods["end_time"].clip(upper=end)
            idle_periods["duration_seconds"] = (
                idle_periods["end_time"] - idle_periods["start_time"]
            ).dt.total_seconds()
        total_window_seconds = (end - start).total_seconds()

    if idle_periods.empty:
        if total_window_seconds is not None:
            return {
                "summary": "No idle periods in range. Utilization rate: 100.0%.",
                "utilization_rate": 1.0,
                "idle_period_stats": {
                    "count": 0,
                    "mean_duration_s": 0.0,
                    "median_duration_s": 0.0,
                    "max_duration_s": 0.0,
                    "total_idle_seconds": 0.0,
                },
                "hourly_idle_pattern": {hour: 0.0 for hour in range(24)},
                "top_10_longest_idle_periods": [],
                "observation_window_hours": total_window_seconds / 3600.0,
                "productive_hours": total_window_seconds / 3600.0,
            }
        return {"summary": "No idle periods in range.", "utilization_rate": float("nan"), "idle_period_stats": {}}

    with log_duration(f"idle_analysis over {len(idle_periods)} idle periods"):
        total_idle_seconds = float(idle_periods["duration_seconds"].sum())
        if total_window_seconds is None:
            total_window_seconds = (idle_periods["end_time"].max() - idle_periods["start_time"].min()).total_seconds()
        productive_seconds = max(total_window_seconds - total_idle_seconds, 0.0)
        utilization_rate = productive_seconds / total_window_seconds if total_window_seconds else float("nan")

        stats = {
            "count": int(len(idle_periods)),
            "mean_duration_s": float(idle_periods["duration_seconds"].mean()),
            "median_duration_s": float(idle_periods["duration_seconds"].median()),
            "max_duration_s": float(idle_periods["duration_seconds"].max()),
            "total_idle_seconds": total_idle_seconds,
        }

        hourly_pattern = _idle_seconds_by_hour_of_day(idle_periods)

        longest = idle_periods.sort_values("duration_seconds", ascending=False).head(10)
        longest_list = [
            {"start_time": str(r.start_time), "end_time": str(r.end_time), "duration_seconds": float(r.duration_seconds)}
            for r in longest.itertuples()
        ]

    summary = (
        f"Utilization rate: {utilization_rate * 100:.1f}% over a "
        f"{total_window_seconds / 3600:.1f}h observation window "
        f"({productive_seconds / 3600:.1f}h productive / "
        f"{total_idle_seconds / 3600:.1f}h idle). {stats['count']} idle periods, "
        f"median {stats['median_duration_s']:.0f}s, longest {stats['max_duration_s'] / 3600:.1f}h."
    )

    return {
        "summary": summary,
        "utilization_rate": utilization_rate,
        "idle_period_stats": stats,
        "hourly_idle_pattern": hourly_pattern,
        "top_10_longest_idle_periods": longest_list,
        "observation_window_hours": total_window_seconds / 3600.0,
        "productive_hours": productive_seconds / 3600.0,
    }


def _drop_events_in_idle_windows(production: pd.DataFrame, idle_periods: pd.DataFrame) -> pd.DataFrame:
    idle_sorted = idle_periods.sort_values("start_time")
    production_sorted = production.sort_values("timestamp")
    matched_windows = pd.merge_asof(
        production_sorted[["timestamp"]],
        idle_sorted[["start_time", "end_time"]],
        left_on="timestamp",
        right_on="start_time",
        direction="backward",
    )
    in_idle = (
        (matched_windows["timestamp"] >= matched_windows["start_time"])
        & (matched_windows["timestamp"] <= matched_windows["end_time"])
    ).fillna(False)
    return production_sorted.loc[~in_idle.to_numpy()]


def _drop_idle_affected_speed_samples(
    production: pd.DataFrame,
    idle_periods: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Remove only speed samples whose measurement interval crosses idle.

    `time_since_last_closure` lets us reconstruct the timestamp at which each
    speed interval began. Matching each event to the most recent idle end then
    identifies the first sample after that idle: previous_timestamp <= idle_end
    < current_timestamp. The event remains in `production` for throughput and
    closure totals; this filtered frame is used only for per-head speed metrics.
    """
    if production.empty or idle_periods.empty:
        return production, 0

    idle_ends = idle_periods[["end_time"]].dropna().drop_duplicates().sort_values("end_time")
    if idle_ends.empty:
        return production, 0

    production_sorted = production.sort_values("timestamp")
    matched_ends = pd.merge_asof(
        production_sorted[["timestamp", "time_since_last_closure"]],
        idle_ends,
        left_on="timestamp",
        right_on="end_time",
        direction="backward",
    )
    previous_timestamp = matched_ends["timestamp"] - pd.to_timedelta(
        matched_ends["time_since_last_closure"], unit="s"
    )
    crosses_idle_end = (
        matched_ends["end_time"].notna()
        & (previous_timestamp <= matched_ends["end_time"])
        & (matched_ends["timestamp"] > matched_ends["end_time"])
    )
    excluded = int(crosses_idle_end.sum())
    return production_sorted.loc[~crosses_idle_end.to_numpy()], excluded


def _idle_seconds_by_hour_of_day(idle_periods: pd.DataFrame) -> dict[int, float]:
    buckets = {h: 0.0 for h in range(24)}
    for start, end in zip(idle_periods["start_time"], idle_periods["end_time"]):
        cursor = start
        while cursor < end:
            hour_end = cursor.floor("h") + pd.Timedelta(hours=1)
            segment_end = min(hour_end, end)
            buckets[cursor.hour] += (segment_end - cursor).total_seconds()
            cursor = segment_end
    return buckets
