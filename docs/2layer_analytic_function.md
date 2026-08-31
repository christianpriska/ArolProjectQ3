# Layer 2 - The Analysis Level

After cleaning the data in Phase 1 (`src\arol_analytics\ingestion`), we'll analyze it.

---

## 1. The Problem and the Goal

Phase 1 produced two cleaned tables: `closure_events.parquet` (detected actual closures) and `idle_periods.parquet` (idle periods). This information is not sufficient to answer certain queries such as "Which head fails most often?", "Is the machine slowing down?", "Which events are anomalous?", ...

**Objective**: to implement a set of deterministic functions (no machine learning, just classical statistics: mean, standard deviation, ...)
that answer these questions. They are not intended to be executed by the user but to be passed to the AI agent, which will use them to answer queries.
For this reason, each function:
- accepts the table (or a pre-filtered subset) as a parameter, never a file path-this makes it testable and composable
- always returns a dictionary with a `summary` key (readable text) plus the structured data, not just scattered numbers

---

## 2. File Map: what each file does

```
src/arol_analytics/analytics/
├── __init__.py    →  defines the 10 main functions
├── __main__.py    →  allows you to run the entire analysis from the command line
├── _common.py     →  shared components: filters, time measurement, JSON conversion
├── io.py          →  loads the two .parquet files from Phase 1
├── summary.py     →  tools 1-2 (dataset summary, success rate)
├── torque.py      →  tools 3-4 (torque statistics and trends)
├── anomaly.py     →  tool 5 (anomaly detection)
├── heads.py       →  metrics 6-7 (head comparison, failure analysis)
├── production.py  →  metrics 8-9 (production speed, downtime)
└── dashboard.py   →  metric 10 (summary dashboard)
```

Specifically, there are two files that provide general functions used by the other classes.

### `_common.py` - Shared Functions

It provides three functions used by many other classes:
- `filter_events()`: applies the same two optional filters that almost all tools accept-by header (`head_filter`) and by time range (`time_range`) 
- `log_duration()`: measures how long a block of code takes to execute, and writes a warning to the log if it exceeds 5 seconds 
- `group_mean_std_flags()`: performs the calculation "Is this value more than $n$ standard deviations from the group mean?", used in almost all tools to flag outliers or anomalous periods.

### `io.py` - data loading

It provides two functions, `load_closure_events()` and `load_idle_periods()`, which read the Phase 1 `.parquet` files.

---

## 3. The Tools

The remaining files not covered in detail in Section 3 implement the various tools for calculating and evaluating the metrics to be applied to the data.

### Tool 1 - `dataset_summary`

Generates a **general overview**: number of closures, number of heads, time range covered, and number of successful/failed/no-load cases.
Upon receiving the Phase 1 quality report, it adds any alerts (counter resets, gaps at file boundaries, etc.) described in plain language.

### Tool 2 - `success_rate_analysis`

Calculates the **success rate** (successful closures / (successful + failed) - "no load" closures do not count, as they are not actual production), which can be grouped by head, day, hour, or source file. Automatically flags groups whose success rate is significantly below average (more than 2 standard deviations).

### Tool 3 - `torque_statistics`

Statistics on applied torque (mean, median, standard deviation, quartiles, outliers) with an important filter: by default, it considers only **successful** closures, because torque is nearly 0 during inactivity and close to 2 Nm during an actual closure-mixing them would produce a meaningless average. 
If the user explicitly requests statistics on "all" events, the tool **warns** that the result may be misleading, rather than providing it without comment.

### Tool 4 - `torque_trend_analysis`

Searches for trends in torque over time, per head: moving average, moving standard deviation, and a linear regression to determine whether torque is rising, falling, or stable.

*Note*: Based on the observed data, the trend showed minimal growth; to provide more relevant information, a warning regarding this was included in the report.

### Tool 5 - `anomaly_detection`

Flags anomalous closures by pair (three methods to choose from: standard deviation, IQR, or a manual threshold) and hours with an anomalous failure rate. 
Anomalous cases are verified by cross-checking two different methods on the same data.

### Tool 6 - `head_comparison`

Creates a table with one row per head; for each, the following are calculated:
- success rate
- average pair value
- variability
- number of closings. 

It includes a statistical test (Kruskal-Wallis) to determine whether the heads actually differ from one another in the applied pair.

*Note*: On the analyzed data, this test reveals a difference of 0.15%, which is a true but not significant result given the large volume of data.

### Tool 7 - `failure_analysis`

This tool analyzes failures by highlighting: 
- which error codes are most common
- days with a spike in failures
- "bursts" of consecutive failures on the same head (3 or more in a row)
- certain heads that tend to fail at the same time

### Tool 8 - `capping_speed_analysis`

It breaks down the machine performance metrics generated in Phase 1: `machine_wide_throughput_pph` (pieces per hour for the entire machine) and `per_head_average_speed_pph` (pieces per hour for each individual head). Both metrics consider only the hours in which at least one successful operation occurred.

*Note*: Upon analyzing the data, these values are:
- ~26,610 pieces/hour for the entire machine (consistent with typical specifications for these machines, 50,000–72,000 pieces/hour)
- ~1,521 pieces/hour per individual head

### Tool 9 - `idle_analysis`

Analyzes `idle_periods.parquet`, highlighting:
- utilization rate (productive time / total time)
- average duration of idle periods
- most frequent times of inactivity (useful for understanding work shifts)
- the 10 longest idle periods

### Tool 10 - `generate_kpi_dashboard`

Runs all the other tools and compiles a dashboard with key metrics. This is intended to be the first output an AI agent displays when asked, "How is the machine doing?"

---

## 4. Final Results (Key Figures, Based on the Entire Database)

Looking at the data provided in its entirety, these are the values resulting from this phase of analysis
```
=== AROL KPI Dashboard ===
Success Rate: 100.00%
Average torque (successful fastenings): 2.014 Nm
Torque stability (standard deviation among averages per head): 0.001 Nm
Machine throughput (aggregate): 26,610 pieces/hour
  (average per head: 1,521 pieces/hour)
Utilization Rate: 33.49%
Worst Head: H29 (99.99% success rate)
Best Head: H24 (100.00% success rate)
Anomalies Detected (statistical method): 307,821
Total Downtime: 1,421 hours
```

Runtime on the entire dataset (55.1 million rows): approximately 40-90
seconds for the complete dashboard-fast enough that it does not require working
on a reduced sample, except for a single statistical test (Kruskal-Wallis in
Tool 6), which is limited to 50,000 events per group to remain fast even if
the dataset were to grow significantly.

---

## 5. Execution

To perform this step, simply run the command
```bash
PYTHONPATH=src python -m arol_analytics.analytics data/processed --output reports
```

Print the on-screen dashboard and save a complete report to
`reports/analytics_report.md` (human-readable) and `reports/analytics_report.json` - including the values from all 10 tools, not just the dashboard (tool 10).