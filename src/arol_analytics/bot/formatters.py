# Turns raw Layer-2 tool-output dicts (see arol_analytics.analytics docstrings)
# and Layer-3 AgentResponse objects into text for the terminal chat interface.
# Uses a small HTML-ish tag subset (<b>, <i>, <pre>) that terminal_sim.py's
# html_to_terminal() converts to ANSI styling -- not real HTML, just a
# convenient shared markup between formatting and rendering.
#
# Every public `fmt_*` function returns (short, full): `short` is what gets
# shown immediately (safe to always show), `full` is `None` unless there's a
# bigger table worth hiding behind a "Show Full Table" button -- callers stash
# it and only show it if the user asks for it.

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from arol_analytics.analytics._common import format_percentage

FullTable = str | None


def esc(value: Any) -> str:
    return html.escape(str(value))


def fmt_num(value: Any, spec: str = ".2f", suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "n/a"
    try:
        return f"{value:{spec}}{suffix}"
    except (ValueError, TypeError):
        return esc(value)


def fmt_compact(value: float) -> str:
    """1,530,000 -> 1.53M, 55,100,000 -> 55.1M -- for headline counts."""
    if value is None or value != value:
        return "n/a"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:,.0f}"


def make_table(headers: list[str], rows: list[list[str]], max_rows: int | None = None) -> str:
    """Monospace table, wrapped in a <pre> block by callers."""
    display_rows = rows if max_rows is None else rows[:max_rows]
    widths = [len(h) for h in headers]
    for row in display_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(cells: Iterable[Any]) -> str:
        return " | ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    lines = [fmt_row(headers), "-+-".join("-" * w for w in widths)]
    lines += [fmt_row(r) for r in display_rows]
    if max_rows is not None and len(rows) > max_rows:
        lines.append(f"... ({len(rows) - max_rows} more rows -- use the button below)")
    return "\n".join(lines)


def pre(text: str) -> str:
    return f"<pre>{esc(text)}</pre>"


# ---------------------------------------------------------------------------
# Tool 1: dataset_summary
# ---------------------------------------------------------------------------


def fmt_dataset_summary(result: dict[str, Any]) -> tuple[str, FullTable]:
    if not result.get("total_events"):
        return f"📋 <b>Dataset Summary</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    tr = result["time_range"]
    sb = result["status_breakdown"]
    lines = [
        "📋 <b>Dataset Summary</b>",
        "",
        f"📦 Total events: <b>{fmt_compact(result['total_events'])}</b> ({result['total_events']:,})",
        f"🔩 Heads: <b>{result['n_heads']}</b> ({result['heads'][0]}–{result['heads'][-1]})",
        f"📅 Period: {esc(tr['start'])} → {esc(tr['end'])} ({tr['duration_days']:.1f} days)",
        "",
        f"✅ Successful: {sb['successful']:,}",
        f"❌ Failed: {sb['failed']:,}",
        f"💤 No-load: {sb['no_load']:,}",
        f"❔ Other: {sb['other']:,}",
        f"📈 Success rate (excl. no-load): <b>{format_percentage(result['overall_success_rate_pct'])}</b>",
    ]
    if result.get("duplicates_removed_total") is not None:
        lines.append(f"🧹 Duplicates removed during ingestion: {result['duplicates_removed_total']:,}")
    if result.get("quality_flags"):
        lines += ["", "⚠️ <b>Data quality flags:</b>"]
        lines += [f"  • {esc(f)}" for f in result["quality_flags"]]
    return "\n".join(lines), None


def fmt_data_quality(result: dict[str, Any]) -> tuple[str, FullTable]:
    lines = ["📋 <b>Data Quality Report</b>", ""]
    flags = result.get("quality_flags") or []
    if flags:
        lines += [f"⚠️ {esc(f)}" for f in flags]
    else:
        lines.append("✅ No data-quality flags recorded for this dataset.")
    lines.append("")
    lines.append(esc(result.get("summary", "")))
    return "\n".join(lines), None


# ---------------------------------------------------------------------------
# Tool 2: success_rate_analysis
# ---------------------------------------------------------------------------


