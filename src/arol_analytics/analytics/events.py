# Tool 11: list_events -- raw, filtered event listing. The other tools all
# report statistics; this one answers "show me every X" questions where the
# user wants individual rows, not aggregates.

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from arol_analytics.analytics._common import TimeRange, failed_closures, filter_events, log_duration, real_closures, successful_closures

logger = logging.getLogger(__name__)

VALID_OUTCOME = {"all", "successful", "failed"}


def list_events(
    events: pd.DataFrame,
    outcome: str = "all",
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
    torque_min: float | None = None,
    torque_max: float | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Raw, filtered listing of individual closure events.

    outcome: "all" (real closures, i.e. excludes no-load), "successful", or
    "failed". torque_min/torque_max optionally bound torque_nm (either or
    both). `limit` caps how many rows come back (most recent first);
    `total_matching` is the true, uncapped count -- use it to answer "how
    many" questions even when `events` itself is truncated.

    Returns a dict with `summary`, `total_matching`, `events` (up to `limit`
    rows: timestamp, head_id, status_code, status_label, torque_nm), `truncated`.
    """
    if outcome not in VALID_OUTCOME:
        raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOME)}, got {outcome!r}")

    events = filter_events(events, head_filter, time_range)
    subset = real_closures(events)
    if outcome == "successful":
        subset = successful_closures(subset)
    elif outcome == "failed":
        subset = failed_closures(subset)

    if torque_min is not None:
        subset = subset[subset["torque_nm"] >= torque_min]
    if torque_max is not None:
        subset = subset[subset["torque_nm"] <= torque_max]

    total_matching = int(len(subset))
    if total_matching == 0:
        return {"summary": "No events match the given filters.", "total_matching": 0, "events": [], "truncated": False}

    with log_duration(f"list_events(outcome={outcome}) over {total_matching:,} matches"):
        top = subset.sort_values("timestamp", ascending=False).head(limit).copy()
        top["timestamp"] = top["timestamp"].astype(str)
        top["head_id"] = top["head_id"].astype(str)
        rows = top[["timestamp", "head_id", "status_code", "status_label", "torque_nm"]].to_dict(orient="records")

    truncated = total_matching > limit
    summary = f"{total_matching:,} event(s) match ({outcome})." + (f" Showing the {len(rows)} most recent." if truncated else "")
    return {"summary": summary, "total_matching": total_matching, "events": rows, "truncated": truncated}
