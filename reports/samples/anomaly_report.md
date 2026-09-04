# AROL Capping Machine — Anomaly & Failure Report

**Period**: 2026-01-31 16:00:06 - 2026-04-30 16:59:59
**Generated**: 2026-09-04
**Source**: `anomaly_detection(method="zscore")` + `failure_analysis()`, run live against the ingested dataset.

## Anomaly Detection (z-score method)

307,821 anomalies detected across 36 heads. H05 shows the most anomalies (8,598 events). 1 hour(s) with elevated failure rate.

> **Read this alongside the failure counts below, not as a proxy for them.** Z-score anomaly detection flags torque readings far from each head's own successful-closure mean/std -- on a large archive this includes a large volume of legitimate distribution-tail readings, not mechanical faults. See `docs/analytics_methods.md` (tool 5) for the caveat.

**Anomaly counts per head (top 10):**

| Head | Anomalies |
|---|---|
| H05 | 8,598 |
| H13 | 8,595 |
| H01 | 8,591 |
| H11 | 8,582 |
| H23 | 8,580 |
| H20 | 8,568 |
| H35 | 8,565 |
| H14 | 8,561 |
| H12 | 8,560 |
| H21 | 8,560 |

**Elevated failure-rate windows (hourly)**: 1 hour(s) flagged.

| Hour | Failure Rate | Events |
|---|---|---|
| 2026-04-10 18:00:00 | 100.00% | 1 |

## Failure Analysis

1,096 failures across 36 heads. 2 day(s) with elevated failure rate. 1 consecutive-failure burst(s) (>=3 in a row) detected.

**Failure breakdown by status code:**

| Status Code | Label | Count |
|---|---|---|
| 65 | RotatingAtRaise | 1,072 |
| 9 | EarlyRaise | 24 |

**Daily failure-rate spikes:**

| Date | Failure Rate | Failures |
|---|---|---|
| 2026-03-14 | 0.0245% | 2 |
| 2026-03-30 | 0.0473% | 2 |

**Per-head dominant failure type** (heads with at least one failure):

- H01: dominant failure RotatingAtRaise (69 events)
- H02: dominant failure RotatingAtRaise (6 events)
- H03: dominant failure RotatingAtRaise (12 events)
- H04: dominant failure RotatingAtRaise (5 events)
- H05: dominant failure RotatingAtRaise (7 events)
- H06: dominant failure RotatingAtRaise (6 events)
- H07: dominant failure RotatingAtRaise (5 events)
- H08: dominant failure RotatingAtRaise (4 events)
- H09: dominant failure RotatingAtRaise (6 events)
- H10: dominant failure RotatingAtRaise (18 events)
- H11: dominant failure RotatingAtRaise (13 events)
- H12: dominant failure RotatingAtRaise (13 events)
- H13: dominant failure RotatingAtRaise (35 events)
- H14: dominant failure RotatingAtRaise (10 events)
- H15: dominant failure RotatingAtRaise (33 events)
- H16: dominant failure RotatingAtRaise (31 events)
- H17: dominant failure RotatingAtRaise (9 events)
- H18: dominant failure RotatingAtRaise (23 events)
- H19: dominant failure RotatingAtRaise (40 events)
- H20: dominant failure RotatingAtRaise (25 events)
- H21: dominant failure RotatingAtRaise (13 events)
- H22: dominant failure RotatingAtRaise (42 events)
- H23: dominant failure RotatingAtRaise (18 events)
- H24: dominant failure RotatingAtRaise (4 events)
- H25: dominant failure RotatingAtRaise (29 events)
- H26: dominant failure RotatingAtRaise (26 events)
- H27: dominant failure RotatingAtRaise (37 events)
- H28: dominant failure RotatingAtRaise (37 events)
- H29: dominant failure RotatingAtRaise (111 events)
- H30: dominant failure RotatingAtRaise (62 events)
- H31: dominant failure RotatingAtRaise (48 events)
- H32: dominant failure RotatingAtRaise (62 events)
- H33: dominant failure RotatingAtRaise (50 events)
- H34: dominant failure RotatingAtRaise (19 events)
- H35: dominant failure RotatingAtRaise (77 events)
- H36: dominant failure RotatingAtRaise (67 events)

**Consecutive failure bursts** (>=3 in a row, same head):

| Head | Start | End | Count | Failure Types |
|---|---|---|---|---|
| H29 | 2026-02-25 11:47:04 | 2026-02-25 11:47:09 | 3 | [65] |

## Heads With Unusual Patterns

Cross-referencing `head_comparison`'s flagged outliers (>2σ from the group average):

- H29 has significantly lower success rate (99.987 vs group avg 99.997)
- H22 has significantly lower mean torque (2.012 vs group avg 2.014)
- H24 has significantly lower mean torque (2.012 vs group avg 2.014)
- H01 has significantly higher torque variability (0.085 vs group avg 0.084)
- H14 has significantly higher torque variability (0.085 vs group avg 0.084)

- **H05** shows the most z-score torque anomalies (8,598 events) -- this tracks each head's own torque spread, not necessarily a defect (see caveat above).

## Monitoring Recommendations

- Treat z-score anomaly counts (307,821) as a torque-variability signal, not a failure count -- track true failures (`failure_analysis`, reject status codes) as the primary quality KPI.
- Investigate **H29** for the recorded consecutive-failure burst(s) -- worth a maintenance log check even if isolated so far.
- Re-run `anomaly_detection(method="iqr")` periodically alongside the default z-score method -- IQR is more robust to a handful of extreme outliers and can catch cases z-score's self-referential baseline might under-flag.
- The elevated failure-rate hours/days above are worth cross-checking against maintenance or changeover logs for that period, since they concentrate a disproportionate share of the archive's already-rare failures.
