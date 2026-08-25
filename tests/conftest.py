# Shared pytest fixtures for the AROL test suite. All data here is synthetic --
# no real dataset is required to run these tests.
#
# `PYTHONPATH=src` is not required to run pytest from the repo root: this file
# adds src/ to sys.path itself, exactly like the older ad-hoc test scripts did.

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arol_analytics.ingestion.normalize import add_status_fields, compute_derived_metrics  # noqa: E402

HEADS = ["H01", "H02", "H03"]


# ---------------------------------------------------------------------------
# Layer 1 (ingestion) fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_raw_df() -> pd.DataFrame:
    """~500-row synthetic raw wide-format telemetry frame, 3 heads (H01-H03),
    1-second sampling, columns grouped by field (Count.., AppTorque.., Status..)
    exactly like the real archive.

    Construction (verified against ingestion.closures.detect_closures /
    ingestion.idle.detect_idle_runs_for_file directly -- these are not
    hand-computed guesses):
      - rows 0-299 and 360-499 (440 rows): normal production.
          H01 Count +1 every row.
          H02 Count +1 every other row.
          H03 Count flat for the first 50 rows, then +1 every row.
        H01 has one reject (status=9) at row 100; H03 has two rejects
        (status=65) at rows 150-151 -- all outside the idle block below.
      - rows 300-359 (60 rows): idle -- all 3 heads simultaneously status=2,
        Count flat (no closures), torque 0.

    Verified closure counts from detect_closures (a fresh CarryState(), single
    file, so each head's very first row has no prior value and is never itself
    a closure): H01=439, H02=220, H03=390 (1,049 total), all data_quality="single".
    Verified idle period from detect_idle_runs_for_file + finalize_idle_periods
    (IDLE_MIN_ROWS=30 <= 60): exactly one period, 2026-01-01 00:05:00 ->
    2026-01-01 00:05:59 (60 rows, 59.0s).
    """
    n = 500
    start = pd.Timestamp("2026-01-01T00:00:00")
    timestamps = [start + pd.Timedelta(seconds=i) for i in range(n)]

    def _production_series(step_every: int) -> np.ndarray:
        values = np.zeros(n)
        c = 0.0
        toggle = 0
        for i in range(n):
            if 300 <= i < 360:
                values[i] = c
                continue
            toggle += 1
            if toggle % step_every == 0:
                c += 1
            values[i] = c
        return values

    h01_count = _production_series(step_every=1)
    h02_count = _production_series(step_every=2)

    h03_count = np.zeros(n)
    c = 0.0
    for i in range(n):
        if 300 <= i < 360 or i < 50:
            h03_count[i] = c
        else:
            c += 1
            h03_count[i] = c

    status = np.zeros(n)
    status[300:360] = 2  # idle block, all heads simultaneously no-load
    h01_status, h02_status, h03_status = status.copy(), status.copy(), status.copy()
    h01_status[100] = 9  # EarlyRaise, reject
    h03_status[150] = 65  # RotatingAtRaise, reject
    h03_status[151] = 65

    h01_torque = np.where(h01_status == 2, 0.0, 2.5)
    h02_torque = np.where(h02_status == 2, 0.0, 2.0)
    h03_torque = np.where(h03_status == 2, 0.0, 1.8)

    df = pd.DataFrame({"timestamp": timestamps})
    # Columns grouped by field across all heads, mirroring the real archive layout.
    df["H01 Count"] = h01_count
    df["H02 Count"] = h02_count
    df["H03 Count"] = h03_count
    df["H01 AppTorque"] = h01_torque
    df["H02 AppTorque"] = h02_torque
    df["H03 AppTorque"] = h03_torque
    df["H01 Status"] = h01_status
    df["H02 Status"] = h02_status
    df["H03 Status"] = h03_status
    return df


@pytest.fixture
def event_block_factory() -> Callable[..., pd.DataFrame]:
    """Factory for a minimal, already-normalized-shape block of closure events
    for one head: timestamp, head_id, counter, counter_delta,
    inferred_closure_count, data_quality, torque_nm, status_code, source_file --
    i.e. the pre-`normalize.add_status_fields` shape. Tests combine several
    blocks and run them through the real `add_status_fields` +
    `compute_derived_metrics` so derived columns (status_label, is_reject,
    is_successful, classification, time_since_last_closure, capping_speed_pph)
    are never hand-duplicated/re-implemented in the test suite.
    """

    def _make(
        head_id: str,
        start: str,
        n: int,
        freq_minutes: float,
        status_code: int | list[int],
        torque_nm: float | list[float],
        source_file: str,
        counter_start: int = 1,
    ) -> pd.DataFrame:
        ts = pd.date_range(start=start, periods=n, freq=pd.Timedelta(minutes=freq_minutes))
        return pd.DataFrame(
            {
                "timestamp": ts,
                "head_id": head_id,
                "segment_id": 0,  # no reset within a block -- one segment throughout
                "counter": range(counter_start, counter_start + n),
                "counter_delta": 1,
                "inferred_closure_count": 1,
                "data_quality": "single",
                "torque_nm": torque_nm,
                "status_code": status_code,
                "source_file": source_file,
            }
        )

    return _make


