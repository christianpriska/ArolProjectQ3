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
- Some files end with literal all-zero rows (Count/AppTorque/Status = 0 for
  every head). These rows are preserved: real reset periods in this archive
  cross daily file boundaries, so a file-local tail cannot safely be called
  export padding. Later non-zero counters are used to classify the zero run.
- Status codes 4 and 9 are NOT undocumented — this spec's status table
  documents all codes actually observed in the archive ({0, 2, 4, 9, 65}).
  No status code outside the documented table was found in a full scan.
- Counter resets (backward jumps) occur ~57-59 times per head across the
  89-file archive (2,088 total) — far from a rare one-off. See
  closures.py / quality.py for how resets are excluded from closure/delta
  calculations rather than fabricating a closure or a huge negative delta.

Note on cross-file continuity: closures and idle periods are correct across file
boundaries by construction (`CarryState` / `pending_idle_run` below) — this
was verified against a true single-file merge and produces byte-identical counts,
so the 89 files are deliberately kept separate during processing rather than
concatenated in memory (keeps memory bounded to ~1 file at a time). Sampling-gap
detection needed an explicit cross-file check too (`prev_last_ts` below), since a
gap sitting exactly at a file boundary is invisible to any single file's own
gap check.

Fixes applied after a colleague's code review (REVIEW.md, 2026-08-20) -- verified
against real data before implementing, and re-verified after an initial fix
turned out to be incomplete (see below), not applied on theory alone:

- **Counter jumps >1 were silently collapsed into a single closure**,
  undercounting production by 824,421 closures (1.50% of the 55.1M total,
  measured after the fix below -- before it, corrupted Count readings
  inflated this into physically impossible deltas up to 476,513 in one row,
  see the next bullet). Fixed by recording `counter_delta` and
  `inferred_closure_count` per event instead of always assuming 1, tagged
  `data_quality` = "single" (54,723,561) / "aggregated" (406,191, counter
  jumped >1 within a normal sampling interval) / "gap" (709, the transition
  spans a detected sampling gap) -- see closures.py. We do NOT fabricate N
  separate rows with duplicated torque/status -- there's only one real
  reading for the whole jump.
- **Corrupted Count readings were mistaken for either real resets or real
  multi-closure jumps**, in three different ways discovered one after another
  by inspecting real occurrences rather than trusting the first fix:
  (1) a momentary all-zero blip (Count/Torque/Status all read exactly 0 for
  1-3 rows) recovering to the same value it had before; (2) a *single head's*
  Count specifically stuck at 0 for minutes while that head's own Torque kept
  reporting real, varying, nonzero values -- proof production never stopped;
  (3) a duration-based heuristic for case (1) missed medium-length runs
  (hundreds of rows) that turned out to be the same reporting glitch as (2),
  just with Torque coincidentally also near 0 during a low-production
  stretch. All three collapse into one underlying question -- "did the
  machine actually reset, or did the counter just stop being reported for a
  while?" -- answered by `quality.mask_corrupted_count_readings` per head,
  per contiguous Count==0 run, by comparing the value immediately after the
  run to the value immediately before it: production resuming at or above
  where it left off (post >= pre) means the run was corrupted reporting
  (Count nulled, not dropped, so closures.detect_closures's ffill-based
  comparison skips it); production resuming near 0 (post << pre) means a
  genuine reset (left untouched). Verified against every one of the 2,088
  Count==0 runs in the archive: a clean split with zero borderline cases --
  corrupted runs top out at 665 rows, genuine resets start at 1,341 (the real
  ~22.6h 2026-03-10/11 machine-down event is 78,680+). No row-length
  threshold needed once this is the criterion.
  `closures.detect_closures` also now computes reset segments directly from
  the raw per-row sequence rather than reconstructing them from
  already-extracted events, so a real reset is correctly segmented even if
  its first recovered value already matches or exceeds the pre-reset peak.
- **`capping_speed_pph` assumed exactly 1 closure per event.** Now multiplied
  by `inferred_closure_count`, so a gap-spanning multi-closure jump doesn't
  read as an implausibly slow single event.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.ingestion.closures import EVENTS_COLUMNS, CarryState, detect_closures
from arol_analytics.ingestion.idle import Run, detect_idle_runs_for_file, finalize_idle_periods
from arol_analytics.ingestion.loader import SchemaValidationError, discover_files, load_raw_file
from arol_analytics.ingestion.normalize import add_status_fields, compute_derived_metrics, dedupe_events
from arol_analytics.ingestion.quality import (
    aggregate_quality,
    compute_file_quality,
    count_trailing_all_zero_rows,
    mask_corrupted_count_readings,
)
from arol_analytics.ingestion.report import build_ingestion_summary
from arol_analytics.ingestion.schema import GAP_FACTOR, IDLE_MIN_ROWS, IDLE_MIN_SECONDS, TIMESTAMP_COLUMN

logger = logging.getLogger(__name__)

