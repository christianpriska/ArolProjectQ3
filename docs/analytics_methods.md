# Analytics Methods

`src/arol_analytics/analytics/` implements 14 deterministic, stateless tools over
`closure_events.parquet` / `idle_periods.parquet`. Every tool returns a
JSON-serializable dict that always includes a human-readable `summary` string.
Shared helpers live in `analytics/_common.py`: `filter_events` (head/time-range
filtering), `real_closures`/`successful_closures`/`failed_closures` (status-based
subsetting), `group_mean_std_flags` (>2σ flagging), `to_jsonable` (numpy/pandas →
native Python for JSON output), `log_duration` (logs slow (>5s) operations).

---

## 1. `dataset_summary` (`summary.py`)

**What it computes.** Total events, inferred closures, head list, time range,
status breakdown, overall success rate, per-file event counts, and (if a
`quality_report` dict is supplied) data-quality flags carried over from Layer 1.

**Method.** Plain aggregation — `groupby`/`value_counts`, no statistical test.

**Parameters.** `events` (required), `quality_report` (optional dict from
`data_quality_report.json`).

**Interpreting results.** `overall_success_rate_pct` excludes no-load events from
the denominator (`successful / (successful + failed)`). `quality_flags` surfaces
unexpected status codes, rejected files, boundary sampling gaps, counter resets,
and duplicates-removed count — all explicit, not inferred.

**Limitations.** No filtering support — always covers the full dataset passed in;
filter the DataFrame before calling if a subset is needed.

---

## 2. `success_rate_analysis` (`summary.py`)

**What it computes.** Success rate = `successful / (successful + failed)`,
no-load always excluded (not a real capping attempt). `group_by`: `"overall"`,
`"per_head"`, `"daily"`, `"hourly"`, or `"per_file"`.

**Method.** Grouped aggregation, then a 2σ outlier flag: groups with
`success_rate_pct < mean − 2·std` across all groups' rates are listed in
`flagged_groups`.

**Parameters.** `group_by` (default `"overall"`), `head_filter`, `time_range`.

**Interpreting results.** `table` has one row per group with `total_closures`,
`inferred_closures`, `successful`, `failed`, `other_count`,
`closures_without_individual_status` (inferred − observed, from
aggregated/gap-tagged rows), `success_rate_pct`; `per_head` rows are additionally
ranked worst-to-best (`rank_worst_to_best`).

**Limitations.** The 2σ flag needs ≥2 groups with non-zero variance; with 1 group
or identical rates, nothing is flagged (not an error).

---

## 3. `torque_statistics` (`torque.py`)

**What it computes.** Distribution stats (count, mean, median, std, min, max, Q1,
Q3, IQR, IQR-outlier count, coefficient of variation) with filtering
(`filter_status`) and grouping (`group_by`).

**Method.** `scipy`-free descriptive statistics via pandas
(`Series.quantile`/`mean`/`std`); IQR outliers flagged at the classic
`[Q1 − 1.5·IQR, Q3 + 1.5·IQR]` bounds.

**Parameters.** `filter_status` (default `"successful_only"`; also
`"failed_only"`, `"all_real"`, `"all"`), `group_by` (`"overall"`, `"per_head"`,
`"daily"`), `head_filter`, `time_range`.

**Interpreting results.** `warning` is set to a fixed `BIMODAL_WARNING` string
whenever `filter_status="all"` — torque is bimodal (~0 Nm no-load, ~2 Nm real
closures), so mixing populations skews mean/std. `flagged_high_variability`
(per_head only) lists heads whose coefficient of variation is >2σ above the
across-head average.

**Limitations.** `"all"` is intentionally the noisy option — prefer
`"successful_only"` or `"all_real"` unless the mixed distribution itself is the
point of the question.

---

## 4. `torque_trend_analysis` (`torque.py`)

