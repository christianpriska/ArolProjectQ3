# Normalize raw closure events into the clean, long-format closure_events dataset.

from __future__ import annotations

import numpy as np
import pandas as pd

from arol_analytics.ingestion.schema import REJECT_STATUS_CODES, STATUS_LABELS, SUCCESS_STATUS_CODE


def add_status_fields(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["head_number"] = events["head_id"].str[1:].astype(int)
    events["counter"] = events["counter"].astype("Int64")
    events["counter_delta"] = events["counter_delta"].astype("Int64")
    events["inferred_closure_count"] = events["inferred_closure_count"].astype("Int64")
    status_int = events["status_code"].astype("Int64")
    events["status_code"] = status_int
    events["status_label"] = status_int.map(STATUS_LABELS).fillna("Unknown")
    events["is_reject"] = status_int.isin(REJECT_STATUS_CODES).fillna(False)
    events["is_successful"] = (status_int == SUCCESS_STATUS_CODE).fillna(False)

    def classify(code: object) -> str:
        if pd.isna(code):
            return "other"
        if code == SUCCESS_STATUS_CODE:
            return "successful"
        if code in REJECT_STATUS_CODES:
            return "failed"
        if code == 2:
            return "no_load"
        return "other"

    events["classification"] = status_int.map(classify)
    return events


def dedupe_events(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Drop duplicate (head, counter) events within the same reset segment.

    Counter values legitimately repeat *across* resets (a head that resets
    and counts back up will pass through values it has already emitted), so
    duplicates are only meaningful within an unbroken monotonic run for a
    given head. `segment_id` is computed by closures.detect_closures directly
    from the raw per-row counter sequence (not reconstructed from the
    extracted events here), so it's correct even when the very first event
    after a real reset already matches or exceeds the pre-reset peak.
    """
    events = events.sort_values(["head_id", "timestamp"]).reset_index(drop=True)

    dup_mask = events.duplicated(subset=["head_id", "segment_id", "counter"], keep="first")
    dup_counts = dup_mask.groupby(events["head_id"]).sum().astype(int)
    dup_counts = {h: int(c) for h, c in dup_counts.items() if c > 0}

    deduped = events.loc[~dup_mask].reset_index(drop=True)
    return deduped, dup_counts


def compute_derived_metrics(events: pd.DataFrame) -> pd.DataFrame:
    """time_since_last_closure and capping_speed_pph, per head, across the
    full (already file-concatenated) timeline.

    capping_speed_pph accounts for inferred_closure_count: if a single row
    represents 4 aggregated/gap-spanning closures (see closures.py), the
    implied rate is 4 closures over that interval, not 1 -- using
    inferred_closure_count instead of a flat "1 closure per row" avoids
    understating speed right after a gap or a multi-count jump.
    """
    events = events.sort_values(["head_id", "timestamp"]).reset_index(drop=True)
    events["timestamp"] = pd.to_datetime(events["timestamp"])
    time_since = events.groupby("head_id")["timestamp"].diff()
    events["time_since_last_closure"] = pd.to_timedelta(time_since).dt.total_seconds()

    secs = events["time_since_last_closure"]
    events["capping_speed_pph"] = np.where(secs > 0, 3600.0 * events["inferred_closure_count"] / secs, np.nan)
    return events
