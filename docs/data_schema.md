# Data Schema

## Raw data format

**File structure and naming.** `src/data/telemetry_MCC777eda3db57348ef8a3113a642ae74db_YYYY-MM-DD.csv`
— 89 daily CSV files, one per day, `2026-02-01.csv` through `2026-04-30.csv` by
nominal filename (the actual timestamp range inside the files runs a little wider,
see below). Discovered and sorted by `ingestion/loader.discover_files()`
(`sorted(data_path.rglob("*.csv"))`) — filename sort order equals chronological
order.

**Column schema.** One `timestamp` column, plus three columns per head:
`H{nn} Count`, `H{nn} AppTorque`, `H{nn} Status` (`nn` zero-padded, `H01`–`H36`).
Columns are **grouped by field across all heads first** (all 36 `Count` columns,
then all 36 `AppTorque` columns, then all 36 `Status` columns), not interleaved
per head — see [architecture.md](architecture.md) for how the loader handles this.
`Count`, `AppTorque`, and `Status` are all stored as floats in the raw CSV (e.g.
`303552.0`) even though `Count` and `Status` are conceptually integers.

Example raw row (abbreviated to 2 of 36 heads):

| timestamp | H01 Count | H02 Count | ... | H01 AppTorque | H02 AppTorque | ... | H01 Status | H02 Status | ... |
|---|---|---|---|---|---|---|---|---|---|
| 2026-02-07T06:38:30.000 | 205088.0 | 198442.0 | ... | 0.0 | 2.013 | ... | 2.0 | 0.0 | ... |

**Sampling rate.** Approximately 1 row/second per the module docstring in
`ingestion/pipeline.py` and the `GAP_FACTOR`-relative gap detection in
`ingestion/quality.compute_file_quality`, which computes each file's own median
inter-row interval rather than assuming a fixed rate.

**Timestamp format.** ISO-8601-like but with **no `Z`/UTC suffix**:
`2026-04-07T17:00:00.000`. Parsed with `pd.to_datetime(..., format="ISO8601",
errors="coerce")` in `ingestion/loader.load_raw_file`; unparsable rows are dropped
and counted in a warning.

**DST shift, confirmed 2026-03-08 → 2026-03-09.** The timestamp column is **naive
US local time, not UTC**, despite the ISO-like formatting. Each daily file's actual
first row shifts from `16:00:00` (previous day) to `17:00:00` (previous day)
exactly at the `2026-03-08`/`2026-03-09` file pair — the second Sunday of March,
the 2026 US DST start date. This is why the archive's *actual* time range
(`2026-01-31 16:00:00` → `2026-04-30 16:59:59`, from
`data/processed/ingestion_summary.md`) starts and ends mid-afternoon rather than at
midnight: each "daily" file spans roughly 16:00/17:00 the previous day through
15:59:59/16:59:59 on its nominal date.

---

## Closure status codes — complete reference

| Code | Label | Reject? | Description | In this archive? |
|------|-------|---------|--------------|-------------------|
| 0 | Closure OK | No | Successful closure | **Yes** — 31,670,096 closure events |
| 2 | No Load | No | Machine running empty | **Yes** — 23,459,257 closure events |
| 3 | SlowTorque | Yes | Failed to reach first torque threshold | No |
| 4 | No Closure | No | No closure detected | **Yes** — 12 closure events |
| 5 | ClosureTorque | Yes | Failed to reach final torque | No |
| 8 | No InTorque | No | Head raises before TimeInTorque elapsed | No |
| 9 | EarlyRaise | Yes | Head raised before TimeInTorque elapsed | **Yes** — 24 closure events |
| 16 | No CapTurns | No | Insufficient cap rotation | No |
| 17 | InsufficientCapTurns | Yes | Closed with fewer degrees than CapTurns | No |
| 32 | Following Error | No | Position tracking error | No |
| 33 | TrackingError | Yes | Real vs. controlled position mismatch | No |
| 64 | Bad Closure | No | General bad closure | No |
| 65 | RotatingAtRaise | Yes | ClosureTorque reached but cap still rotating at head raise | **Yes** — 1,072 closure events |