**What it computes.** Per-head moving average/std, a linear-regression slope
(Nm/day) with significance, and changepoints (moving-average shifts >2× the
head's overall torque std within a short lag). Always on successful closures.

**Method.** `scipy.stats.linregress(days_since_start, torque)` per head;
`direction` is `"increasing"`/`"decreasing"` only if `p_value < 0.05` **and**
`|slope| > 1e-9`, else `"stable"`. Changepoints: `rolling_mean.diff(lag).abs() >
2 * overall_std`, grouped into contiguous runs, first point of each run reported.

**Parameters.** `head_filter`, `window_size` (int = rolling window in events, or a
pandas offset string like `"7D"`; default `1000`), `time_range`.

**Interpreting results — the large-N caveat.** On the full archive, essentially
every head shows a "statistically significant" trend (p as low as ~1e-85) with
mean **r² ≈ 0.0004** — time explains ~0.04% of torque variance. With ~900k events
per head, `p < 0.05` is trivially easy to reach even for a practically
meaningless slope. **The tool's own `summary` auto-appends a CAVEAT line whenever
mean r² across heads is < 0.01**, explicitly telling a caller (including an LLM
reading only the summary) to check `r_squared`/`slope_nm_per_day` before treating
`significant=True` as practically meaningful.

**Limitations.** `plot_series` is downsampled to one point/day/head (returning the
full per-event series for ~30M events would be impractically large for JSON/an
LLM prompt).

---

## 5. `anomaly_detection` (`anomaly.py`)

**What it computes.** Flags anomalous torque readings (`method`: `"zscore"`,
`"iqr"`, or `"threshold"`) plus hours with an elevated failure rate.

**Method.** `"zscore"`: per-head mean/std computed on *successful* closures,
flag `|torque − mean| > sensitivity·std` (default `sensitivity=3.0`). `"iqr"`:
per-head Q1/Q3 on successful closures, flag outside `[Q1−1.5·IQR, Q3+1.5·IQR]`.
`"threshold"`: flag outside a caller-supplied `[low, high]` range. All three
evaluate against *real* (non-idle) closures — a no-load event's ~0 Nm torque
isn't a meaningful anomaly by construction. Failure-rate spikes: hourly failure
rate vs. its own mean/std across the dataset, flagged when `> mean + 2·std`.

**Parameters.** `method` (default `"zscore"`), `threshold_range` (required only
for `"threshold"`), `sensitivity` (default 3.0), `head_filter`, `time_range`,
`max_events_returned` (default 500, caps the `anomalies` list — sorted by
deviation magnitude, worst first; `total_anomalies` is always the true, uncapped
count).

**Interpreting results.** On the full archive, z-score flags **307,821**
anomalies — this is dominated by the same bimodal-torque effect as above (many
"anomalies" are legitimate no-load-adjacent readings near the population
boundary), not evidence of 307,821 mechanical faults; cross-check against
`failure_analysis` (1,096 true failures) before treating anomaly count as a
failure proxy.

**Limitations.** `"threshold"` requires domain knowledge of a sane torque range;
`"zscore"`/`"iqr"` are self-calibrating per head but assume the successful-closure
population is roughly the right baseline to compare against.

---

## 6. `head_comparison` (`heads.py`)

**What it computes.** Side-by-side per-head table (success rate, torque mean/std,
total closures, ranks), a Kruskal-Wallis test on successful-closure torque across
heads, outlier flags, the single busiest/quietest head by volume, a daily
per-head success-rate correlation matrix, and a failure breakdown by status code.

**Method.** `scipy.stats.kruskal` (non-parametric one-way ANOVA — does torque
differ significantly by head, without assuming normality), subsampled to
`KRUSKAL_MAX_SAMPLE_PER_HEAD = 50,000` events/head (`np.random.default_rng(seed=0)`)
since the test is O(n log n) over tens of millions of concatenated rows and 50k/head
is already far more than needed to detect a real effect. Outlier flagging: same
2σ-from-group-mean pattern as elsewhere, applied independently to success rate,
mean torque, and torque std.

**Parameters.** `heads` (optional subset), `time_range`.

**Interpreting results.** On the full archive: Kruskal-Wallis statistic
173,362.45, **p ≈ 0** (significant) — but per-head mean torque spans only
2.012–2.015 Nm, a ~0.15% range. This is the same large-N pattern as the trend
caveat above: a real, statistically detectable difference that is tiny in
absolute terms. `busiest_head`/`quietest_head` are named explicitly (not just left
in `table`) since the full 36-row table may be truncated before an LLM sees it.

**Limitations.** The correlation matrix (`success_rate_correlation_matrix`) needs
≥2 heads with valid daily data; returns `{}` otherwise.

---

## 7. `failure_analysis` (`heads.py`)

**What it computes.** Failure distribution by status code, daily failure-rate
spikes, each head's dominant failure type, consecutive-failure bursts (≥3 in a
row for the same head), and cross-head hourly failure correlation.

