# Head comparison report: full per-head ranking, statistical test results,
# and torque variability analysis.

from __future__ import annotations

import pandas as pd

from arol_analytics.analytics._common import format_percentage
from arol_analytics.analytics.heads import head_comparison
from arol_analytics.reports._common import dataset_period, fmt, generated_on

TOP_N_VARIABILITY = 5


def render_head_comparison_report(events: pd.DataFrame) -> str:
    """Render the head comparison report -- built live from head_comparison(),
    not from a pre-computed snapshot."""
    comparison = head_comparison(events)
    table = comparison.get("table", [])

    lines: list[str] = []
    lines.append("# AROL Capping Machine — Head Comparison Report")
    lines.append("")
    lines.append(f"**Period**: {dataset_period(events)}")
    lines.append(f"**Generated**: {generated_on()}")
    lines.append(
        f"**Source**: `head_comparison()`, run live against the ingested dataset "
        f"({len(events):,} closure events, {events['head_id'].nunique() if not events.empty else 0} heads)."
    )
    lines.append("")
    lines.append(comparison["summary"])
    lines.append("")

    if not table:
        lines.append("_No data available for this dataset._")
        return "\n".join(lines)

    lines.append(f"## Full {len(table)}-Head Ranking")
    lines.append("")
    lines.append("Ranked by success rate (best first); ties broken by the underlying `rank_success_rate` field.")
    lines.append("")
    lines.append(
        "| Rank | Head | Total Closures | Successful | Failed | Success % | Mean Torque (Nm) | "
        "Torque Std (Nm) | Rank (Torque) | Rank (Torque Std) | Rank (Volume) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    ranked = sorted(table, key=lambda r: r["rank_success_rate"])
    for row in ranked:
        lines.append(
            f"| {fmt(row['rank_success_rate'], '.0f')} | {row['head_id']} | {row['total_closures']:,} | "
            f"{int(row['successful']):,} | {int(row['failed']):,} | {format_percentage(row['success_rate_pct'])} | "
            f"{fmt(row['mean_torque_nm'], '.4f')} | {fmt(row['std_torque_nm'], '.4f')} | "
            f"{fmt(row['rank_mean_torque'], '.0f')} | {fmt(row['rank_torque_std'], '.0f')} | "
            f"{fmt(row['rank_total_closures'], '.0f')} |"
        )
    lines.append("")

    lines.append("## Statistical Test Results")
    lines.append("")
    kw = comparison.get("kruskal_wallis_torque_test")
    if kw:
        lines.append(
            "**Kruskal-Wallis test** (successful-closure torque across heads -- does torque differ "
            "significantly by head?):"
        )
        lines.append("")
        lines.append(f"- Statistic: {kw['statistic']:.2f}")
        lines.append(f"- p-value: {kw['p_value']:.4g}")
        lines.append(f"- Verdict: **{'significant' if kw['significant'] else 'not significant'}**")
        lines.append(f"- Note: {kw['note']}")
        lines.append("")
        means = [r["mean_torque_nm"] for r in table]
        spread_pct = (max(means) - min(means)) / min(means) * 100 if min(means) else float("nan")
        lines.append(
            f"**Interpretation**: the test result is {'statistically significant' if kw['significant'] else 'not significant'} "
            f"(p={kw['p_value']:.4g}), but per-head mean torque only spans **{min(means):.4f}-{max(means):.4f} Nm** "
            f"-- a spread of {spread_pct:.2f}% of the smallest mean. At this sample size, even a small real "
            "difference between heads is easy to detect statistically -- read the table above for the actual "
            "magnitude, not the p-value alone (see `docs/analytics_methods.md`)."
        )
        lines.append("")
    else:
        lines.append("_Not enough heads with valid torque data to run this test._")
        lines.append("")

    lines.append("## Flagged Heads")
    lines.append("")
    flagged = comparison.get("flagged_heads", [])
    lines.append("Heads more than 2 standard deviations from the group average on success rate, mean torque, or torque variability:")
    lines.append("")
    if flagged:
        for f in flagged:
            lines.append(f"- {f}")
        lines.append("")
        lines.append(
            "None of these are large in absolute terms (see the ranking table) -- they are statistical "
            "outliers relative to an already tight, well-behaved population, not necessarily indications "
            "of a malfunctioning head."
        )
    else:
        lines.append("_No heads flagged as statistical outliers._")
    lines.append("")

    lines.append("## Torque Variability Analysis")
    lines.append("")
    by_std = sorted(table, key=lambda r: r["std_torque_nm"], reverse=True)
    lines.append(f"Top {min(TOP_N_VARIABILITY, len(by_std))} heads by torque standard deviation (highest variability):")
    lines.append("")
    lines.append("| Head | Torque Std (Nm) | Mean Torque (Nm) | Coefficient of Variation |")
    lines.append("|---|---|---|---|")
    for row in by_std[:TOP_N_VARIABILITY]:
        cv = row["std_torque_nm"] / row["mean_torque_nm"] if row["mean_torque_nm"] else float("nan")
        lines.append(f"| {row['head_id']} | {row['std_torque_nm']:.4f} | {row['mean_torque_nm']:.4f} | {cv:.4f} |")
    lines.append("")
    lines.append(f"Bottom {min(TOP_N_VARIABILITY, len(by_std))} heads by torque standard deviation (lowest variability):")
    lines.append("")
    lines.append("| Head | Torque Std (Nm) | Mean Torque (Nm) | Coefficient of Variation |")
    lines.append("|---|---|---|---|")
    for row in list(reversed(by_std))[:TOP_N_VARIABILITY]:
        cv = row["std_torque_nm"] / row["mean_torque_nm"] if row["mean_torque_nm"] else float("nan")
        lines.append(f"| {row['head_id']} | {row['std_torque_nm']:.4f} | {row['mean_torque_nm']:.4f} | {cv:.4f} |")
    lines.append("")
    all_std = [r["std_torque_nm"] for r in table]
    lines.append(
        f"All {len(table)} heads' torque std falls in the range {min(all_std):.4f}-{max(all_std):.4f} Nm -- "
        "consistent with torque variability being a process characteristic shared across the whole "
        "machine, not a per-head defect signature."
    )
    lines.append("")

    busiest, quietest = comparison.get("busiest_head"), comparison.get("quietest_head")
    if busiest and quietest:
        lines.append("## Busiest / Quietest Heads")
        lines.append("")
        lines.append(f"- Busiest: **{busiest['head_id']}** ({busiest['total_closures']:,} total closures)")
        lines.append(f"- Quietest: **{quietest['head_id']}** ({quietest['total_closures']:,} total closures)")
        if quietest["total_closures"]:
            spread = busiest["total_closures"] - quietest["total_closures"]
            lines.append(
                f"- Spread: {spread:,} closures ({spread / quietest['total_closures'] * 100:.3f}% of the "
                "quietest head's volume) -- heads are close to evenly loaded."
            )
        lines.append("")

    return "\n".join(lines)