def fmt_success_rate(result: dict[str, Any]) -> tuple[str, FullTable]:
    table = result.get("table", [])
    if not table:
        return f"✅ <b>Success Rate</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    header = f"✅ <b>Success Rate Analysis</b> ({esc(result['group_by'])})\n\n{esc(result['summary'])}"

    if result["group_by"] == "overall":
        row = table[0]
        body = (
            f"\n\nSuccessful: {row['successful']:,}\n"
            f"Failed: {row['failed']:,}\n"
            f"Other: {row['other_count']:,}\n"
            f"Success rate: <b>{format_percentage(row['success_rate_pct'])}</b>"
        )
        return header + body, None

    rows = sorted(table, key=lambda r: r["group"]) if result["group_by"] != "per_head" else table
    full_rows = [
        [r["group"], format_percentage(r["success_rate_pct"]), f"{r['total_closures']:,}"] for r in rows
    ]
    full_table = make_table(["Group", "Success%", "Total"], full_rows)

    if len(table) <= 8:
        return header + "\n\n" + pre(full_table), None

    # highlight best/worst for long tables (e.g. per_head across 36 heads, daily over ~90 days)
    by_rate = sorted((r for r in table if r["success_rate_pct"] == r["success_rate_pct"]), key=lambda r: r["success_rate_pct"])
    worst = by_rate[:3]
    best = list(reversed(by_rate[-3:]))
    lines = [header, "", "📉 <b>Worst:</b>"]
    lines += [f"  {esc(r['group'])}: {format_percentage(r['success_rate_pct'])}" for r in worst]
    lines += ["", "📈 <b>Best:</b>"]
    lines += [f"  {esc(r['group'])}: {format_percentage(r['success_rate_pct'])}" for r in best]
    if result.get("flagged_groups"):
        lines += ["", f"⚠️ Flagged (>2σ below average): {', '.join(esc(g) for g in result['flagged_groups'])}"]
    lines += ["", f"📋 {len(table)} groups total -- tap below for the full table."]
    return "\n".join(lines), full_table


# ---------------------------------------------------------------------------
# Tool 3/4: torque_statistics, torque_trend_analysis
# ---------------------------------------------------------------------------


def fmt_torque_statistics(result: dict[str, Any]) -> tuple[str, FullTable]:
    table = result.get("table", [])
    if not table:
        return f"🔧 <b>Torque Statistics</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    header = f"🔧 <b>Torque Statistics</b> ({esc(result['filter_status'])}, {esc(result['group_by'])})"
    if result.get("warning"):
        header += f"\n⚠️ {esc(result['warning'])}"

    if result["group_by"] == "overall":
        r = table[0]
        body = (
            f"\n\nMean: <b>{fmt_num(r['mean'], '.3f')} Nm</b>  (median {fmt_num(r['median'], '.3f')})\n"
            f"Std: {fmt_num(r['std'], '.3f')}  |  CV: {fmt_num(r['coefficient_of_variation'], '.3f')}\n"
            f"Range: {fmt_num(r['min'], '.3f')} – {fmt_num(r['max'], '.3f')} Nm\n"
            f"Q1/Q3: {fmt_num(r['q1'], '.3f')} / {fmt_num(r['q3'], '.3f')}  (IQR {fmt_num(r['iqr'], '.3f')})\n"
            f"IQR outliers: {r['outlier_count']:,}  |  n = {r['count']:,}"
        )
        return header + body, None

    full_rows = [
        [r["group"], fmt_num(r["mean"], "0.3f"), fmt_num(r["std"], "0.3f"), f"{int(r['count']):,}"] for r in table
    ]
    full_table = make_table(["Group", "MeanNm", "Std", "N"], full_rows)

    if len(table) <= 8:
        return header + "\n\n" + pre(full_table), None

    if result.get("flagged_high_variability"):
        header += f"\n\n⚠️ High-variability heads: {', '.join(esc(g) for g in result['flagged_high_variability'])}"
    header += f"\n\n📋 {len(table)} groups total -- tap below for the full table."
    return header, full_table


def fmt_torque_trend(result: dict[str, Any]) -> tuple[str, FullTable]:
    trend = result.get("per_head_trend", {})
    if not trend:
        return f"📈 <b>Torque Trend</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    header = f"📈 <b>Torque Trend / Drift Detection</b>\n\n{esc(result['summary'])}"

    rows = sorted(trend.items(), key=lambda kv: kv[0])
    full_rows = [
        [h, v["direction"], fmt_num(v["slope_nm_per_day"], "+.5f"), fmt_num(v["r_squared"], ".4f"), "yes" if v["significant"] else "no"]
        for h, v in rows
    ]
    full_table = make_table(["Head", "Direction", "Slope/day", "r2", "Sig?"], full_rows)

    if len(rows) <= 8:
        return header + "\n\n" + pre(full_table), None

    drifting = [h for h, v in rows if v["direction"] != "stable"]
    body = f"\n\n{len(drifting)}/{len(rows)} heads show a directional trend."
    if drifting:
        body += f"\nDrifting: {', '.join(drifting[:10])}" + (" ..." if len(drifting) > 10 else "")
    if result.get("changepoints"):
        body += f"\n\n⚡ {len(result['changepoints'])} changepoint(s) detected."
    body += "\n\n📋 Tap below for the full per-head table."
    return header + body, full_table