CLOSURE_EVENTS_COLUMNS = [
    "timestamp",
    "head_id",
    "head_number",
    "counter",
    "counter_delta",
    "inferred_closure_count",
    "data_quality",
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


def _find_future_first_nonzero_counts(
    files: list[Path], current_index: int, head_ids: list[str]
) -> dict[str, float]:
    """Find the first later non-zero Count for selected heads.

    This look-ahead is only used for heads whose zero run reaches the current
    file boundary. Files are read in chunks and scanning stops as soon as all
    requested heads have a later value, so normal files pay no extra I/O cost.
    """
    unresolved = set(head_ids)
    result: dict[str, float] = {}
    wanted_columns = {f"{h} Count" for h in head_ids}

    for future_path in files[current_index + 1 :]:
        try:
            chunks = pd.read_csv(
                future_path,
                usecols=lambda column: column in wanted_columns,
                chunksize=10_000,
            )
            with chunks:
                for chunk in chunks:
                    for h in list(unresolved):
                        column = f"{h} Count"
                        if column not in chunk:
                            continue
                        values = pd.to_numeric(chunk[column], errors="coerce")
                        nonzero = values[values.notna() & values.ne(0)]
                        if not nonzero.empty:
                            result[h] = float(nonzero.iloc[0])
                            unresolved.remove(h)
                    if not unresolved:
                        return result
        except Exception as exc:
            logger.warning("could not inspect %s for boundary-zero context: %s", future_path.name, exc)

    return result


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
    trailing_zero_rows: dict[str, int] = {}
    corrupted_rows_masked: dict[str, int] = {}
    per_file_events: list[pd.DataFrame] = []

    carry_state = CarryState()
    pending_idle_run: Run | None = None
    all_idle_runs: list[Run] = []
    boundary_gaps: list[dict[str, Any]] = []
    prev_last_ts: pd.Timestamp | None = None
    prev_filename: str | None = None

    for file_index, path in enumerate(files):
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

        if df.empty:
            logger.warning("%s: empty after timestamp validation, skipping", path.name)
            continue

        n_trailing_zero = count_trailing_all_zero_rows(df, head_ids)
        trailing_zero_rows[path.name] = n_trailing_zero
        if n_trailing_zero:
            logger.warning(
                "%s: preserving %d trailing all-zero rows until cross-file classification",
                path.name,
                n_trailing_zero,
            )

        trailing_zero_heads = [h for h in head_ids if df[f"{h} Count"].iloc[-1] == 0]
        future_first_nonzero = _find_future_first_nonzero_counts(files, file_index, trailing_zero_heads)

        df, n_masked = mask_corrupted_count_readings(
            df,
            head_ids,
            carry_state.last_count,
            future_first_nonzero,
        )
        if n_masked:
            logger.warning("%s: masked %d corrupted Count readings as missing", path.name, n_masked)
        corrupted_rows_masked[path.name] = n_masked

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

        reset_count_before = len(carry_state.reset_events)
        events, carry_state = detect_closures(df, head_ids, path.name, carry_state)
        resets_in_file = carry_state.reset_events[reset_count_before:]
        reset_counts_for_file = {h: 0 for h in head_ids}
        for reset in resets_in_file:
            head_id = str(reset["head_id"])
            reset_counts_for_file[head_id] = reset_counts_for_file.get(head_id, 0) + 1
        # The extractor has cross-file context; its result replaces the
        # provisional file-local diff computed by compute_file_quality().
        file_report["counter_resets_per_head"] = reset_counts_for_file
        if len(events):
            per_file_events.append(events)

        closed_runs, pending_idle_run = detect_idle_runs_for_file(df, head_ids, pending_idle_run)
        all_idle_runs.extend(closed_runs)

    if pending_idle_run is not None:
        all_idle_runs.append(pending_idle_run)

    if per_file_events:
        closure_events = pd.concat(per_file_events, ignore_index=True)
    else:
        closure_events = pd.DataFrame(columns=EVENTS_COLUMNS)

    closure_events = add_status_fields(closure_events)
    closure_events, dup_counts = dedupe_events(closure_events)
    closure_events = compute_derived_metrics(closure_events)
    closure_events = closure_events[CLOSURE_EVENTS_COLUMNS]

    idle_periods = finalize_idle_periods(all_idle_runs, IDLE_MIN_ROWS, IDLE_MIN_SECONDS)

    quality_report = aggregate_quality(file_reports, schema_errors, trailing_zero_rows, boundary_gaps)
    reset_counts: dict[str, int] = {}
    for reset in carry_state.reset_events:
        head_id = str(reset["head_id"])
        reset_counts[head_id] = reset_counts.get(head_id, 0) + 1
    quality_report["counter_reset_events"] = carry_state.reset_events
    quality_report["counter_resets_per_head"] = reset_counts
    quality_report["counter_resets_total"] = len(carry_state.reset_events)
    quality_report["corrupted_rows_masked_per_file"] = corrupted_rows_masked
    quality_report["corrupted_rows_masked_total"] = sum(corrupted_rows_masked.values())
    quality_report["duplicate_events_removed_per_head"] = dup_counts
    quality_report["duplicate_events_removed_total"] = sum(dup_counts.values())
    if len(closure_events):
        quality_report["closure_rows_per_head"] = closure_events.groupby("head_id").size().to_dict()
        quality_report["inferred_closures_per_head"] = (
            closure_events.groupby("head_id")["inferred_closure_count"].sum().astype(int).to_dict()
        )
        quality_report["data_quality_breakdown"] = closure_events["data_quality"].value_counts().to_dict()
    else:
        quality_report["closure_rows_per_head"] = {}
        quality_report["inferred_closures_per_head"] = {}
        quality_report["data_quality_breakdown"] = {}

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
