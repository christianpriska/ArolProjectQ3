# Layer 2 - The Analysis Level

After cleaning the data in Phase 1 (`src\arol_analytics\ingestion`), we analyzed them.

---

## 1. The Problem and the Goal

Phase 1 produced two cleaned tables: `closure_events.parquet` (detected actual closures) and `idle_periods.parquet` (idle periods). This information is not sufficient to answer certain queries such as "Which head fails most often?", "Is the machine slowing down?", "Which events are anomalous?", ...

**Objective**: to implement a set of deterministic functions (no machine learning, just classical statistics: mean, standard deviation, ...) that answer these questions. They are not intended to be executed by the user but to be passed to the AI agent, which will use them to answer queries. For this reason, each function:
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

Generates a **general overview**: number of closures, number of heads, time range covered, and number of successful/failed/no-load cases. Upon receiving the Phase 1 quality report, it adds any alerts (counter resets, gaps at file boundaries, etc.) described in plain language.

### Tool 2 - `success_rate_analysis`

Calculates the **success rate** (successful closures / (successful + failed) - "no load" closures do not count, as they are not actual production), which can be grouped by head, day, hour, or source file. Automatically flags groups whose success rate is significantly below average (more than 2 standard deviations).

### Tool 3 - `torque_statistics`

Statistics on applied torque (mean, median, standard deviation, quartiles, outliers) with an important filter: by default, it considers only **successful** closures, because torque is nearly 0 during inactivity and close to 2 Nm during an actual closure-mixing them would produce a meaningless average.  If the user explicitly requests statistics on "all" events, the tool **warns** that the result may be misleading, rather than providing it without comment.

### Tool 4 - `torque_trend_analysis`

Searches for trends in torque over time, per head: moving average, moving standard deviation, and a linear regression to determine whether torque is rising, falling, or stable.

*Note*: Based on the observed data, the trend showed minimal growth; to provide more relevant information, a warning regarding this was included in the report.

### Tool 5 - `anomaly_detection`

Flags anomalous closures by torques (three methods to choose from: standard deviation, IQR, or a manual threshold) and time ranges with an anomalous failure rate.  Anomalous cases are verified by cross-checking two different methods on the same data.

### Tool 6 - `head_comparison`

Creates a table with one row per head; for each, the following are calculated:
- success rate
- average torque value
- variability
- number of closings. 

It includes a statistical test (Kruskal-Wallis) to determine whether the heads actually differ from one another in the applied torque.

*Note*: On the analyzed data, this test reveals a difference of 0.15%, which is a true but not significant result given the large volume of data.

### Tool 7 - `failure_analysis`

This tool analyzes failures by highlighting: 
- which error codes are most common
- days with a spike in failures
- "bursts" of consecutive failures on the same head (3 or more in a row)
- certain heads that tend to fail at the same time
- the failure rate by hour of the day (0-23), with a chi-square test that says whether time of day and outcome are actually related

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

### Tool 11-14

Note that in layer 4 more tools are added and are present in `tools.py`, however they don't belong to the structure of this layer.

#### Tool 11 - `list_events`

Returns a **filtered raw listing of individual closure events** on a row-by-row basis (up to a configurable limit, default 200, ordered most recent first). Unlike aggregate analytics tools that return statistics, this tool answers row-level detail questions (e.g., *"show me all failed operations for head H03"*) and provides the true, uncapped count of matching records (`total_matching`), making it ideal for answering questions like *"how many operations were performed in window X?"*.

#### Tool 12 - `torque_outcome_comparison`

Compares the **torque distribution of successful vs. failed closures side by side**, applying a non-parametric **Mann-Whitney U test**. While `torque_statistics` evaluates one population at a time, this tool is specifically designed for direct head-to-head comparisons to determine whether failed closures run on significantly higher or lower torque than successful ones.

#### Tool 13 - `torque_success_correlation`

Computes a **per-head Pearson correlation** between mean applied torque and success rate. It evaluates whether heads operating at a higher average torque systematically tend to achieve higher (or lower) success rates across the machine.

#### Tool 14 - `visualize` (`render_chart`)

Renders **charts and data visualizations as PNG images** via Matplotlib. It supports 7 chart types (`torque_over_time`, `torque_histogram`, `success_rate_per_head`, `failures_over_time`, `production_over_time`, `utilization`, `kpi_dashboard`). It is invoked by the AI Agent whenever the user explicitly asks to plot, graph, or visualize data instead of receiving a text/numeric summary.

---

## 4. Final Results (Key Figures, Based on the Entire Database)

Looking at the data provided in its entirety, these are the values resulting from this phase of analysis
```
=== AROL KPI Dashboard ===
Success Rate: 99.9965%
Mean torque (successful closures): 2.014 Nm
Torque stability (standard deviation among per-head means): 0.001 Nm
Machine throughput (aggregate): 26,610 pieces/hour
  (average per head: 1,521 pieces/hour)
Utilization rate: 33.63%
Worst-performing head: H29 (99.99% success rate)
Best-performing head: H24 (100.00% success rate)
Anomalies detected (z-score method): 307,821
Total idle time: 1,418.35 hours
```

Runtime on the entire dataset (55.1 million rows): approximately 40-90 seconds for the complete dashboard-fast enough that it does not require working on a reduced sample, except for a single statistical test (Kruskal-Wallis in Tool 6), which is limited to 50,000 events per group to remain fast even if the dataset were to grow significantly.

---

## 5. Execution

To perform this step, simply run the command
```bash
PYTHONPATH=src python -m arol_analytics.analytics data/processed --output reports
```

Print the on-screen dashboard and save a complete report to `reports/analytics_report.md` (human-readable) and `reports/analytics_report.json` - including the values from all 10 tools, not just the dashboard (tool 10).