# ---------------------------------------------------------------------------
# Tool 5: anomaly_detection
# ---------------------------------------------------------------------------


def fmt_anomaly_detail(result: dict[str, Any]) -> tuple[str, FullTable]:
    header = f"⚠️ <b>Anomaly Detection</b> ({esc(result.get('method', ''))})\n\n{esc(result['summary'])}"
    anomalies = result.get("anomalies", [])
    if not anomalies:
        return header, None

    full_rows = [
        [a["timestamp"], a["head_id"], fmt_num(a["torque_nm"], ".3f"), str(a["status_code"])] for a in anomalies[:200]
    ]
    full_table = make_table(["Timestamp", "Head", "TorqueNm", "Status"], full_rows)

    top5 = anomalies[:5]
    lines = [header, "", "Top deviations:"]
    for a in top5:
        lines.append(f"  {esc(a['head_id'])} @ {esc(a['timestamp'])}: {esc(a['reason'])}")
    lines.append(f"\n📋 {result['total_anomalies']:,} total -- tap below for a fuller list.")
    return "\n".join(lines), full_table


def fmt_anomaly_summary(result: dict[str, Any]) -> tuple[str, FullTable]:
    header = f"⚠️ <b>Anomaly Summary</b> ({esc(result.get('method', ''))})\n\n{esc(result['summary'])}"
    per_head = result.get("anomaly_count_per_head", {})
    if not per_head:
        return header, None

    ranked = sorted(per_head.items(), key=lambda kv: kv[1], reverse=True)
    full_table = make_table(["Head", "Anomalies"], [[h, f"{c:,}"] for h, c in ranked])

    lines = [header, "", "Top heads by anomaly count:"]
    lines += [f"  {esc(h)}: {c:,}" for h, c in ranked[:8]]
    if result.get("elevated_failure_rate_windows"):
        lines.append(f"\n⏱️ {len(result['elevated_failure_rate_windows'])} hour(s) with elevated failure rate.")
    if len(ranked) > 8:
        lines.append(f"\n📋 {len(ranked)} heads total -- tap below for the full breakdown.")
        return "\n".join(lines), full_table
    return "\n".join(lines), None


# ---------------------------------------------------------------------------
# Tool 6: head_comparison
# ---------------------------------------------------------------------------


def fmt_head_comparison(result: dict[str, Any], flagged_only: bool = False) -> tuple[str, FullTable]:
    table = result.get("table", [])
    if not table:
        return f"🔍 <b>Head Comparison</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    header = f"🔍 <b>Head Comparison</b>\n\n{esc(result['summary'])}"

    if flagged_only:
        flagged = result.get("flagged_heads", [])
        if not flagged:
            return header + "\n\n✅ No heads flagged as statistical outliers.", None
        lines = [header, "", "🚩 <b>Flagged heads:</b>"]
        lines += [f"  • {esc(f)}" for f in flagged]
        return "\n".join(lines), None

    full_rows = [
        [
            r["head_id"],
            fmt_num(r.get("success_rate_pct"), suffix="%"),
            fmt_num(r.get("mean_torque_nm"), ".3f"),
            f"{int(r['total_closures']):,}",
        ]
        for r in table
    ]
    full_table = make_table(["Head", "Success%", "MeanTorque", "Total"], full_rows)

    if len(table) <= 8:
        return header + "\n\n" + pre(full_table), None

    if result.get("flagged_heads"):
        header += f"\n\n🚩 {len(result['flagged_heads'])} head(s) flagged:"
        header += "".join(f"\n  • {esc(f)}" for f in result["flagged_heads"][:5])
    kw = result.get("kruskal_wallis_torque_test")
    if kw:
        verdict = "significant" if kw["significant"] else "not significant"
        header += f"\n\nKruskal-Wallis (torque across heads): p={kw['p_value']:.4g} ({verdict})"
    header += f"\n\n📋 {len(table)} heads total -- tap below for the full table."
    return header, full_table


# ---------------------------------------------------------------------------
# Tool 7: failure_analysis
# ---------------------------------------------------------------------------