@pytest.fixture
def synthetic_closure_events(event_block_factory: Callable[..., pd.DataFrame]) -> pd.DataFrame:
    """A clean, already-normalized closure_events-shaped DataFrame: 200 events,
    3 heads, spanning January and February 2026, with known per-head success
    rates by construction:
      - H01: 80 events, all of January, all successful -> 100% success rate,
        mean torque (successful) = 2.00 Nm.
      - H02: 70 events, 35 successful in January + 35 failed in February ->
        50% success rate, mean torque (successful) = 2.20 Nm.
      - H03: 50 events, all of February, all failed -> 0% success rate.

    Verified directly against success_rate_analysis/head_comparison: per-head
    rates come out to exactly 100.0 / 50.0 / 0.0, February-only filtering
    returns exactly 85 rows (H02's 35 + H03's 50), January-only exactly 115
    (H01's 80 + H02's 35).
    """
    h01 = event_block_factory("H01", "2026-01-01T00:00:00", 80, 60, 0, 2.00, "synthetic_2026-01.csv")
    h02a = event_block_factory("H02", "2026-01-01T00:30:00", 35, 60, 0, 2.20, "synthetic_2026-01.csv")
    h02b = event_block_factory(
        "H02", "2026-02-01T00:00:00", 35, 60, 65, 0.05, "synthetic_2026-02.csv", counter_start=36
    )
    h03 = event_block_factory("H03", "2026-02-01T00:15:00", 50, 60, 65, 1.80, "synthetic_2026-02.csv")

    raw = pd.concat([h01, h02a, h02b, h03], ignore_index=True)
    events = compute_derived_metrics(add_status_fields(raw))
    return events


@pytest.fixture
def synthetic_idle_periods() -> pd.DataFrame:
    """3 idle periods on 2026-01-01, total 3h idle, verified to give exactly
    70% utilization when analyzed over the 10h window
    2026-01-01T00:00:00 -> 2026-01-01T10:00:00 (idle_analysis(time_range=...)):
      - 01:00-02:00 (1h), 03:00-03:30 (0.5h), 05:00-06:30 (1.5h).
    """
    starts = ["2026-01-01T01:00:00", "2026-01-01T03:00:00", "2026-01-01T05:00:00"]
    ends = ["2026-01-01T02:00:00", "2026-01-01T03:30:00", "2026-01-01T06:30:00"]
    periods = pd.DataFrame({"start_time": pd.to_datetime(starts), "end_time": pd.to_datetime(ends)})
    periods["duration_seconds"] = (periods["end_time"] - periods["start_time"]).dt.total_seconds()
    return periods


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_csv_files(tmp_path: Path, synthetic_raw_df: pd.DataFrame) -> Path:
    """Writes `synthetic_raw_df` as two daily raw CSVs (rows 0-249 / 250-499)
    into a temp directory, formatted exactly like the real archive
    (ISO-ish timestamp string, no timezone suffix) -- for ingestion pipeline
    tests that need real files on disk (schema discovery, multi-file
    cross-boundary handling).
    """
    data_dir = tmp_path / "raw"
    data_dir.mkdir()

    df = synthetic_raw_df.copy()
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S.000")

    df.iloc[:250].to_csv(data_dir / "synthetic_2026-01-01.csv", index=False)
    df.iloc[250:].to_csv(data_dir / "synthetic_2026-01-02.csv", index=False)
    return data_dir


@pytest.fixture
def tmp_parquet_files(
    tmp_path: Path, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame
) -> Path:
    """Writes `synthetic_closure_events` / `synthetic_idle_periods` as Parquet
    into a temp directory laid out exactly like `data/processed/` (what
    `analytics.io.load_closure_events`/`load_idle_periods` and
    `agent.executor.ToolExecutor` expect) -- for analytics/agent tests that
    exercise the file-loading path instead of passing DataFrames directly.
    """
    data_dir = tmp_path / "processed"
    data_dir.mkdir()
    synthetic_closure_events.to_parquet(data_dir / "closure_events.parquet", index=False)
    synthetic_idle_periods.to_parquet(data_dir / "idle_periods.parquet", index=False)
    return data_dir
