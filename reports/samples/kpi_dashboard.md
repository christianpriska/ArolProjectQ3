# AROL Capping Machine — KPI Dashboard

**Period**: 2026-01-31 16:00:00 - 2026-04-30 16:59:59 (89 files)
**Generated**: 2026-08-25
**Source**: `data/processed/` (real ingested archive), via `generate_kpi_dashboard()` — see `reports/analytics_report.json` for the full raw output this report is built from.

## Key Performance Indicators

| KPI | Value |
|-----|-------|
| Overall success rate (excl. no-load) | 99.9965% |
| Mean torque (successful closures) | 2.014 Nm |
| Torque stability (std of per-head means) | 0.0010 Nm |
| Machine-wide throughput | 26,610 pph |
| Per-head average speed | 1,521.4 pph/head |
| Utilization rate | 33.49% |
| Worst-performing head | H29 (99.9867%) |
| Best-performing head | H24 (99.9995%) |
| Anomalies detected (z-score method) | 307,821 |
| Total idle time | 1,421.2h |

> Machine-wide throughput and per-head average speed are two different numbers, reported separately on purpose (~17.5x apart) — see `docs/analytics_methods.md` (tool 8) for why they must not be conflated.

## Head Performance Summary

All 36 heads, ranked by success rate (worst first). Source: `head_comparison()`.

| Rank | Head | Total Closures | Successful | Failed | Success % | Mean Torque (Nm) | Torque Std (Nm) |
|---|---|---|---|---|---|---|---|
| 1 | H24 | 1,531,611 | 879,754 | 4 | 99.9995% | 2.0116 | 0.0844 |
| 2 | H08 | 1,531,233 | 879,675 | 4 | 99.9995% | 2.0136 | 0.0839 |
| 3 | H07 | 1,531,245 | 879,761 | 5 | 99.9994% | 2.0125 | 0.0831 |
| 4 | H04 | 1,531,135 | 879,633 | 5 | 99.9994% | 2.0142 | 0.0837 |
| 5 | H02 | 1,531,417 | 879,894 | 6 | 99.9993% | 2.0146 | 0.0840 |
| 6 | H06 | 1,531,255 | 879,692 | 6 | 99.9993% | 2.0147 | 0.0833 |
| 7 | H09 | 1,531,181 | 879,661 | 6 | 99.9993% | 2.0121 | 0.0848 |
| 8 | H05 | 1,531,273 | 879,726 | 7 | 99.9992% | 2.0128 | 0.0851 |
| 9 | H14 | 1,531,139 | 879,359 | 10 | 99.9989% | 2.0132 | 0.0853 |
| 10 | H17 | 1,531,140 | 879,414 | 11 | 99.9987% | 2.0139 | 0.0845 |
| 11 | H03 | 1,531,350 | 879,748 | 12 | 99.9986% | 2.0132 | 0.0841 |
| 12 | H21 | 1,531,299 | 879,709 | 13 | 99.9985% | 2.0132 | 0.0842 |
| 13 | H12 | 1,531,357 | 879,684 | 13 | 99.9985% | 2.0152 | 0.0841 |
| 14 | H11 | 1,531,152 | 879,575 | 13 | 99.9985% | 2.0142 | 0.0843 |
| 15 | H23 | 1,531,584 | 879,759 | 18 | 99.9980% | 2.0131 | 0.0846 |
| 16 | H10 | 1,531,182 | 879,688 | 18 | 99.9980% | 2.0132 | 0.0833 |
| 17 | H34 | 1,531,742 | 880,023 | 20 | 99.9977% | 2.0140 | 0.0836 |
| 18 | H18 | 1,531,205 | 879,765 | 24 | 99.9973% | 2.0139 | 0.0838 |
| 19 | H20 | 1,531,530 | 880,002 | 25 | 99.9972% | 2.0142 | 0.0844 |
| 20 | H26 | 1,531,354 | 879,573 | 27 | 99.9969% | 2.0154 | 0.0834 |
| 21 | H25 | 1,531,611 | 879,889 | 30 | 99.9966% | 2.0125 | 0.0840 |
| 22 | H16 | 1,531,146 | 879,530 | 31 | 99.9965% | 2.0153 | 0.0841 |
| 23 | H15 | 1,531,400 | 879,850 | 34 | 99.9961% | 2.0135 | 0.0842 |
| 24 | H13 | 1,531,119 | 879,212 | 36 | 99.9959% | 2.0144 | 0.0849 |
| 25 | H28 | 1,531,659 | 880,081 | 37 | 99.9958% | 2.0132 | 0.0835 |
| 26 | H27 | 1,531,620 | 879,993 | 38 | 99.9957% | 2.0141 | 0.0837 |
| 27 | H19 | 1,531,274 | 879,732 | 40 | 99.9955% | 2.0142 | 0.0837 |
| 28 | H22 | 1,531,336 | 879,704 | 44 | 99.9950% | 2.0117 | 0.0841 |
| 29 | H31 | 1,531,716 | 879,633 | 48 | 99.9945% | 2.0129 | 0.0843 |
| 30 | H33 | 1,531,775 | 880,168 | 50 | 99.9943% | 2.0124 | 0.0838 |
| 31 | H32 | 1,531,745 | 879,740 | 63 | 99.9928% | 2.0134 | 0.0839 |
| 32 | H30 | 1,531,415 | 879,626 | 66 | 99.9925% | 2.0148 | 0.0830 |
| 33 | H36 | 1,531,429 | 879,552 | 68 | 99.9923% | 2.0151 | 0.0836 |
| 34 | H01 | 1,531,438 | 879,523 | 69 | 99.9922% | 2.0136 | 0.0853 |
| 35 | H35 | 1,531,728 | 879,887 | 78 | 99.9911% | 2.0149 | 0.0841 |
| 36 | H29 | 1,531,666 | 879,881 | 117 | 99.9867% | 2.0148 | 0.0838 |

