# Tool 10: generate_kpi_dashboard -- one call that compiles all key KPIs.

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration
from arol_analytics.analytics.anomaly import anomaly_detection
from arol_analytics.analytics.production import capping_speed_analysis, idle_analysis
from arol_analytics.analytics.summary import success_rate_analysis
from arol_analytics.analytics.torque import torque_statistics

logger = logging.getLogger(__name__)


def generate_kpi_dashboard(
    events: pd.DataFrame,
    idle_periods: pd.DataFrame,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """One-call overview: calls the other tools internally and compiles the
    key KPIs a report header needs.

    Returns a dict with `summary` (formatted multi-line report-header string)
    and `kpis`: overall_success_rate_pct, mean_torque_nm,
    torque_stability_std_across_heads, machine_wide_throughput_pph (true
    aggregate pieces/hour, summed across all heads -- NOT an average of
    per-head speeds, see capping_speed_analysis), per_head_average_speed_pph
    (kept alongside it for reference, but don't read it as "the machine's
    speed"), utilization_rate_pct, worst_head, best_head, n_anomalies,
    total_idle_hours.
    """
    events_f = filter_events(events, None, time_range)

    with log_duration("generate_kpi_dashboard"):
        overall_success = success_rate_analysis(events_f, group_by="overall")
        per_head_success = success_rate_analysis(events_f, group_by="per_head")
        overall_torque = torque_statistics(events_f, filter_status="successful_only", group_by="overall")
        per_head_torque = torque_statistics(events_f, filter_status="successful_only", group_by="per_head")
        speed = capping_speed_analysis(events_f, idle_periods=idle_periods)
        idle = idle_analysis(idle_periods, time_range=time_range)
        anomalies = anomaly_detection(events_f, method="zscore")

    overall_success_rate = overall_success["table"][0]["success_rate_pct"] if overall_success.get("table") else float("nan")
    mean_torque = overall_torque["table"][0]["mean"] if overall_torque.get("table") else float("nan")

    per_head_torque_table = per_head_torque.get("table", [])
    torque_std_across_heads = (
        pd.Series([r["mean"] for r in per_head_torque_table if r["mean"] is not None]).std(ddof=0)
        if per_head_torque_table
        else float("nan")
    )

    head_table = per_head_success.get("table", [])  # already sorted worst-to-best
    worst_head = {"head_id": head_table[0]["group"], "success_rate_pct": head_table[0]["success_rate_pct"]} if head_table else None
    best_head = {"head_id": head_table[-1]["group"], "success_rate_pct": head_table[-1]["success_rate_pct"]} if head_table else None

    utilization_pct = idle.get("utilization_rate")
    utilization_pct = utilization_pct * 100.0 if utilization_pct is not None and utilization_pct == utilization_pct else None

    kpis = {
        "overall_success_rate_pct": overall_success_rate,
        "mean_torque_nm": mean_torque,
        "torque_stability_std_across_heads": float(torque_std_across_heads) if torque_std_across_heads == torque_std_across_heads else None,
        "machine_wide_throughput_pph": speed.get("machine_wide_throughput_pph", {}).get("mean"),
        "per_head_average_speed_pph": speed.get("per_head_average_speed_pph", {}).get("mean"),
        "utilization_rate_pct": utilization_pct,
        "worst_head": worst_head,
        "best_head": best_head,
        "n_anomalies": anomalies.get("total_anomalies", 0),
        "total_idle_hours": idle.get("idle_period_stats", {}).get("total_idle_seconds", 0.0) / 3600.0,
    }

    summary = _format_summary(kpis)
    return {"summary": summary, "kpis": kpis}


def _fmt(value: Any, spec: str = ".2f", suffix: str = "") -> str:
    if value is None or value != value:  # None or NaN
        return "n/a"
    return f"{value:{spec}}{suffix}"


def _format_summary(kpis: dict[str, Any]) -> str:
    worst = kpis["worst_head"]
    best = kpis["best_head"]
    lines = [
        "=== AROL KPI Dashboard ===",
        f"Success rate: {_fmt(kpis['overall_success_rate_pct'], suffix='%')}",
        f"Mean torque (successful closures): {_fmt(kpis['mean_torque_nm'], '.3f', ' Nm')}",
        f"Torque stability (std of per-head means): {_fmt(kpis['torque_stability_std_across_heads'], '.3f', ' Nm')}",
        f"Machine-wide throughput: {_fmt(kpis['machine_wide_throughput_pph'], '.0f', ' pph')}",
        f"  (per-head average: {_fmt(kpis['per_head_average_speed_pph'], '.1f', ' pph/head')})",
        f"Utilization rate: {_fmt(kpis['utilization_rate_pct'], suffix='%')}",
        f"Worst-performing head: {worst['head_id']} ({_fmt(worst['success_rate_pct'], suffix='%')})" if worst else "Worst-performing head: n/a",
        f"Best-performing head: {best['head_id']} ({_fmt(best['success_rate_pct'], suffix='%')})" if best else "Best-performing head: n/a",
        f"Anomalies detected (z-score method): {kpis['n_anomalies']:,}",
        f"Total idle time: {_fmt(kpis['total_idle_hours'], '.1f', 'h')}",
    ]
    return "\n".join(lines)
