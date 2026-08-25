# AROL Capping Machine — Head Comparison Report

**Period**: 2026-01-31 16:00:00 - 2026-04-30 16:59:59 (89 files)
**Generated**: 2026-08-25
**Source**: `head_comparison()` on the real ingested archive (`data/processed/`, 55,130,461 closure events, 36 heads).

Compared 36 heads. 5 flagged as statistical outliers. Most closures: H33 (1,531,775); fewest: H13 (1,531,119). Kruskal-Wallis on torque across heads: p=0 (significant).

## Full 36-Head Ranking

Ranked by success rate (best first); ties broken by the underlying `rank_success_rate` field.

| Rank | Head | Total Closures | Successful | Failed | Success % | Mean Torque (Nm) | Torque Std (Nm) | Rank (Torque) | Rank (Torque Std) | Rank (Volume) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | H24 | 1,531,611 | 879,754 | 4 | 99.9995% | 2.0116 | 0.0844 | 36 | 8 | 9 |
| 2 | H08 | 1,531,233 | 879,675 | 4 | 99.9995% | 2.0136 | 0.0839 | 20 | 22 | 27 |
| 3 | H07 | 1,531,245 | 879,761 | 5 | 99.9994% | 2.0125 | 0.0831 | 32 | 35 | 26 |
| 4 | H04 | 1,531,135 | 879,633 | 5 | 99.9994% | 2.0142 | 0.0837 | 13 | 28 | 35 |
| 5 | H02 | 1,531,417 | 879,894 | 6 | 99.9993% | 2.0146 | 0.0840 | 9 | 20 | 15 |
| 6 | H06 | 1,531,255 | 879,692 | 6 | 99.9993% | 2.0147 | 0.0833 | 8 | 33 | 25 |
| 7 | H09 | 1,531,181 | 879,661 | 6 | 99.9993% | 2.0121 | 0.0848 | 34 | 5 | 30 |
| 8 | H05 | 1,531,273 | 879,726 | 7 | 99.9992% | 2.0128 | 0.0851 | 30 | 3 | 24 |
| 9 | H14 | 1,531,139 | 879,359 | 10 | 99.9989% | 2.0132 | 0.0853 | 23 | 1 | 34 |
| 10 | H17 | 1,531,140 | 879,414 | 11 | 99.9987% | 2.0139 | 0.0845 | 18 | 7 | 33 |
| 11 | H03 | 1,531,350 | 879,748 | 12 | 99.9986% | 2.0132 | 0.0841 | 24 | 18 | 20 |
| 12 | H21 | 1,531,299 | 879,709 | 13 | 99.9985% | 2.0132 | 0.0842 | 27 | 12 | 22 |
| 13 | H12 | 1,531,357 | 879,684 | 13 | 99.9985% | 2.0152 | 0.0841 | 3 | 14 | 18 |
| 14 | H11 | 1,531,152 | 879,575 | 13 | 99.9985% | 2.0142 | 0.0843 | 11 | 10 | 31 |
| 15 | H23 | 1,531,584 | 879,759 | 18 | 99.9980% | 2.0131 | 0.0846 | 28 | 6 | 11 |
| 16 | H10 | 1,531,182 | 879,688 | 18 | 99.9980% | 2.0132 | 0.0833 | 25 | 34 | 29 |
| 17 | H34 | 1,531,742 | 880,023 | 20 | 99.9977% | 2.0140 | 0.0836 | 16 | 29 | 3 |
| 18 | H18 | 1,531,205 | 879,765 | 24 | 99.9973% | 2.0139 | 0.0838 | 17 | 25 | 28 |
| 19 | H20 | 1,531,530 | 880,002 | 25 | 99.9972% | 2.0142 | 0.0844 | 12 | 9 | 12 |
| 20 | H26 | 1,531,354 | 879,573 | 27 | 99.9969% | 2.0154 | 0.0834 | 1 | 32 | 19 |
| 21 | H25 | 1,531,611 | 879,889 | 30 | 99.9966% | 2.0125 | 0.0840 | 31 | 19 | 9 |
| 22 | H16 | 1,531,146 | 879,530 | 31 | 99.9965% | 2.0153 | 0.0841 | 2 | 17 | 32 |
| 23 | H15 | 1,531,400 | 879,850 | 34 | 99.9961% | 2.0135 | 0.0842 | 21 | 13 | 17 |
| 24 | H13 | 1,531,119 | 879,212 | 36 | 99.9959% | 2.0144 | 0.0849 | 10 | 4 | 36 |
| 25 | H28 | 1,531,659 | 880,081 | 37 | 99.9958% | 2.0132 | 0.0835 | 26 | 31 | 7 |
| 26 | H27 | 1,531,620 | 879,993 | 38 | 99.9957% | 2.0141 | 0.0837 | 15 | 27 | 8 |
| 27 | H19 | 1,531,274 | 879,732 | 40 | 99.9955% | 2.0142 | 0.0837 | 14 | 26 | 23 |
| 28 | H22 | 1,531,336 | 879,704 | 44 | 99.9950% | 2.0117 | 0.0841 | 35 | 16 | 21 |
| 29 | H31 | 1,531,716 | 879,633 | 48 | 99.9945% | 2.0129 | 0.0843 | 29 | 11 | 5 |
| 30 | H33 | 1,531,775 | 880,168 | 50 | 99.9943% | 2.0124 | 0.0838 | 33 | 23 | 1 |
| 31 | H32 | 1,531,745 | 879,740 | 63 | 99.9928% | 2.0134 | 0.0839 | 22 | 21 | 2 |
| 32 | H30 | 1,531,415 | 879,626 | 66 | 99.9925% | 2.0148 | 0.0830 | 6 | 36 | 16 |
| 33 | H36 | 1,531,429 | 879,552 | 68 | 99.9923% | 2.0151 | 0.0836 | 4 | 30 | 14 |
| 34 | H01 | 1,531,438 | 879,523 | 69 | 99.9922% | 2.0136 | 0.0853 | 19 | 2 | 13 |
| 35 | H35 | 1,531,728 | 879,887 | 78 | 99.9911% | 2.0149 | 0.0841 | 5 | 15 | 4 |
| 36 | H29 | 1,531,666 | 879,881 | 117 | 99.9867% | 2.0148 | 0.0838 | 7 | 24 | 6 |

