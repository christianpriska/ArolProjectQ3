#Closure-event detection from per-head cumulative counters.

from __future__ import annotations

import pandas as pd

from arol_analytics.ingestion.schema import TIMESTAMP_COLUMN

# per-head last-seen counter value, carried across files so a closure that
# lands on the very first row of a file is not silently dropped
CarryState = dict[str, float]


def detect_closures(
    df: pd.DataFrame,
    head_ids: list[str],
    source_file: str,
    carry_state: CarryState,
) -> tuple[pd.DataFrame, CarryState]:
    """Detect counter-increment events for every head in a single file.

    A closure is any row where H{nn} Count is strictly greater than the
    previous value for that head (previous row in this file, or the last
    value carried over from the previous file for the file's first row).
    Counter decreases are resets, not closures, and are intentionally
    excluded here.
    """
    ts = df[TIMESTAMP_COLUMN]
    per_head_frames = []
    new_carry_state: CarryState = {}

    for h in head_ids:
        count = df[f"{h} Count"]
        prev = count.shift(1)
        if h in carry_state:
            prev.iloc[0] = carry_state[h]
        incremented = count > prev

        if incremented.any():
            idx = incremented[incremented].index
            per_head_frames.append(
                pd.DataFrame(
                    {
                        "timestamp": ts.loc[idx].values,
                        "head_id": h,
                        "counter": count.loc[idx].values,
                        "torque_nm": df.loc[idx, f"{h} AppTorque"].values,
                        "status_code": df.loc[idx, f"{h} Status"].values,
                        "source_file": source_file,
                    }
                )
            )

        last_valid = count.dropna()
        if len(last_valid):
            new_carry_state[h] = float(last_valid.iloc[-1])
        elif h in carry_state:
            new_carry_state[h] = carry_state[h]

    if per_head_frames:
        events = pd.concat(per_head_frames, ignore_index=True)
        events = events.sort_values("timestamp").reset_index(drop=True)
    else:
        events = pd.DataFrame(
            columns=["timestamp", "head_id", "counter", "torque_nm", "status_code", "source_file"]
        )

    return events, new_carry_state