**Method.** Bursts: contiguous same-head failure runs via a `cumsum`-based
run-length grouping (`(is_reject != is_reject.shift()).cumsum()`), kept if
`len(run) >= 3`. Daily spikes: same mean+2σ pattern as `anomaly_detection`'s
hourly version, applied to daily failure rate.

**Parameters.** `head_filter`, `time_range`.

**Interpreting results.** On the full archive: 1,096 failures (1,072 × status 65
RotatingAtRaise, 24 × status 9 EarlyRaise), 2 days with elevated failure rate, 1
burst of ≥3 consecutive failures. `failure_correlation_between_heads` needs ≥2
heads with hourly failure counts; `None` otherwise.

**Limitations.** Because true failures are extremely rare (0.002% of closures),
daily-spike and burst detection operate on very small counts — a "spike" day may
still be only a handful of failures in absolute terms; read alongside
`failure_distribution_by_status_code` for context.

---

## 8. `capping_speed_analysis` (`production.py`)

**What it computes.** Production speed in pieces/hour, reported **two ways,
deliberately not conflated**: `machine_wide_throughput_pph` (true aggregate rate
— `inferred_closure_count` summed across **all** heads per hour) and
`per_head_average_speed_pph` (mean of individual events' `capping_speed_pph`,
i.e. "how fast is one head", not the machine). A prior version of this tool only
reported the second number under the generic name "overall speed", which reads
like the first — this is fixed by naming and returning both explicitly.

**Method.** Hourly resampling (`resample("h")`) of `inferred_closure_count` for
machine-wide throughput; per-event `capping_speed_pph` (already
`inferred_closure_count`-aware, see [data_schema.md](data_schema.md)) averaged for
the per-head number. Speed anomalies: hourly throughput >2σ from its own average,
tagged `"slowdown"`/`"speedup"`.