Source of truth: `STATUS_TABLE` in `ingestion/schema.py`. "In this archive?" and the
counts are measured directly against `closure_events.parquet`'s `status_code`
column (`df["status_code"].value_counts()`), not assumed — no status code outside
this table was found anywhere in the 89-file archive
(`data_quality_report.json`'s `unexpected_status_codes` is `{}`). Codes 3, 5, 8,
16, 17, 32, 33 are part of the documented machine spec but never actually occur in
this dataset.

`ingestion/normalize.add_status_fields` derives three higher-level fields from the
raw status code: `is_reject` (`status_code` in the reject set above), `is_successful`
(`status_code == 0`), and `classification` — `"successful"` (0), `"failed"` (any
reject code), `"no_load"` (2), or `"other"` (everything else, e.g. code 4, which is
not a reject code but also isn't success/no-load).

---

## Processed data format

### `closure_events.parquet` (55,130,461 rows)

One row per detected closure event (a `Count` increment for one head). Column list
and types below are read directly from the Parquet file's schema
(`pyarrow.parquet.ParquetFile(...).schema_arrow`), with an example value from a
real row (`H01`, 2026-02-07):

| Column | Type | Description | Example |
|---|---|---|---|
| `timestamp` | `timestamp[us]` | When the closure was observed. | `2026-02-07 06:38:30` |
| `head_id` | `string` (loaded as pandas `category`) | Head identifier. | `"H01"` |
| `head_number` | `int64` | Integer form of the head id. | `1` |
| `counter` | `int64` | The head's cumulative `Count` value at this event. | `205088` |
| `counter_delta` | `int64` | How much `Count` rose since the last valid reading. | `1` |
| `inferred_closure_count` | `int64` | Closures implied by this event for production totals (currently always `== counter_delta`; named `accepted_closure_count` in older Parquet outputs — `analytics/io.py` renames it transparently on load for backward compatibility). | `1` |
| `data_quality` | `string` (category) | `"single"` (normal 1-step jump), `"aggregated"` (jump >1, normal interval), or `"gap"` (jump spans a detected sampling gap). | `"single"` |
| `torque_nm` | `double` | Closing torque reading, in Newton-meters. | `0.0` |
| `status_code` | `int64` | Raw machine status code (see table above). | `2` |
| `status_label` | `string` (category) | Human-readable label for `status_code`. | `"No Load"` |
| `is_reject` | `bool` | `True` if `status_code` is one of the reject codes. | `False` |
| `is_successful` | `bool` | `True` if `status_code == 0`. | `False` |
| `classification` | `string` (category) | `"successful"` / `"failed"` / `"no_load"` / `"other"`. | `"no_load"` |
| `source_file` | `string` (category) | Which daily CSV this event came from. | `"telemetry_MCC..._2026-02-07.csv"` |
| `time_since_last_closure` | `double` | **Derived.** Seconds since this head's previous closure event (per-head diff of `timestamp`, computed in `ingestion/normalize.compute_derived_metrics`). `NaN` for each head's first event. | `2.0` |
| `capping_speed_pph` | `double` | **Derived.** `3600 * inferred_closure_count / time_since_last_closure` — pieces/hour implied by this single event; accounts for multi-closure jumps so a gap-spanning event doesn't read as an implausibly slow single closure. `NaN`/`0` where `time_since_last_closure` isn't positive. | `1800.0` |

`analytics/io.load_closure_events` downcasts `head_id`, `status_label`,
`classification`, and `source_file` to pandas `category` dtype on load (not in the
Parquet file itself) to reduce memory on a 55M-row frame — the on-disk types above
are plain strings.

### `idle_periods.parquet` (3,493 rows)

One row per detected idle period (all 36 heads simultaneously `status=2` for at
least `IDLE_MIN_ROWS`/`IDLE_MIN_SECONDS`, see [architecture.md](architecture.md)).

| Column | Type | Description |
|---|---|---|
| `start_time` | `timestamp[us]` | Start of the idle period. |
| `end_time` | `timestamp[us]` | End of the idle period. |
| `duration_seconds` | `double` | `(end_time - start_time)` in seconds. |

### `data_quality_report.json`

Written by `ingestion/pipeline.save_outputs`, built by
`ingestion/quality.aggregate_quality` plus post-processing in `pipeline.ingest_dataset`.
Top-level keys actually present on the current archive (values from the current
run): `files_processed` (89), `schema_errors` (`[]`), `total_rows` (7,623,968 raw
rows across all files/heads), `time_range`, `missing_cells_total` (96,518),
`missing_pct_overall`, `status_code_distribution` (raw per-row, per-head status
counts across the whole archive — not the same as the closure-level distribution
above, since most raw rows aren't closure events), `unexpected_status_codes`
(`{}`), `counter_resets_per_head` / `counter_resets_total` (108),
`negative_torque_total` (0), `torque_outliers_total` (1,319,070 — `>3σ` from each
file's own per-head mean, a coarser per-file heuristic than
`analytics.anomaly_detection`'s dataset-wide z-score/IQR methods),
`trailing_all_zero_rows_preserved_total` (2,688), `corrupted_rows_masked_total`
(96,518), `duplicate_events_removed_total` (0), `data_quality_breakdown` (`single`/
`aggregated`/`gap` counts), `files_with_gaps` (21 files), `boundary_gaps` (`[]` on
the current archive), `closure_rows_per_head`, `inferred_closures_per_head`.

---

## Key statistics (current archive, `data/processed/`)

- **55,130,461** observed closure events across **36** heads, from **89** raw
  files, spanning **2026-01-31 16:00:00 → 2026-04-30 16:59:59**.
- **55,954,882** inferred closures (sum of `inferred_closure_count` — higher than
  the row count because 406,191 "aggregated" and 709 "gap" rows each represent more
  than one real closure).
- **1,096** failures (1,072 × status 65 RotatingAtRaise, 24 × status 9 EarlyRaise),
  **12** "other" (status 4, No Closure).
- Observed-status success rate **99.9965%**: 31,670,096 successful observations
  divided by 31,671,192 successful + failed observations; no-load is excluded.
- **307,821** anomalies flagged by `anomaly_detection`'s default z-score method
  (sensitivity 3.0, evaluated on real/non-idle closures against each head's own
  successful-closure mean/std).
- **3,493** idle periods, **1,418.35** total idle hours, **33.63%** utilization rate
  (`idle_analysis`).
- Mean torque **2.014 Nm** on successful closures (std of per-head means: **0.001
  Nm** — heads are extremely torque-consistent with each other).
- Production speed: **~26,610 pph** machine-wide throughput (all heads summed,
  then averaged across hours containing at least one recorded production closure;
  zero-production hours are not included) vs. **~1,521 pph/head** per-head average
  (mean of individual head cycle speeds) — these are two different numbers, ~17x apart; see
  [analytics_methods.md](analytics_methods.md) for why both are reported.

All numbers above were read directly from `data/processed/data_quality_report.json`,
`data/processed/ingestion_summary.md`, and a fresh `generate_kpi_dashboard()` run
(`reports/analytics_report.md`), not carried over from an earlier session or the
original project spec.
