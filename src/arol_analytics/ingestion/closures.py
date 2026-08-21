# Closure-event detection from per-head cumulative counters.

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from arol_analytics.ingestion.schema import (
    DATA_QUALITY_AGGREGATED,
    DATA_QUALITY_GAP,
    DATA_QUALITY_SINGLE,
    GAP_FACTOR,
    TIMESTAMP_COLUMN,
)

EVENTS_COLUMNS = [
    "timestamp",
    "head_id",
    "counter",
    "counter_delta",
    "accepted_closure_count",
    "data_quality",
    "segment_id",
    "torque_nm",
    "status_code",
    "source_file",
]


@dataclass
class CarryState:
    """State threaded from one file to the next so counter increments, reset
    segments, and sampling-gap detection are all correct across file
    boundaries, without ever loading more than one file's data at a time."""

    last_count: dict[str, float] = field(default_factory=dict)
    last_ts: pd.Timestamp | None = None
    segment_id: dict[str, int] = field(default_factory=dict)


def detect_closures(
    df: pd.DataFrame,
    head_ids: list[str],
    source_file: str,
    carry_state: CarryState,
) -> tuple[pd.DataFrame, CarryState]:
    """Detect counter-increment events for every head in a single file.

    A closure event is any row where H{nn} Count is greater than the last
    *valid* value seen for that head. "Valid" matters: corrupted Count
    readings (quality.mask_corrupted_count_readings has already set them to
    NaN) are skipped via ffill rather than compared against literally, so a
    reporting glitch is never misread as a real reset-and-recount.

    A counter can legitimately jump by more than 1 between two observed rows
    -- either because several closures happened inside one sampling gap
    (`data_quality="gap"`), or, rarely, because more than one closure landed
    inside a single normal ~1s sampling interval (`data_quality="aggregated"`).
    Either way we only know one torque/status/timestamp for the whole jump, so
    we record ONE row with `counter_delta` (the jump size) and
    `accepted_closure_count` (how many closures to count towards production
    totals -- currently always == counter_delta: we don't have a principled
    basis yet to call a jump "implausible" rather than "real but unsampled";
    see the module docstring in pipeline.py).

    Resets (`Count` decreasing) are detected directly on the raw per-row
    sequence -- not reconstructed from the extracted events afterwards -- so
    `segment_id` (used by normalize.dedupe_events to scope duplicate
    detection) is correct even when the very first event after a reset
    already matches or exceeds the pre-reset peak.
    """
    ts = df[TIMESTAMP_COLUMN]
    prev_ts = ts.shift(1)
    time_gap = ts - prev_ts
    if carry_state.last_ts is not None:
        prev_ts.iloc[0] = carry_state.last_ts
        if len(ts):
            time_gap.iloc[0] = ts.iloc[0] - carry_state.last_ts
    time_gap_seconds = time_gap.dt.total_seconds()

    median_interval = time_gap_seconds.median()
    if not median_interval or pd.isna(median_interval) or median_interval <= 0:
        median_interval = 1.0
    is_gap_row = time_gap_seconds > GAP_FACTOR * median_interval

    per_head_frames = []
    new_last_count: dict[str, float] = {}
    new_segment_id: dict[str, int] = {}

    for h in head_ids:
        count = df[f"{h} Count"]
        filled = count.ffill()
        prev_count = filled.shift(1)
        if h in carry_state.last_count:
            prev_count.iloc[0] = carry_state.last_count[h]

        delta = count - prev_count  # NaN wherever `count` itself is a masked/corrupted row
        is_reset = delta < 0
        start_segment = carry_state.segment_id.get(h, 0)
        segment = start_segment + is_reset.cumsum()

        incremented = delta > 0
        if incremented.any():
            idx = incremented[incremented].index
            d = delta.loc[idx]
            quality = np.where(
                is_gap_row.loc[idx], DATA_QUALITY_GAP, np.where(d > 1, DATA_QUALITY_AGGREGATED, DATA_QUALITY_SINGLE)
            )
            per_head_frames.append(
                pd.DataFrame(
                    {
                        "timestamp": ts.loc[idx].values,
                        "head_id": h,
                        "counter": count.loc[idx].values,
                        "counter_delta": d.values,
                        "accepted_closure_count": d.values,
                        "data_quality": quality,
                        "segment_id": segment.loc[idx].values,
                        "torque_nm": df.loc[idx, f"{h} AppTorque"].values,
                        "status_code": df.loc[idx, f"{h} Status"].values,
                        "source_file": source_file,
                    }
                )
            )

        last_valid = filled.dropna()
        if len(last_valid):
            new_last_count[h] = float(last_valid.iloc[-1])
        elif h in carry_state.last_count:
            new_last_count[h] = carry_state.last_count[h]

        new_segment_id[h] = int(segment.iloc[-1]) if len(segment) else start_segment

    if per_head_frames:
        events = pd.concat(per_head_frames, ignore_index=True)
        events = events.sort_values("timestamp").reset_index(drop=True)
    else:
        events = pd.DataFrame(columns=EVENTS_COLUMNS)

    new_carry_state = CarryState(
        last_count=new_last_count,
        last_ts=ts.iloc[-1] if len(ts) else carry_state.last_ts,
        segment_id=new_segment_id,
    )
    return events, new_carry_state
