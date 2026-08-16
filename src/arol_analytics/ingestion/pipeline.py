"""Main ingestion pipeline: raw wide-format CSVs -> clean, long-format datasets.

Discrepancies found between the project spec and the real archive
(`src/data/telemetry_MCC777eda3db57348ef8a3113a642ae74db_*/*.csv`), confirmed
by exhaustively scanning all 89 files before writing this module:

- Only 36 heads (H01-H36) are present, not 48.
- Columns are grouped by field, not interleaved per head: all 36 `Count`
  columns, then all 36 `AppTorque` columns, then all 36 `Status` columns —
  not `H01 Count, H01 AppTorque, H01 Status, H02 Count, ...` as a literal
  reading of "per-head triplets" might suggest.
- `timestamp` has no `Z`/UTC suffix (`2026-04-07T17:00:00.000`, not
  `...Z`) and is NOT a stable UTC clock: the daily file boundary shifts from
  16:00 to 17:00 (in the previous day) right at the 2026-03-08/03-09 file
  pair — the second Sunday of March, US DST start. This means timestamps are
  naive local time in a US-based timezone, not UTC as the spec assumed.
- Count/AppTorque/Status are all stored as floats (e.g. `303552.0`) even
  though Count and Status are conceptually integers.
- Files end with a run of literal all-zero rows (Count/AppTorque/Status = 0
  for every head simultaneously) in 16/89 files — an export artifact, since
  Count is cumulative and cannot legitimately drop to 0. Stripped before
  closure/idle detection (see quality.strip_trailing_padding).
- Status codes 4 and 9 are NOT undocumented — this spec's status table
  documents all codes actually observed in the archive ({0, 2, 4, 9, 65}).
  No status code outside the documented table was found in a full scan.
- Counter resets (backward jumps) occur ~57-59 times per head across the
  89-file archive (2,088 total) — far from a rare one-off. See
  closures.py / quality.py for how resets are excluded from closure/delta
  calculations rather than fabricating a closure or a huge negative delta.

Note on cross-file continuity: closures and idle periods are correct across file
boundaries by construction (`carry_last_count` / `pending_idle_run` below) — this
was verified against a true single-file merge and produces byte-identical counts,
so the 89 files are deliberately kept separate during processing rather than
concatenated in memory (keeps memory bounded to ~1 file at a time). Sampling-gap
detection needed an explicit cross-file check too (`prev_last_ts` below), since a
gap sitting exactly at a file boundary is invisible to any single file's own
gap check — this surfaced 2 real gaps that only appear after trailing padding is
stripped (see `strip_trailing_padding`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.ingestion.closures import detect_closures
from arol_analytics.ingestion.idle import Run, detect_idle_runs_for_file, finalize_idle_periods
from arol_analytics.ingestion.loader import SchemaValidationError, discover_files, load_raw_file
from arol_analytics.ingestion.normalize import add_status_fields, compute_derived_metrics, dedupe_events
from arol_analytics.ingestion.quality import aggregate_quality, compute_file_quality, strip_trailing_padding
from arol_analytics.ingestion.report import build_ingestion_summary
from arol_analytics.ingestion.schema import GAP_FACTOR, IDLE_MIN_ROWS, IDLE_MIN_SECONDS, TIMESTAMP_COLUMN

logger = logging.getLogger(__name__)

CLOSURE_EVENTS_COLUMNS = [
    "timestamp",
    "head_id",
    "head_number",
    "counter",
    "torque_nm",
    "status_code",
    "status_label",
    "is_reject",
    "is_successful",
    "classification",
    "source_file",
    "time_since_last_closure",
    "capping_speed_pph",
]


def _jsonify(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


def ingest_dataset(data_path: str, output_dir: str | None = "data/processed") -> dict[str, Any]:
    """Ingest every raw telemetry CSV under data_path into clean, analysis-ready datasets.

    Returns a dict with keys: closure_events, idle_periods, data_quality_report,
    ingestion_summary, file_reports.
    """
    files = discover_files(data_path)
    if not files:
        raise FileNotFoundError(f"No CSV files found under {data_path}")

    file_reports: list[dict[str, Any]] = []
    schema_errors: list[dict[str, str]] = []
    padding_rows: dict[str, int] = {}
    per_file_events: list[pd.DataFrame] = []

    carry_last_count: dict[str, float] = {}
    pending_idle_run: Run | None = None
    all_idle_runs: list[Run] = []
    boundary_gaps: list[dict[str, Any]] = []
    prev_last_ts: pd.Timestamp | None = None
    prev_filename: str | None = None

    for path in files:
        logger.info("processing %s", path.name)
        try:
            loaded = load_raw_file(path)
        except SchemaValidationError as e:
            logger.error("schema validation failed for %s: %s", path.name, e)
            schema_errors.append({"file": path.name, "error": str(e)})
            continue
        except Exception as e:  # malformed file (bad CSV, encoding, etc.)
            logger.error("failed to load %s: %s", path.name, e)
            schema_errors.append({"file": path.name, "error": f"{type(e).__name__}: {e}"})
            continue

        df, head_ids = loaded.df, loaded.head_ids

        df, n_padding = strip_trailing_padding(df, head_ids)
        if n_padding:
            logger.warning("%s: stripped %d trailing zero-padding rows", path.name, n_padding)
        padding_rows[path.name] = n_padding

        if df.empty:
            logger.warning("%s: empty after stripping padding, skipping", path.name)
            continue

        file_report = compute_file_quality(df, head_ids, path.name)
        file_reports.append(file_report)

        this_first_ts = df[TIMESTAMP_COLUMN].iloc[0]
        if prev_last_ts is not None:
            gap_seconds = (this_first_ts - prev_last_ts).total_seconds()
            reference_interval = file_report["median_sampling_interval_seconds"] or 1.0
            if gap_seconds > GAP_FACTOR * reference_interval:
                boundary_gaps.append(
                    {
                        "prev_file": prev_filename,
                        "next_file": path.name,
                        "prev_end": str(prev_last_ts),
                        "next_start": str(this_first_ts),
                        "gap_seconds": gap_seconds,
                    }
                )
                logger.warning(
                    "sampling gap of %.1fs between %s and %s (file-boundary, not caught by per-file gap checks)",
                    gap_seconds, prev_filename, path.name,
                )
        prev_last_ts = df[TIMESTAMP_COLUMN].iloc[-1]
        prev_filename = path.name

        events, carry_last_count = detect_closures(df, head_ids, path.name, carry_last_count)
        if len(events):
            per_file_events.append(events)

        closed_runs, pending_idle_run = detect_idle_runs_for_file(df, head_ids, pending_idle_run)
        all_idle_runs.extend(closed_runs)

    if pending_idle_run is not None:
        all_idle_runs.append(pending_idle_run)

    if per_file_events:
        closure_events = pd.concat(per_file_events, ignore_index=True)
    else:
        closure_events = pd.DataFrame(columns=["timestamp", "head_id", "counter", "torque_nm", "status_code", "source_file"])

    closure_events = add_status_fields(closure_events)
    closure_events, dup_counts = dedupe_events(closure_events)
    closure_events = compute_derived_metrics(closure_events)
    closure_events = closure_events[CLOSURE_EVENTS_COLUMNS]

    idle_periods = finalize_idle_periods(all_idle_runs, IDLE_MIN_ROWS, IDLE_MIN_SECONDS)

    quality_report = aggregate_quality(file_reports, schema_errors, padding_rows, boundary_gaps)
    quality_report["duplicate_events_removed_per_head"] = dup_counts
    quality_report["duplicate_events_removed_total"] = sum(dup_counts.values())
    quality_report["closures_detected_per_head"] = (
        closure_events.groupby("head_id").size().to_dict() if len(closure_events) else {}
    )

    ingestion_summary = build_ingestion_summary(
        file_reports, schema_errors, closure_events, idle_periods, dup_counts, quality_report
    )

    result = {
        "closure_events": closure_events,
        "idle_periods": idle_periods,
        "data_quality_report": quality_report,
        "ingestion_summary": ingestion_summary,
        "file_reports": file_reports,
    }

    if output_dir is not None:
        save_outputs(result, Path(output_dir))

    return result


def save_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    result["closure_events"].to_parquet(output_dir / "closure_events.parquet", index=False)
    result["idle_periods"].to_parquet(output_dir / "idle_periods.parquet", index=False)

    with open(output_dir / "data_quality_report.json", "w") as f:
        json.dump(_jsonify(result["data_quality_report"]), f, indent=2)

    with open(output_dir / "ingestion_summary.md", "w") as f:
        f.write(result["ingestion_summary"])

    logger.info("wrote outputs to %s", output_dir)
