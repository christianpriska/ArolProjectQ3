# Layer 1 - Data preparation: Data Exploration, Cleaning, and Normalization

This document explains, step by step, everything that was done to transform the raw data from the AROL capping machine into a clean dataset ready for analysis.

---

## 1. The Problem and the Objective

**Raw Data**: The machines generate a large volume of data. The sample data consists of 89 CSV files (one per day, from early February to late April 2026), totaling approximately 4.6 GB, located in `src/data/`. The machine has 36 capping heads.
Every second, for each head, the machine records 3 values:
- **Count**: a cumulative count of the number of caps installed
- **AppTorque**: the torque applied during capping
- **Status**: a numeric code indicating whether the capping operation was successful or not

This data does not only identify successful closures; there are numerous instances in which the machine does not complete a capping operation but still records the values.

**Objective**: to generate a "cleaned" table with **one row for each actual closure** (no longer one per second), and a report describing the quality of the raw data.

---

## 2. Virtual environment

To prevent system issues, the application runs in a virtual environment dedicated to the project:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas pyarrow numpy
```

---

## 3. Data Observation Before Code Development

Upon examining the data and comparing it with the specifications provided by the company, the following became apparent:

| Specification | Actual Data |
|---|---|
| Up to 48 heads (H01–H48) | Exactly **36 heads** in each file |
| Columns "in groups of three": `H01 Count, H01 AppTorque, H01 Status, H02 Count, ...` | Columns **grouped by type**: first all 36 `Count` columns, then all 36 `AppTorque` columns, then all 36 `Status` columns |
| ISO 8601 timestamp in UTC (with a trailing `Z`) | Timestamps **without `Z`** and **not in fixed UTC**-see below |
| Documented status codes: {0,2,3,4,5,8,9,16,17,32,33,64,65} | In reality, **only** {0, 2, 4, 9, 65} appear |

**Additional notes**: 
- Each "daily" file actually begins at 4:00 p.m. (or 5:00 p.m.) on the previous day and ends at 3:59:59 p.m./4:59:59 p.m. on the designated day. The one-hour offset changes exactly between the files for 2026-03-08 and 2026-03-09-the second Sunday in March, which is **the start of U.S. Daylight Saving Time**. This means that the timestamps are in U.S. local time, not UTC as one might assume from the format.
- Some files have "zeroed" lines (Count/AppTorque/Status = 0)-an export artifact, not actual readings (the counter cannot reset itself). Some are a **continuous trailing tail** (to be removed); others are isolated blocks in the middle of the file.
- The counters "reset"-this is not uncommon. Sometimes it's a true machine shutdown, sometimes it's a sensor "flicker" lasting a few seconds, and sometimes the counter stops reporting correctly for minutes while the machine continues to actually produce output.

---

## 4. Step-by-Step Ingestion pipeline

Here's what happens when you run the data ingestion pipeline (`ingest_dataset`), in order:

1. **Find all CSV files** in the specified folder (`src/data/`), sorted by
   name (which corresponds to chronological order).

2. **For each file, in chronological order**:
   - **Read it and validate its schema** - check for the column
     `timestamp` and the triplets `H{nn} Count/AppTorque/Status`. If a file is malformed, it is discarded with an error message, and the pipeline **continues** with the other files (it does not stop).
   - **Remove the tail of zeroed rows**, if present (only if it is truly a trailing tail, as explained in point 3).
   - **Calculate the quality metrics** for that file (rows, missing values, time gaps, suspicious pair values, status code distribution, counter resets).
   - **Detect closures**: for each header, scan the `Count` column row by row. When the value **increases** compared to the previous row, that row is a closure. If it **decreases**, it is not a close but a reset - it is ignored and not counted as a false close.
   - **Detect periods of inactivity**: stretches where all 36 heads have Status=2 (no load) for at least 30 consecutive rows or 30 consecutive seconds.

3. **Combine the results from all files** into a single closure table.

4. **Enrich the table**: add a human-readable status label (e.g., "Closure OK"), indicating whether it was a success or a failure, and two calculated values: how much time has elapsed since the last closure of the same head, and the closure rate (pieces/hour).

5. **Remove true duplicates** (see Section 5, "Duplicate Closures Due to Flicker").

6. **Save everything to disk** in `data/processed/`: the two cleaned tables (`.parquet`), the quality report (`.json`), and the human-readable summary (`.md`).

---

## 5. File Map: what each file does

```
src/arol_analytics/ingestion/
├── __init__.py      →  exposes `ingest_dataset()` as the package's entry point
├── __main__.py      →  allows you to run everything from the command line
├── schema.py        →  the "rules of the game": status code table, thresholds, column names
├── loader.py        →  finds the files and checks that they are in the correct format
├── quality.py       →  calculates quality statistics + removes the final zero-value rows
├── closures.py      →  the heart: detects when a closure occurs
├── idle.py          →  detects periods when the machine is idle
├── normalize.py     →  labels closures, removes duplicates, calculates derived metrics
├── report.py        →  writes the human-readable summary (Markdown) for the user
└── pipeline.py      →  the "conductor": brings all the above pieces together
```

Now, the details of each one-including the "extra" parts that solve specific problems found in real data.

### `schema.py` - the rules of the game

It contains all the constants used throughout the code: the table of 13 status codes (which ones are "reject," what human-readable name to give each one), the inactivity thresholds (30 lines / 30 seconds, taken verbatim from the specification), the threshold for time gaps (2x the median interval, also from the specification), and the tolerance for
considering two files "contiguous" in time (5 seconds-we chose this one-see Section 6).

All other files read the "rules" from a single file --> optimized in case thresholds need to be modified.

### `loader.py` - find and validate files

Locates the CSV files in the folder and validates their structure (consistency in the expected columns: timestamp + Count/AppTorque/Status triplets) before running the pipeline.

Proper functionality was tested during the development phase.

### `quality.py` - statistics + cleaning up corrupted readings

Main functions:
- `count_trailing_all_zero_rows()`: reports rows that are entirely zero but does not remove them. The classification also uses the first valid value from subsequent files, because a true reset can span the daily boundary.
- `mask_corrupted_count_readings()`: For each head, it identifies blocks where `Count` reads 0 in the middle of the file and determines whether it is a **true reset** (to be retained) or a **corrupted reading** (to be discarded, replacing it with a "missing" value that `closures.py` can ignore).
- `compute_file_quality()`: For each file, it calculates everything needed for the report-time interval covered, gaps in the sample, percentage of missing values, negative or suspicious pairs, distribution of status codes, and how many times the counter rolled back.

### `closures.py`-the heart of the pipeline: recognizing closures

The basic rule is simple: **a closure is a line where `Count` is higher than
the previous line** (the valid one, ignoring corrupted readings discarded by
`quality.py`) **for that header**. If the value drops, it's not a closure; it's a
reset-and it's automatically excluded, without the need for a specific check.

Since `Count` can increase by more than 1 in a single step, each
closure also records: `counter_delta` (by how much it increased), `inferred_closure_count` (how many closures the counter implies-currently always equal to `counter_delta`), and `data_quality` ("single" = normal, "aggregated" = jump >1 within a normal interval, "gap" = the jump crosses a detected sampling gap) .

It also calculates the reset "segment" (how many times that header's counter has rolled over, by examining the **raw** data row by row).

**Handling the First Event in the Document**: Since the first line of each file has no "previous line" within the same file to compare it to. If nothing were done, a true close that occurs exactly on the first line of a day would be lost once for every file change. To resolve this, the pipeline carries forward from one file to the next the last counter value of each header, the last timestamp, and the current "segment" of each header (`CarryState`), so that even the first line of each new file is compared correctly. **Verified in practice**: By processing two consecutive days using both this method and by actually merging all the raw data into a single table and performing the comparison once across the entire dataset, the number of closures found was **identical** (612,010 in both cases)-so keeping the files separate does not result in any loss of information and uses much less memory.

### `idle.py` - Finding periods of inactivity

A row counts as "inactive" only if **all 36 heads together** have
Status No Load (2). Periods of inactivity are grouped and retained only if they last at least 30 rows or 30 seconds. A sampling gap always splits a run: without observations, the missing interval cannot be assumed to be idle.

Idle periods may span adjacent files. A run at the end of one file is merged with a run at the start of the next only when their timestamps are continuous within the configured file-boundary tolerance; otherwise the runs remain separate.

### `normalize.py` - Labels, Duplicates, and Derived Metrics

Three things, in order:

1. **Human-readable labels**: Each closure is assigned a human-readable status name
   (`status_label`), whether it's a success (`is_successful`), whether it's a failure
   (`is_reject`), and a broader category (`classification`).

2. **Remove duplicate closures without making mistakes.** The specification requires removing duplicates (same header, same counter value). The problem: after a reset, the counter starts from 0 and *legitimately* revisits values already used before the reset-these are not duplicate closures, but genuine closures that happen to coincide with a number already seen. If all repeated (header, value) pairs were blindly removed from the entire archive, genuine closures would be lost. The solution: the check for duplicates is limited to a single "segment"-that is, the interval between one reset and the next-for that header (the segment is identified by `closures.py`). Only if the same value appears twice **within the same segment** is it considered a true duplicate and removed.

3. **Derived metrics**: time since the last closure of the same head and closure rate (bottles/hour), calculated after merging all files, and therefore automatically adjusted even when spanning two days. The speed measurement takes into account `inferred_closure_count`; that is, if a row represents $n$ aggregated closures, the calculated speed is "$n$ closures in that interval," not "1 slower closure."

### `report.py` - the human-readable summary

Starting with the cleaned and merged data, it transforms it into the `ingestion_summary.md` file, which contains information regarding:
- how many files were processed
- how many closures per head
- success/failure/downtime percentages
- data quality alerts
- summary of downtime periods

### `pipeline.py` - the orchestrator

It combines the execution of the previous files in the correct order, collecting information necessary for continuous execution:
- `carry_state` for counters
- `pending_idle_run` for idle time
- `prev_last_ts` for gaps between files

Finally, it combines everything, calculates the aggregated report, and saves the output files.

### `__main__.py` - the entry point from the terminal

This allows you to run everything with a single command:

```bash
PYTHONPATH=src python -m arol_analytics.ingestion src/data --output-dir data/processed
```
---

## 6. Output Files

The `data/processed/` folder contains the files resulting from the analysis of the provided sample data:

| File | Content |
|---|---|
| `closure_events.parquet` | cleaned table of closures (includes `counter_delta`, `inferred_closure_count`, `data_quality`) |
| `idle_periods.parquet` | 3,493 rows: start, end, and duration of each idle period |
| `data_quality_report.json` | machine-readable version of all metrics |
| `ingestion_summary.md` | human-readable version of the same metrics |
