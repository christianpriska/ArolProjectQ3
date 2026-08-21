# AROL Analytics Report (Layer 2)

## Dataset Summary

55,130,461 closure events across 36 heads, 2026-01-31 16:00:06 to 2026-04-30 16:59:59 (89 days 00:59:53). Success rate (excluding no-load): 100.00% (31,670,096 successful / 1,096 failed). No-load events: 23,459,257.

## KPI Dashboard

```
=== AROL KPI Dashboard ===
Success rate: 100.00%
Mean torque (successful closures): 2.014 Nm
Torque stability (std of per-head means): 0.001 Nm
Machine-wide throughput: 26610 pph
  (per-head average: 1521.4 pph/head)
Utilization rate: 33.49%
Worst-performing head: H29 (99.99%)
Best-performing head: H24 (100.00%)
Anomalies detected (z-score method): 307,821
Total idle time: 1421.2h
```

## Head Comparison

Compared 36 heads. 5 flagged as statistical outliers. Kruskal-Wallis on torque across heads: p=0 (significant).

| head_id | total_closures | successful | failed | success_rate_pct | mean_torque_nm | std_torque_nm |
|---|---|---|---|---|---|---|
| H01 | 1531438 | 879523 | 69 | 99.992 | 2.014 | 0.085 |
| H02 | 1531417 | 879894 | 6 | 99.999 | 2.015 | 0.084 |
| H03 | 1531350 | 879748 | 12 | 99.999 | 2.013 | 0.084 |
| H04 | 1531135 | 879633 | 5 | 99.999 | 2.014 | 0.084 |
| H05 | 1531273 | 879726 | 7 | 99.999 | 2.013 | 0.085 |
| H06 | 1531255 | 879692 | 6 | 99.999 | 2.015 | 0.083 |
| H07 | 1531245 | 879761 | 5 | 99.999 | 2.013 | 0.083 |
| H08 | 1531233 | 879675 | 4 | 100.000 | 2.014 | 0.084 |
| H09 | 1531181 | 879661 | 6 | 99.999 | 2.012 | 0.085 |
| H10 | 1531182 | 879688 | 18 | 99.998 | 2.013 | 0.083 |
| H11 | 1531152 | 879575 | 13 | 99.999 | 2.014 | 0.084 |
| H12 | 1531357 | 879684 | 13 | 99.999 | 2.015 | 0.084 |
| H13 | 1531119 | 879212 | 36 | 99.996 | 2.014 | 0.085 |
| H14 | 1531139 | 879359 | 10 | 99.999 | 2.013 | 0.085 |
| H15 | 1531400 | 879850 | 34 | 99.996 | 2.013 | 0.084 |
| H16 | 1531146 | 879530 | 31 | 99.996 | 2.015 | 0.084 |
| H17 | 1531140 | 879414 | 11 | 99.999 | 2.014 | 0.085 |
| H18 | 1531205 | 879765 | 24 | 99.997 | 2.014 | 0.084 |
| H19 | 1531274 | 879732 | 40 | 99.995 | 2.014 | 0.084 |
| H20 | 1531530 | 880002 | 25 | 99.997 | 2.014 | 0.084 |
| H21 | 1531299 | 879709 | 13 | 99.999 | 2.013 | 0.084 |
| H22 | 1531336 | 879704 | 44 | 99.995 | 2.012 | 0.084 |
| H23 | 1531584 | 879759 | 18 | 99.998 | 2.013 | 0.085 |
| H24 | 1531611 | 879754 | 4 | 100.000 | 2.012 | 0.084 |
| H25 | 1531611 | 879889 | 30 | 99.997 | 2.013 | 0.084 |
| H26 | 1531354 | 879573 | 27 | 99.997 | 2.015 | 0.083 |
| H27 | 1531620 | 879993 | 38 | 99.996 | 2.014 | 0.084 |
| H28 | 1531659 | 880081 | 37 | 99.996 | 2.013 | 0.083 |
| H29 | 1531666 | 879881 | 117 | 99.987 | 2.015 | 0.084 |
| H30 | 1531415 | 879626 | 66 | 99.992 | 2.015 | 0.083 |
| H31 | 1531716 | 879633 | 48 | 99.995 | 2.013 | 0.084 |
| H32 | 1531745 | 879740 | 63 | 99.993 | 2.013 | 0.084 |
| H33 | 1531775 | 880168 | 50 | 99.994 | 2.012 | 0.084 |
| H34 | 1531742 | 880023 | 20 | 99.998 | 2.014 | 0.084 |
| H35 | 1531728 | 879887 | 78 | 99.991 | 2.015 | 0.084 |
| H36 | 1531429 | 879552 | 68 | 99.992 | 2.015 | 0.084 |

**Flagged heads:**
- H29 has significantly lower success rate (99.987 vs group avg 99.997)
- H22 has significantly lower mean torque (2.012 vs group avg 2.014)
- H24 has significantly lower mean torque (2.012 vs group avg 2.014)
- H01 has significantly higher torque variability (0.085 vs group avg 0.084)
- H14 has significantly higher torque variability (0.085 vs group avg 0.084)

## Failure Analysis

1,096 failures across 36 heads. 2 day(s) with elevated failure rate. 1 consecutive-failure burst(s) (>=3 in a row) detected.

**Per-head dominant failure type:**
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

**Consecutive failure bursts** (1):
- H29: 3 in a row, 2026-02-25 11:47:04 -> 2026-02-25 11:47:09 (types [65])