def fmt_failure_overall(result: dict[str, Any]) -> tuple[str, FullTable]:
    header = f"❌ <b>Failure Analysis</b>\n\n{esc(result['summary'])}"
    dist = result.get("failure_distribution_by_status_code", {})
    if not dist:
        return header, None

    ranked = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)
    lines = [header, "", "By status code:"]
    lines += [f"  {code}: {count:,}" for code, count in ranked]
    if result.get("daily_failure_rate_spikes"):
        lines.append(f"\n📅 {len(result['daily_failure_rate_spikes'])} day(s) with elevated failure rate.")
    return "\n".join(lines), None


def fmt_failure_bursts(result: dict[str, Any]) -> tuple[str, FullTable]:
    bursts = result.get("consecutive_failure_bursts", [])
    header = f"❌ <b>Consecutive Failure Bursts</b>\n\n{esc(result['summary'])}"
    if not bursts:
        return header + "\n\nNo bursts (>=3 consecutive failures) found.", None

    full_rows = [[b["head_id"], b["start_time"], f"{b['count']}"] for b in bursts]
    full_table = make_table(["Head", "Start", "Count"], full_rows)

    worst = sorted(bursts, key=lambda b: b["count"], reverse=True)[:5]
    lines = [header, "", "Longest bursts:"]
    for b in worst:
        lines.append(f"  {esc(b['head_id'])} @ {esc(b['start_time'])}: {b['count']} in a row (types {b['failure_types']})")
    if len(bursts) > 5:
        lines.append(f"\n📋 {len(bursts)} bursts total -- tap below for the full list.")
        return "\n".join(lines), full_table
    return "\n".join(lines), None


def fmt_failure_per_head(result: dict[str, Any]) -> tuple[str, FullTable]:
    dominant = result.get("per_head_dominant_failure", [])
    header = f"❌ <b>Per-Head Failure Profile</b>\n\n{esc(result['summary'])}"
    if not dominant:
        return header, None
    raw_text = "\n".join(dominant)
    if len(dominant) <= 10:
        return header + "\n\n" + pre(raw_text), None
    lines = [header, "", *[f"  {esc(d)}" for d in dominant[:10]], "", f"📋 {len(dominant)} heads total -- tap below for the rest."]
    return "\n".join(lines), raw_text


# ---------------------------------------------------------------------------
# Tool 8: capping_speed_analysis
# ---------------------------------------------------------------------------


def fmt_speed_summary(result: dict[str, Any]) -> tuple[str, FullTable]:
    mw = result.get("machine_wide_throughput_pph")
    if not mw:
        return f"🏭 <b>Production Speed</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    ph = result["per_head_average_speed_pph"]
    lines = [
        "🏭 <b>Capping Speed Analysis</b>",
        "",
        f"Machine-wide throughput: <b>{fmt_num(mw['mean'], '.0f')} pph</b> (range {fmt_num(mw['min'], '.0f')}-{fmt_num(mw['max'], '.0f')})",
        f"Per-head average: {fmt_num(ph['mean'], '.1f')} pph/head (not the machine's rate -- see /help)",
        f"Speed anomalies: {len(result.get('speed_anomalies', []))} hour(s) flagged",
    ]
    excluded = result.get("idle_affected_speed_samples_excluded", 0)
    if excluded:
        lines.append(f"Post-idle speed samples excluded: {excluded:,} (closures still counted)")
    if result.get("gap_affected_hours"):
        lines.append(f"\n⚠️ {len(result['gap_affected_hours'])} hour(s) include gap-backlogged closures and read artificially high.")
    return "\n".join(lines), None


def fmt_speed_over_time(result: dict[str, Any]) -> tuple[str, FullTable]:
    timeline = result.get("machine_wide_timeline", [])
    header = "🏭 <b>Speed Over Time (machine-wide, hourly)</b>\n\n" + esc(result.get("summary", ""))
    if not timeline:
        return header, None

    full_rows = [[t["hour"], fmt_num(t["pieces_per_hour"], ".0f"), "gap" if t["gap_affected"] else ""] for t in timeline]
    full_table = make_table(["Hour", "pph", "Flag"], full_rows, max_rows=500)

    anomalies = result.get("speed_anomalies", [])
    lines = [header, "", f"{len(timeline)} hourly data point(s)."]
    if anomalies:
        lines.append("\nNotable hours:")
        for a in anomalies[:6]:
            lines.append(f"  {esc(a['hour'])}: {fmt_num(a['pieces_per_hour'], '.0f')} pph ({a['type']})")
    lines.append("\n📋 Tap below for the full hourly table.")
    return "\n".join(lines), full_table


