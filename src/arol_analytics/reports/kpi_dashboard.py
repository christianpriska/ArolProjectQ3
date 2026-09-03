# KPI dashboard report: KPI summary + full per-head performance table.

from __future__ import annotations

import pandas as pd

from arol_analytics.analytics._common import format_percentage
from arol_analytics.analytics.dashboard import generate_kpi_dashboard
from arol_analytics.analytics.heads import head_comparison
from arol_analytics.analytics.production import capping_speed_analysis
from arol_analytics.reports._common import dataset_period, fmt, generated_on


def render_kpi_dashboard_report(events: pd.DataFrame, idle_periods: pd.DataFrame) -> str:
    """Render the KPI dashboard report: headline KPIs, the full per-head
    ranking table, and notable findings -- built live from generate_kpi_dashboard()
    and head_comparison(), not from a pre-computed snapshot."""
    dashboard = generate_kpi_dashboard(events, idle_periods)
    k = dashboard["kpis"]
    comparison = head_comparison(events)
    speed = capping_speed_analysis(events, idle_periods=idle_periods)

    lines: list[str] = []
    lines.append("# AROL Capping Machine — KPI Dashboard")
    lines.append("")
    lines.append(f"**Period**: {dataset_period(events)}")
    lines.append(f"**Generated**: {generated_on()}")
    lines.append(
        "**Source**: `generate_kpi_dashboard()` + `head_comparison()`, run live against the ingested dataset."
    )
    lines.append("")

    lines.append("## Key Performance Indicators")
    lines.append("")
    lines.append("| KPI | Value |")
    lines.append("|-----|-------|")
    lines.append(
        f"| Overall success rate (excl. no-load) | {format_percentage(k['overall_success_rate_pct'])} "
        f"({k.get('successful_status_observations', 0):,} successful / "
        f"{k.get('failed_status_observations', 0):,} failed) |"
    )
    lines.append(f"| Mean torque (successful closures) | {fmt(k['mean_torque_nm'], '.3f', ' Nm')} |")
    lines.append(
        f"| Torque stability (std of per-head means) | {fmt(k['torque_stability_std_across_heads'], '.4f', ' Nm')} |"
    )
    lines.append(
        f"| Machine-wide throughput ({k.get('production_hours_with_closures', 0):,} hours "
        f"with recorded closures) | {fmt(k['machine_wide_throughput_pph'], ',.0f', ' pph')} |"
    )
    lines.append(f"| Per-head average speed | {fmt(k['per_head_average_speed_pph'], ',.1f', ' pph/head')} |")
    lines.append(
        f"| Utilization rate ({fmt(k.get('observation_window_hours'), '.1f')}h observation window) | "
        f"{fmt(k['utilization_rate_pct'], '.2f', '%')} |"
    )
    worst, best = k.get("worst_head"), k.get("best_head")
    if worst:
        lines.append(f"| Worst-performing head | {worst['head_id']} ({format_percentage(worst['success_rate_pct'])}) |")
    if best:
        lines.append(f"| Best-performing head | {best['head_id']} ({format_percentage(best['success_rate_pct'])}) |")
    lines.append(f"| Anomalies detected (z-score method) | {k['n_anomalies']:,} |")
    lines.append(f"| Total idle time | {fmt(k['total_idle_hours'], ',.1f', 'h')} |")
    lines.append("")
    lines.append(
        "> Machine-wide throughput is the average of the all-head hourly totals across hours containing "
        "at least one recorded production closure; zero-production hours are excluded. It and per-head "
        "average speed are two different numbers, reported separately on purpose -- see "
        "`docs/analytics_methods.md` (tool 8) for why they must not be conflated."
    )
    lines.append("")

    lines.append("## Head Performance Summary")
    lines.append("")
    table = comparison.get("table", [])
    lines.append(f"All {len(table)} heads, ranked by success rate (best first). Source: `head_comparison()`.")
    lines.append("")
    lines.append("| Rank | Head | Total Closures | Successful | Failed | Success % | Mean Torque (Nm) | Torque Std (Nm) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    ranked = sorted(table, key=lambda r: r["rank_success_rate"])
    for row in ranked:
        lines.append(
            f"| {int(row['rank_success_rate'])} | {row['head_id']} | {row['total_closures']:,} | "
            f"{int(row['successful']):,} | {int(row['failed']):,} | {format_percentage(row['success_rate_pct'])} | "
            f"{fmt(row['mean_torque_nm'], '.4f')} | {fmt(row['std_torque_nm'], '.4f')} |"
        )
    lines.append("")

    lines.append("## Notable Findings")
    lines.append("")
    lines.append(f"- **{comparison['summary']}**")
    lines.append("")
    flagged = comparison.get("flagged_heads", [])
    if flagged:
        lines.append("**Flagged heads** (>2σ from the group average on success rate, mean torque, or torque variability):")
        lines.append("")
        for f in flagged:
            lines.append(f"- {f}")
        lines.append("")
    kw = comparison.get("kruskal_wallis_torque_test")
    if kw and table:
        means = [r["mean_torque_nm"] for r in table if r.get("mean_torque_nm") is not None]
        verdict = "significant" if kw["significant"] else "not significant"
        spread = f" (per-head mean torque spans {min(means):.4f}-{max(means):.4f} Nm)" if means else ""
        lines.append(
            f"- Kruskal-Wallis test on successful-closure torque across heads: p={kw['p_value']:.4g} "
            f"({verdict}){spread} -- statistically real differences at this sample size can still be "
            "tiny in absolute terms; see `docs/analytics_methods.md` for the large-N caveat."
        )
    busiest, quietest = comparison.get("busiest_head"), comparison.get("quietest_head")
    if busiest and quietest:
        lines.append(
            f"- Busiest head: **{busiest['head_id']}** ({busiest['total_closures']:,} closures). "
            f"Quietest head: **{quietest['head_id']}** ({quietest['total_closures']:,} closures)."
        )
    gap_hours = speed.get("gap_affected_hours", [])
    if gap_hours:
        lines.append(
            f"- {len(gap_hours)} hour(s) read as artificially inflated throughput due to a sampling-gap "
            f"catch-up (see `docs/analytics_methods.md`, tool 8) -- e.g. {gap_hours[0]['hour']} shows "
            f"{gap_hours[0]['pieces_per_hour']:,.0f} pph from {gap_hours[0]['backlogged_closures']:,} "
            "backlogged closures, not a real production spike."
        )
    lines.append("")

    lines.append("## Data Scope")
    lines.append("")
    lines.append(f"- **{len(events):,}** observed closure events, **{events['head_id'].nunique()}** heads")
    lines.append(f"- Time range: {dataset_period(events)}")
    if not idle_periods.empty:
        lines.append(f"- **{len(idle_periods):,}** idle periods detected")
    lines.append("")

    return "\n".join(lines)
