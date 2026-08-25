# Tool 1 (dataset_summary) and Tool 2 (success_rate_analysis).

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration, real_closures

logger = logging.getLogger(__name__)

VALID_GROUP_BY = {"overall", "per_head", "daily", "hourly", "per_file"}


def dataset_summary(
    events: pd.DataFrame,
    quality_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Basic overview of the closure_events dataset: size, heads, time range,
    status breakdown, overall success rate, and any data-quality flags carried
    over from the Layer-1 ingestion report (if supplied).

    Returns a dict with a human-readable `summary` plus: total_events, n_heads,
    heads, time_range, status_breakdown, overall_success_rate_pct,
    events_per_source_file, quality_flags, duplicates_removed_total (explicit
    even when 0 -- None only if no quality_report was supplied).
    """
    if events.empty:
        return {
            "summary": "No closure events in dataset.",
            "total_events": 0,
            "total_inferred_closures": 0,
            "closures_without_individual_status": 0,
        }

    n_heads = int(events["head_id"].nunique())
    heads = sorted(events["head_id"].astype(str).unique().tolist())

    start, end = events["timestamp"].min(), events["timestamp"].max()
    duration = end - start

    status_counts = events["classification"].value_counts().to_dict()
    inferred_total = int(events["inferred_closure_count"].sum())
    unobserved_total = inferred_total - len(events)
    successful = int(status_counts.get("successful", 0))
    failed = int(status_counts.get("failed", 0))
    no_load = int(status_counts.get("no_load", 0))
    other = int(status_counts.get("other", 0))
    denom = successful + failed
    success_rate = (successful / denom * 100.0) if denom else float("nan")

    events_per_file = events["source_file"].value_counts().sort_index().to_dict()

    quality_flags: list[str] = []
    duplicates_removed_total: int | None = None
    if quality_report:
        duplicates_removed_total = int(quality_report.get("duplicate_events_removed_total", 0))
        if quality_report.get("unexpected_status_codes"):
            quality_flags.append(f"unexpected status codes found: {quality_report['unexpected_status_codes']}")
        if quality_report.get("schema_errors"):
            quality_flags.append(f"{len(quality_report['schema_errors'])} file(s) rejected during ingestion")
        if quality_report.get("boundary_gaps"):
            quality_flags.append(f"{len(quality_report['boundary_gaps'])} sampling gap(s) at file boundaries")
        if quality_report.get("counter_resets_total"):
            quality_flags.append(f"{quality_report['counter_resets_total']} counter reset(s) across the archive")
        if duplicates_removed_total:
            quality_flags.append(f"{duplicates_removed_total} duplicate closure(s) removed during ingestion")

    dedup_sentence = (
        f" Duplicate (head, counter) events removed during ingestion: {duplicates_removed_total:,} "
        f"({'none found -- the raw data had no exact repeats' if duplicates_removed_total == 0 else 'see quality_flags for the per-head breakdown'})."
        if duplicates_removed_total is not None
        else ""
    )
    summary = (
        f"{len(events):,} observed closure events representing {inferred_total:,} inferred closures "
        f"across {n_heads} heads, {start} to {end} ({duration}). "
        f"Observed-status success rate (excluding no-load): {success_rate:.2f}% "
        f"({successful:,} successful / {failed:,} failed). "
        f"Closures without an individual status observation: {unobserved_total:,}. "
        f"No-load events: {no_load:,}."
        f"{dedup_sentence}"
    )

    return {
        "summary": summary,
        "duplicates_removed_total": duplicates_removed_total,
        "total_events": int(len(events)),
        "total_inferred_closures": inferred_total,
        "closures_without_individual_status": unobserved_total,
        "n_heads": n_heads,
        "heads": heads,
        "time_range": {"start": start, "end": end, "duration_days": duration.total_seconds() / 86400.0},
        "status_breakdown": {"successful": successful, "failed": failed, "no_load": no_load, "other": other},
        "overall_success_rate_pct": success_rate,
        "events_per_source_file": events_per_file,
        "quality_flags": quality_flags,
    }


def success_rate_analysis(
    events: pd.DataFrame,
    group_by: str = "overall",
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Success rate (successful / (successful + failed)) with flexible grouping.

    No Load (status 2) events are always excluded -- they're not real capping
    attempts. "daily"/"hourly" bucket the timeline itself (not hour-of-day
    across days -- see idle_analysis for that pattern).

    group_by: "overall", "per_head", "daily", "hourly", or "per_file".

    Returns a dict with `summary`, `group_by`, `table` (one row per group:
    group, total_closures/status observations, inferred_closures, successful,
    failed, other_count, success_rate_pct,
    and for per_head also rank_worst_to_best), and `flagged_groups` (groups
    whose success rate is > 2 sigma below the average across groups).
    """
    if group_by not in VALID_GROUP_BY:
        raise ValueError(f"group_by must be one of {sorted(VALID_GROUP_BY)}, got {group_by!r}")

    events = filter_events(events, head_filter, time_range)
    real = real_closures(events)
    if real.empty:
        return {"summary": "No real (non-idle) closures match the given filters.", "group_by": group_by, "table": [], "flagged_groups": []}

    with log_duration(f"success_rate_analysis(group_by={group_by})"):
        key = _group_key(real, group_by)
        grouped = real.groupby(key, observed=True)
        table = grouped.agg(
            total_closures=("is_successful", "size"),
            inferred_closures=("inferred_closure_count", "sum"),
            successful=("is_successful", "sum"),
            failed=("is_reject", "sum"),
        ).reset_index(names="group")
        table["other_count"] = table["total_closures"] - table["successful"] - table["failed"]
        table["closures_without_individual_status"] = table["inferred_closures"] - table["total_closures"]
        denom = table["successful"] + table["failed"]
        table["success_rate_pct"] = np.where(denom > 0, table["successful"] / denom * 100.0, np.nan)

        flagged: list[str] = []
        rates = table["success_rate_pct"].dropna()
        if len(rates) >= 2:
            avg, std = rates.mean(), rates.std(ddof=0)
            if std > 0:
                mask = table["success_rate_pct"] < (avg - 2 * std)
                flagged = table.loc[mask, "group"].astype(str).tolist()

        if group_by == "per_head":
            table = table.sort_values("success_rate_pct", ascending=True, na_position="first").reset_index(drop=True)
            table["rank_worst_to_best"] = range(1, len(table) + 1)
        else:
            table = table.sort_values("group").reset_index(drop=True)

    overall_rate = table["success_rate_pct"].mean()
    summary = f"Success rate ({group_by}): {len(table)} group(s), avg {overall_rate:.2f}%."
    summary += f" {len(flagged)} group(s) >2σ below average: {flagged}." if flagged else " No groups flagged as significantly underperforming."

    table["group"] = table["group"].astype(str)
    return {
        "summary": summary,
        "group_by": group_by,
        "table": table.to_dict(orient="records"),
        "flagged_groups": flagged,
    }


def _group_key(events: pd.DataFrame, group_by: str) -> pd.Series:
    if group_by == "overall":
        return pd.Series("overall", index=events.index)
    if group_by == "per_head":
        return events["head_id"]
    if group_by == "daily":
        return events["timestamp"].dt.floor("D")
    if group_by == "hourly":
        return events["timestamp"].dt.floor("h")
    return events["source_file"]  # per_file