## Notable Findings

- **Compared 36 heads. 5 flagged as statistical outliers. Most closures: H33 (1,531,775); fewest: H13 (1,531,119). Kruskal-Wallis on torque across heads: p=0 (significant).**

**Flagged heads** (>2σ from the group average on success rate, mean torque, or torque variability):

- H29 has significantly lower success rate (99.987 vs group avg 99.997)
- H22 has significantly lower mean torque (2.012 vs group avg 2.014)
- H24 has significantly lower mean torque (2.012 vs group avg 2.014)
- H01 has significantly higher torque variability (0.085 vs group avg 0.084)
- H14 has significantly higher torque variability (0.085 vs group avg 0.084)

- Kruskal-Wallis test on successful-closure torque across all 36 heads: statistic=173362.45, p=0 (significant, subsampled to <= 50,000 events/head for performance). Note the large-N caveat: per-head mean torque only spans 2.012-2.015 Nm — statistically real, but a tiny absolute spread (see `docs/analytics_methods.md`).
- Busiest head: **H33** (1,531,775 closures). Quietest head: **H13** (1,531,119 closures).
- 307,821 anomalies detected across 36 heads. H05 shows the most anomalies (8,598 events). 1 hour(s) with elevated failure rate.
- 9 hour(s) in the archive read as artificially inflated throughput due to a sampling-gap catch-up (see `docs/analytics_methods.md`, tool 8) — e.g. 2026-02-04 14:00:00 shows 236,795 pph from 236,795 backlogged closures, not a real production spike.

## Data Scope

- **55,130,461** observed closure events, **55,954,882** inferred closures, **36** heads
- Time range: 2026-01-31T16:00:06 → 2026-04-30T16:59:59 (89.0 days)
- Status breakdown: 31,670,096 successful, 1,096 failed, 23,459,257 no-load, 12 other
- 89 raw source files, ingested via `python -m arol_analytics.ingestion src/data`