# ---------------------------------------------------------------------------
# Tool 9: idle_analysis
# ---------------------------------------------------------------------------


def fmt_idle_utilization(result: dict[str, Any]) -> tuple[str, FullTable]:
    if result.get("utilization_rate") != result.get("utilization_rate"):  # NaN
        return f"💤 <b>Idle & Utilization</b>\n\n{esc(result.get('summary', 'No data.'))}", None
    stats = result["idle_period_stats"]
    lines = [
        "💤 <b>Idle & Utilization</b>",
        "",
        f"Utilization rate: <b>{fmt_num(result['utilization_rate'] * 100, '.1f')}%</b>",
        f"Idle periods: {stats['count']:,}",
        f"Total idle time: {fmt_num(stats['total_idle_seconds'] / 3600, '.1f')}h",
        f"Median idle duration: {fmt_num(stats['median_duration_s'], '.0f')}s",
        f"Longest idle period: {fmt_num(stats['max_duration_s'] / 3600, '.1f')}h",
    ]
    return "\n".join(lines), None


def fmt_idle_periods(result: dict[str, Any]) -> tuple[str, FullTable]:
    longest = result.get("top_10_longest_idle_periods", [])
    header = "💤 <b>Idle Period Statistics</b>\n\n" + esc(result.get("summary", ""))
    if not longest:
        return header, None
    rows = [[p["start_time"], p["end_time"], fmt_num(p["duration_seconds"] / 3600, ".2f")] for p in longest]
    table = make_table(["Start", "End", "Hours"], rows)
    return header + "\n\n<b>10 longest idle periods:</b>\n" + pre(table), None


def fmt_idle_daily_pattern(result: dict[str, Any]) -> tuple[str, FullTable]:
    hourly = result.get("hourly_idle_pattern", {})
    header = "💤 <b>Daily Idle Pattern</b>\n\n" + esc(result.get("summary", ""))
    if not hourly:
        return header, None
    rows = [[f"{h:02d}:00", fmt_num(sec / 3600, ".2f")] for h, sec in sorted(hourly.items())]
    table = make_table(["Hour", "IdleHours"], rows)
    return header + "\n\n<b>Idle hours by hour-of-day:</b>\n" + pre(table), None


# ---------------------------------------------------------------------------
# Tool 11: list_events
# ---------------------------------------------------------------------------


def fmt_list_events(result: dict[str, Any]) -> tuple[str, FullTable]:
    header = f"📄 <b>Event List</b>\n\n{esc(result['summary'])}"
    rows = result.get("events", [])
    if not rows:
        return header, None

    full_rows = [[r["timestamp"], r["head_id"], r["status_label"], fmt_num(r["torque_nm"], ".3f")] for r in rows]
    full_table = make_table(["Timestamp", "Head", "Status", "TorqueNm"], full_rows)

    if len(rows) <= 10:
        return header + "\n\n" + pre(full_table), None

    lines = [header, "", "Most recent:"]
    for r in rows[:10]:
        lines.append(f"  {esc(r['timestamp'])} {esc(r['head_id'])} {esc(r['status_label'])} {fmt_num(r['torque_nm'], '.3f')} Nm")
    lines.append(f"\n📋 Showing {len(rows)} of {result['total_matching']:,} matching -- tap below for the full list.")
    return "\n".join(lines), full_table


# ---------------------------------------------------------------------------
# Tool 12: torque_outcome_comparison
# ---------------------------------------------------------------------------


def fmt_torque_outcome_comparison(result: dict[str, Any]) -> tuple[str, FullTable]:
    succ, fail = result.get("successful"), result.get("failed")
    if not succ or not fail:
        return f"🔧 <b>Torque: Successful vs Failed</b>\n\n{esc(result['summary'])}", None

    mw = result.get("mann_whitney_u_test") or {}
    lines = [
        "🔧 <b>Torque: Successful vs Failed</b>",
        "",
        f"✅ Successful (n={succ['count']:,}): mean {fmt_num(succ['mean'], '.3f')} Nm, std {fmt_num(succ['std'], '.3f')}, range {fmt_num(succ['min'], '.3f')}-{fmt_num(succ['max'], '.3f')}",
        f"❌ Failed (n={fail['count']:,}): mean {fmt_num(fail['mean'], '.3f')} Nm, std {fmt_num(fail['std'], '.3f')}, range {fmt_num(fail['min'], '.3f')}-{fmt_num(fail['max'], '.3f')}",
        "",
        f"Mann-Whitney U: p={fmt_num(mw.get('p_value'), '.4g')} ({'significant' if mw.get('significant') else 'not significant'})",
    ]
    return "\n".join(lines), None


