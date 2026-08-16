#Idle-period detection: sustained windows where every head is No Load (status 2).

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from arol_analytics.ingestion.schema import FILE_BOUNDARY_TOLERANCE_SECONDS, IDLE_STATUS_CODE, TIMESTAMP_COLUMN


@dataclass
class Run:
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    n_rows: int
    touches_start: bool
    touches_end: bool


def _find_runs(df: pd.DataFrame, head_ids: list[str]) -> list[Run]:
    status_cols = [f"{h} Status" for h in head_ids]
    all_idle = (df[status_cols] == IDLE_STATUS_CODE).all(axis=1)
    if not all_idle.any():
        return []

    group_id = (all_idle != all_idle.shift()).cumsum()
    runs = []
    ts = df[TIMESTAMP_COLUMN]
    n = len(df)
    for gid, idx in df.groupby(group_id).groups.items():
        if not all_idle.loc[idx[0]]:
            continue
        start_pos, end_pos = idx[0], idx[-1]
        runs.append(
            Run(
                start_time=ts.loc[start_pos],
                end_time=ts.loc[end_pos],
                n_rows=len(idx),
                touches_start=(start_pos == 0),
                touches_end=(end_pos == n - 1),
            )
        )
    return runs


def detect_idle_runs_for_file(
    df: pd.DataFrame,
    head_ids: list[str],
    pending_run: Run | None,
) -> tuple[list[Run], Run | None]:
    """Find unfiltered idle runs in one file, merging with a run pending from
    the previous file if they are time-contiguous. Returns (closed_runs,
    new_pending_run) — new_pending_run is a run that touches the end of this
    file and may still extend into the next file.
    """
    runs = _find_runs(df, head_ids)
    if not runs:
        return ([pending_run] if pending_run else []), None

    if pending_run is not None:
        first = runs[0]
        gap = (first.start_time - pending_run.end_time).total_seconds()
        if first.touches_start and gap <= FILE_BOUNDARY_TOLERANCE_SECONDS:
            merged = Run(
                start_time=pending_run.start_time,
                end_time=first.end_time,
                n_rows=pending_run.n_rows + first.n_rows,
                touches_start=pending_run.touches_start,
                touches_end=first.touches_end,
            )
            runs[0] = merged
        else:
            runs.insert(0, pending_run)

    new_pending = runs[-1] if runs[-1].touches_end else None
    closed = runs[:-1] if new_pending is not None else runs
    return closed, new_pending


def finalize_idle_periods(runs: list[Run], min_rows: int, min_seconds: float) -> pd.DataFrame:
    kept = [
        r
        for r in runs
        if r.n_rows >= min_rows or (r.end_time - r.start_time).total_seconds() >= min_seconds
    ]
    if not kept:
        return pd.DataFrame(columns=["start_time", "end_time", "duration_seconds"])
    return pd.DataFrame(
        {
            "start_time": [r.start_time for r in kept],
            "end_time": [r.end_time for r in kept],
            "duration_seconds": [(r.end_time - r.start_time).total_seconds() for r in kept],
        }
    ).sort_values("start_time").reset_index(drop=True)