## Statistical Test Results

**Kruskal-Wallis test** (successful-closure torque across all 36 heads — does torque differ significantly by head?):

- Statistic: 173362.45
- p-value: 0
- Verdict: **significant**
- Note: subsampled to <= 50,000 events/head for performance

**Interpretation**: the test result is statistically significant (p≈0), but per-head mean torque only spans **2.0116–2.0154 Nm** — a spread of 0.19% of the smallest mean. With ~880k successful closures per head, even a negligible real difference between heads is easy to detect statistically. This is the same large-N pattern documented for `torque_trend_analysis` in `docs/analytics_methods.md` — read the table above for the actual magnitude, not the p-value alone.

## Flagged Heads

Heads more than 2 standard deviations from the group average on success rate, mean torque, or torque variability:

- H29 has significantly lower success rate (99.987 vs group avg 99.997)
- H22 has significantly lower mean torque (2.012 vs group avg 2.014)
- H24 has significantly lower mean torque (2.012 vs group avg 2.014)
- H01 has significantly higher torque variability (0.085 vs group avg 0.084)
- H14 has significantly higher torque variability (0.085 vs group avg 0.084)

None of these are large in absolute terms (see the ranking table) — they are statistical outliers relative to an already extremely tight, well-behaved population of 36 heads, not indications of a malfunctioning head. H29's flag is consistent with it also having the most consecutive-failure burst and the highest single-head failure count in `reports/samples/anomaly_report.md`.

## Torque Variability Analysis

Top 5 heads by torque standard deviation (highest variability):

| Head | Torque Std (Nm) | Mean Torque (Nm) | Coefficient of Variation |
|---|---|---|---|
| H14 | 0.0853 | 2.0132 | 0.0424 |
| H01 | 0.0853 | 2.0136 | 0.0424 |
| H05 | 0.0851 | 2.0128 | 0.0423 |
| H13 | 0.0849 | 2.0144 | 0.0421 |
| H09 | 0.0848 | 2.0121 | 0.0422 |

Bottom 5 heads by torque standard deviation (lowest variability):

| Head | Torque Std (Nm) | Mean Torque (Nm) | Coefficient of Variation |
|---|---|---|---|
| H30 | 0.0830 | 2.0148 | 0.0412 |
| H07 | 0.0831 | 2.0125 | 0.0413 |
| H10 | 0.0833 | 2.0132 | 0.0414 |
| H06 | 0.0833 | 2.0147 | 0.0414 |
| H26 | 0.0834 | 2.0154 | 0.0414 |

All 36 heads' torque std falls in a tight band (0.0830-0.0853 Nm) — consistent with the archive-wide finding that torque variability is a process characteristic shared across the whole machine, not a per-head defect signature.

## Busiest / Quietest Heads

- Busiest: **H33** (1,531,775 total closures)
- Quietest: **H13** (1,531,119 total closures)
- Spread: 656 closures (0.043% of the quietest head's volume) — heads are close to evenly loaded.