**Parameters.** `idle_periods` (optional — if given and `exclude_idle=True`,
events inside a known idle window are dropped so the first closure after an idle
stretch doesn't report an artificially tiny speed), `head_filter`, `time_range`,
`exclude_idle` (default `True`).

**Interpreting results — gap-affected hours.** An event with `data_quality="gap"`
bundles every closure from an unsampled stretch into the one hour where data
resumes. This makes that hour's throughput read far higher than it really was
(e.g. one hour in this archive shows ~236,795 pph — ~4× the real peak — from
backlogged closures at the end of a 2026-02-04 sampling gap). The **total count is
still correct**; only the *hourly attribution* is wrong. These hours are **flagged
in `gap_affected_hours`, not dropped** (dropping would silently undercount), and
the tool's `summary` auto-appends a warning when any exist.

**Limitations.** On the full archive, machine-wide throughput (~26,610 pph) and
per-head average (~1,521 pph/head) differ by ~17.5× — always specify which one is
meant when asked about "production speed". Peak real hours (~51,800–51,877 pph)
are independently consistent with a typical 36-head AROL capper's rated throughput
(50,000–72,000 bph per manufacturer spec).

---

## 9. `idle_analysis` (`production.py`)

**What it computes.** Utilization rate, idle-period duration stats, idle time by
hour-of-day (for shift-pattern detection), and the 10 longest idle periods.

**Method.** `utilization_rate = productive_seconds / total_window_seconds`, where
`productive_seconds = total_window − total_idle`. Hourly attribution
(`_idle_seconds_by_hour_of_day`) splits a period spanning multiple hours across
each hour-of-day it actually overlaps, rather than bucketing by start time alone.

**Parameters.** `idle_periods` (required), `time_range` (optional).

**Interpreting results.** Full archive: 33.49% utilization, 3,486 periods,
1,421.2 total idle hours, longest single period 59.24h
(`2026-04-26 07:33:10 → 2026-04-28 18:47:44`).

**Limitations.** Without `time_range`, the total window is derived from the idle
periods' own min/max span, not the full closure_events time range — pass
`time_range` explicitly if idle periods happen to start later or end earlier than
production data.

---

## 10. `generate_kpi_dashboard` (`dashboard.py`)

**What it computes.** One-call rollup calling `success_rate_analysis`,
`torque_statistics`, `capping_speed_analysis`, `idle_analysis`, and
`anomaly_detection` internally, compiling a fixed KPI set plus a formatted
multi-line report-header string.

**Method.** No new statistics — pure composition/extraction from the tools above.

**Parameters.** `idle_periods` (required), `time_range` (optional).

**Interpreting results.** `kpis` includes both `machine_wide_throughput_pph` and
`per_head_average_speed_pph` side by side (labeled, per the tool 8 caveat above),
`worst_head`/`best_head` (by success rate), `n_anomalies` (z-score method),
`total_idle_hours`. `summary` is a fixed-format multi-line string (see
`reports/samples/kpi_dashboard.md` for a live example) suitable as a report
header.

**Limitations.** Inherits every caveat of the tools it calls internally (bimodal
torque, gap-affected hours, etc.) without repeating them in its own `summary` —
call the underlying tool directly for full detail on any one KPI.

---

## 11. `list_events` (`events.py`)

**What it computes.** Raw, filtered listing of individual closure events —
row-level data for "show me every X" questions the aggregate tools above don't
answer.

**Method.** Plain filtering + sort, no statistics.

**Parameters.** `outcome` (`"all"`, `"successful"`, `"failed"`; default `"all"`,
no-load always excluded), `head_filter`, `time_range`, `torque_min`, `torque_max`,
`limit` (default 200, most recent first).

**Interpreting results.** `total_matching` is the true, uncapped count — use it to
answer "how many" even when `events` itself is truncated at `limit`.

**Limitations.** Not paginated beyond `limit`/`truncated` — for very large result
sets, narrow with `head_filter`/`time_range`/torque bounds rather than raising
`limit` arbitrarily.

---

## 12. `torque_outcome_comparison` (`torque.py`)

**What it computes.** Successful-vs-failed torque distributions side by side,
with a Mann-Whitney U test (does one population tend to run higher/lower?).
`torque_statistics` reports one population at a time; this is the direct
head-to-head comparison.

**Method.** `scipy.stats.mannwhitneyu(successful, failed, alternative="two-sided")`
— a non-parametric rank-based test, appropriate since torque isn't normally
distributed and the two groups have wildly different sample sizes (successful
closures vastly outnumber failures).

**Parameters.** `head_filter`, `time_range`.

**Interpreting results.** `direction` (`"higher"`/`"lower"`) compares the two
means directly; `significant` is `p_value < 0.05`.

**Limitations.** Needs non-empty data in both groups — returns an explicit
"not enough data" summary otherwise rather than raising.

---

## 13. `torque_success_correlation` (`heads.py`)

**What it computes.** Tests whether heads with higher average torque also tend
to have higher (or lower) success rates — a per-head Pearson correlation between
mean torque (successful closures) and success rate (real closures).

**Method.** `scipy.stats.pearsonr` across per-head aggregates (one point per
head, not per event) — this is a **head-level**, not event-level, correlation.

**Parameters.** `head_filter`, `time_range`.

**Interpreting results.** `strength` is bucketed from `|r|`: weak (<0.3),
moderate (<0.7), strong (≥0.7); `direction` from the sign of `r`.

**Limitations.** Needs ≥3 heads with valid data (`pearsonr` needs at least 2
points to run at all, but the tool requires 3 to avoid a spurious "perfect"
correlation on 2 points); returns an explicit message and `pearson_r: None`
otherwise.

---

## 14. `render_chart` / `visualize` (`charts.py`)

**What it computes.** Renders one of 7 chart types (`torque_over_time`,
`torque_histogram`, `success_rate_per_head`, `failures_over_time`,
`production_over_time`, `utilization`, `kpi_dashboard`) as PNG image bytes over
the same filtered data the text tools use, using matplotlib with the `Agg`
(headless) backend.

**Method.** Standard matplotlib plots (line, histogram, bar, pie) styled with the
project's fixed categorical/status color palette. Notably, `success_rate_per_head`
plots each head's **deviation from the group average**, not the raw percentage —
real success rates cluster in a band under 1 percentage point wide, so a raw
0–100 axis would make every bar look identical.

**Parameters.** `chart_type` (required), `head_filter`, `time_range`.
`torque_over_time` breaks out per-head lines only when `head_filter` names ≤3
heads (otherwise a single aggregate line, to avoid an unreadable 36-line chart).

**Interpreting results.** Returns `images` (list of PNG bytes — `kpi_dashboard`
composes 4 separate full-size images rather than one cramped multi-panel figure)
and `series` (the underlying numeric data, for a text/ASCII fallback where a
displayed image isn't possible, e.g. the terminal bot).

**Limitations.** Called `visualize` (not `render_chart`) in the agent's tool
registry/executor dispatch — the function name and the tool name callers use
differ; see `agent/tools.py`/`agent/executor.py`.

---

## Design decisions

**Parquet over CSV.** `closure_events.parquet` is 55.1M rows; Parquet's columnar
storage and compression make repeated loads (every analytics CLI run, every
`ToolExecutor` construction) fast and keep memory bounded via categorical
downcasting (`analytics/io.py`) — CSV would need a full text re-parse of ~650MB
every time.

**Configurable thresholds, not magic numbers.** Every threshold used in
filtering/flagging logic (`IDLE_MIN_ROWS`, `GAP_FACTOR`, the `sensitivity=3.0`
default in `anomaly_detection`, `KRUSKAL_MAX_SAMPLE_PER_HEAD`) is a named
module-level constant with a documented rationale, not an inline literal — see
[architecture.md](architecture.md) for the ingestion-side thresholds specifically.

**No-load exclusion from success rates.** A `status=2` (No Load) event means the
machine cycled with nothing to cap — it isn't a capping attempt at all, so
counting it as neither a success nor a failure (rather than, say, a failure)
keeps "success rate" meaningful as "of the times we actually tried to cap
something, how often did it work."

**r² alongside p-value.** Every tool that runs a significance test on
tens-of-millions-of-rows data (`torque_trend_analysis`, `head_comparison`'s
Kruskal-Wallis) is paired with an effect-size measure (r², or the raw per-head
numbers in `head_comparison`'s table) specifically because p-value alone is
almost meaningless at this sample size — see the large-N caveats on tools 4 and 6
above.

**Cross-file boundary handling.** Correctness at all 88 file boundaries (closures,
resets, idle periods, and sampling gaps) is handled by threading state
(`CarryState`, `pending_idle_run`, `prev_last_ts`) across files in Layer 1, rather
than concatenating all 89 files into one in-memory table first — verified against
a true single-file merge, byte-identical results, while keeping memory bounded to
roughly one file at a time. See [architecture.md](architecture.md).

**Flicker-duplicate removal.** Without deduplication, a corrupted `Count` reading
recovering to its pre-glitch value could be misread as two separate closures at
the same counter value, which would in turn look like a "duplicate closure"
artifact and, worse, could be misclassified by a downstream consecutive-failure
detector. Deduplication is scoped to `(head_id, segment_id, counter)` so a
legitimate counter-value repeat *after* a real reset (a head revisiting counter
values it already used before resetting) is never mistaken for a duplicate. On
the current, already-cleaned archive this now finds **0** true duplicates — see
[architecture.md](architecture.md) for how the corrupted-reading fix upstream
prevents the 551 duplicates an earlier pipeline version found.