## Torque Trend

Torque trend across 36 heads: 36 show a statistically significant trend (36 increasing, 0 decreasing). 0 changepoint(s) detected. CAVEAT: mean r² across heads is only 0.0004 -- with this many events, p < 0.05 is easy to hit even when time explains almost none of the variance. Read 'significant' as statistically real, not necessarily practically meaningful; check r_squared and slope_nm_per_day before acting on it.

| head | slope (Nm/day) | direction | significant | p-value |
|---|---|---|---|---|
| H01 | 0.00006 | increasing | True | 5.64e-77 |
| H02 | 0.00006 | increasing | True | 6.026e-81 |
| H03 | 0.00005 | increasing | True | 9.814e-74 |
| H04 | 0.00005 | increasing | True | 3.8e-72 |
| H05 | 0.00006 | increasing | True | 9e-76 |
| H06 | 0.00005 | increasing | True | 1.183e-67 |
| H07 | 0.00006 | increasing | True | 1.393e-82 |
| H08 | 0.00006 | increasing | True | 2.482e-83 |
| H09 | 0.00005 | increasing | True | 3.087e-71 |
| H10 | 0.00006 | increasing | True | 1.547e-76 |
| H11 | 0.00006 | increasing | True | 1.007e-77 |
| H12 | 0.00006 | increasing | True | 1.252e-75 |
| H13 | 0.00006 | increasing | True | 6.633e-78 |
| H14 | 0.00006 | increasing | True | 1.117e-85 |
| H15 | 0.00005 | increasing | True | 4.705e-69 |
| H16 | 0.00005 | increasing | True | 4.085e-73 |
| H17 | 0.00006 | increasing | True | 8.725e-74 |
| H18 | 0.00006 | increasing | True | 1.422e-77 |
| H19 | 0.00005 | increasing | True | 8.068e-65 |
| H20 | 0.00006 | increasing | True | 2.876e-74 |
| H21 | 0.00006 | increasing | True | 2.469e-77 |
| H22 | 0.00006 | increasing | True | 6.283e-82 |
| H23 | 0.00006 | increasing | True | 2.426e-74 |
| H24 | 0.00006 | increasing | True | 2.51e-77 |
| H25 | 0.00005 | increasing | True | 5.182e-69 |
| H26 | 0.00005 | increasing | True | 1.445e-66 |
| H27 | 0.00006 | increasing | True | 3.875e-82 |
| H28 | 0.00005 | increasing | True | 3.638e-68 |
| H29 | 0.00005 | increasing | True | 3.543e-70 |
| H30 | 0.00006 | increasing | True | 9.797e-80 |
| H31 | 0.00005 | increasing | True | 4.708e-72 |
| H32 | 0.00005 | increasing | True | 8.977e-74 |
| H33 | 0.00005 | increasing | True | 2.01e-71 |
| H34 | 0.00005 | increasing | True | 3.726e-70 |
| H35 | 0.00005 | increasing | True | 5.146e-73 |
| H36 | 0.00006 | increasing | True | 3.463e-76 |

## Anomalies (z-score method)

307,821 anomalies detected across 36 heads. H05 shows the most anomalies (8,598 events). 1 hour(s) with elevated failure rate.

## Capping Speed

Machine-wide throughput: 26610 pph (range 1-236795). Per-head average: 1521.4 pph/head. 1 hour(s) flagged as significant throughput anomalies. WARNING: 9 hour(s) include gap-backlogged closures and read artificially high (e.g. 2026-02-04 14:00:00 shows 236795 pph) -- see gap_affected_hours.

**Gap-affected hours (throughput reads inflated, do not use for peak-rate claims):**
- 2026-02-04 14:00:00: 236795 pph -- 236795 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-02-27 13:00:00: 43938 pph -- 492 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-18 14:00:00: 2905 pph -- 467 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-18 15:00:00: 34398 pph -- 33947 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-18 17:00:00: 3526 pph -- 953 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-23 09:00:00: 1237 pph -- 318 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-23 10:00:00: 7129 pph -- 275 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-03-26 11:00:00: 368 pph -- 63 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).
- 2026-04-17 23:00:00: 18963 pph -- 889 closures from an unsampled gap were all attributed to this one hour when the data resumed -- they really happened over the gap's duration, not in this hour alone, so this hour's rate reads inflated (total count is still correct).

## Idle Analysis

Utilization rate: 33.5% (715.6h productive / 1421.2h idle). 3486 idle periods, median 270s, longest 59.2h.

**Top longest idle periods:**
- 2026-04-26 07:33:10 -> 2026-04-28 18:47:44 (59.24h)
- 2026-03-14 18:09:33 -> 2026-03-16 21:30:17 (51.35h)
- 2026-03-28 18:21:50 -> 2026-03-30 12:38:34 (42.28h)
- 2026-03-16 21:30:21 -> 2026-03-18 11:04:29 (37.57h)
- 2026-03-20 15:30:07 -> 2026-03-21 14:26:56 (22.95h)
- 2026-02-18 20:20:25 -> 2026-02-19 19:11:30 (22.85h)
- 2026-03-22 10:55:58 -> 2026-03-23 09:04:54 (22.15h)
- 2026-03-24 12:48:07 -> 2026-03-25 08:10:39 (19.38h)
- 2026-03-12 16:54:48 -> 2026-03-13 11:39:37 (18.75h)
- 2026-03-08 20:22:57 -> 2026-03-09 14:46:19 (18.39h)