# ---------------------------------------------------------------------------
# Tool 13: torque_success_correlation
# ---------------------------------------------------------------------------


def fmt_torque_success_correlation(result: dict[str, Any]) -> tuple[str, FullTable]:
    header = f"📐 <b>Torque ↔ Success Rate Correlation</b>\n\n{esc(result['summary'])}"
    table = result.get("table", [])
    if not table or result.get("pearson_r") is None:
        return header, None

    full_rows = [[r["head_id"], fmt_num(r["mean_torque_nm"], ".3f"), fmt_num(r["success_rate_pct"], suffix="%")] for r in table]
    full_table = make_table(["Head", "MeanTorque", "Success%"], full_rows)

    if len(table) <= 8:
        return header + "\n\n" + pre(full_table), None
    header += f"\n\n📋 {len(table)} heads total -- tap below for the per-head table."
    return header, full_table


# ---------------------------------------------------------------------------
# Tool 10: generate_kpi_dashboard
# ---------------------------------------------------------------------------


def fmt_kpi_dashboard(result: dict[str, Any]) -> tuple[str, FullTable]:
    kpis = result.get("kpis", {})
    if not kpis:
        return f"📊 <b>KPI Dashboard</b>\n\n{esc(result.get('summary', 'No data.'))}", None

    worst = kpis.get("worst_head")
    best = kpis.get("best_head")
    lines = [
        "📊 <b>KPI Dashboard</b>",
        "",
        f"✅ Success Rate: <b>{format_percentage(kpis['overall_success_rate_pct'])}</b> "
        f"({kpis.get('successful_status_observations', 0):,} successful / "
        f"{kpis.get('failed_status_observations', 0):,} failed)",
        f"🔧 Mean Torque: {fmt_num(kpis['mean_torque_nm'], '.3f')} Nm",
        f"🏭 Production Speed: {fmt_num(kpis['machine_wide_throughput_pph'], '.1f')} pph "
        f"({kpis.get('production_hours_with_closures', 0):,} production hours)",
        f"⏱️ Utilization: {fmt_num(kpis['utilization_rate_pct'], suffix='%')} "
        f"over {fmt_num(kpis.get('observation_window_hours'), '.1f')}h",
        f"⚠️ Anomalies: {kpis.get('n_anomalies', 0):,}",
        f"💤 Idle Time: {fmt_num(kpis['total_idle_hours'], '.1f')}h",
    ]
    if worst:
        lines.append(f"📉 Worst head: {esc(worst['head_id'])} ({format_percentage(worst['success_rate_pct'])})")
    if best:
        lines.append(f"📈 Best head: {esc(best['head_id'])} ({format_percentage(best['success_rate_pct'])})")
    return "\n".join(lines), None


# ---------------------------------------------------------------------------
# Mode 2: Layer-3 agent responses
# ---------------------------------------------------------------------------


def _markdown_lite_to_html(text: str) -> str:
    """The composer's multi-tool report is Markdown (## headers, **bold**);
    Telegram HTML mode can't render Markdown, so convert the small subset the
    composer actually emits (see agent/composer.py REPORT_PROMPT) into HTML,
    escaping everything else."""
    lines_out: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip("#").strip()
        heading_level = len(line) - len(line.lstrip("#"))
        escaped = esc(stripped if heading_level else line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        if heading_level:
            escaped = f"<b>{escaped}</b>"
        lines_out.append(escaped)
    return "\n".join(lines_out)


def fmt_agent_response(answer: str, used_llm: bool, execution_time: float, errors: list[str]) -> str:
    source = "🤖 LLM routing · deterministic answer" if used_llm else "🔑 keyword-fallback · deterministic answer"
    footer = f"\n\n<i>{source} · {execution_time:.1f}s</i>"
    if errors:
        footer += "\n" + "\n".join(f"⚠️ {esc(e)}" for e in errors)
    return _markdown_lite_to_html(answer) + footer


def fmt_tool_error(tool: str, error: str) -> str:
    return f"⚠️ Something went wrong running <b>{esc(tool)}</b>:\n{esc(error)}\n\nTry a different filter, or use /menu."
