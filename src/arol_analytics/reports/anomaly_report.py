# Anomaly & failure report: anomaly detection + failure breakdown, bursts,
# and monitoring recommendations.

from __future__ import annotations

import pandas as pd

from arol_analytics.analytics._common import format_percentage
from arol_analytics.analytics.anomaly import anomaly_detection
from arol_analytics.analytics.heads import failure_analysis, head_comparison
from arol_analytics.ingestion.schema import STATUS_LABELS
from arol_analytics.reports._common import dataset_period, fmt, generated_on

TOP_N_ANOMALY_HEADS = 10


def render_anomaly_report(events: pd.DataFrame) -> str:
    """Render the anomaly & failure report -- built live from
    anomaly_detection(), failure_analysis(), and head_comparison()'s flagged
    heads, not from a pre-computed snapshot."""
    anomalies = anomaly_detection(events, method="zscore")
    failures = failure_analysis(events)
    comparison = head_comparison(events)

    lines: list[str] = []
    lines.append("# AROL Capping Machine — Anomaly & Failure Report")
    lines.append("")
    lines.append(f"**Period**: {dataset_period(events)}")
    lines.append(f"**Generated**: {generated_on()}")
    lines.append(
        '**Source**: `anomaly_detection(method="zscore")` + `failure_analysis()`, run live against '
        "the ingested dataset."
    )
    lines.append("")

    lines.append("## Anomaly Detection (z-score method)")
    lines.append("")
    lines.append(anomalies["summary"])
    lines.append("")
    lines.append(
        "> **Read this alongside the failure counts below, not as a proxy for them.** Z-score anomaly "
        "detection flags torque readings far from each head's own successful-closure mean/std -- on a "
        "large archive this includes a large volume of legitimate distribution-tail readings, not "
        "mechanical faults. See `docs/analytics_methods.md` (tool 5) for the caveat."
    )
    lines.append("")
    per_head = anomalies.get("anomaly_count_per_head", {})
    if per_head:
        lines.append(f"**Anomaly counts per head (top {TOP_N_ANOMALY_HEADS}):**")
        lines.append("")
        lines.append("| Head | Anomalies |")
        lines.append("|---|---|")
        top = sorted(per_head.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N_ANOMALY_HEADS]
        for h, c in top:
            lines.append(f"| {h} | {c:,} |")
        lines.append("")
    windows = anomalies.get("elevated_failure_rate_windows", [])
    lines.append(f"**Elevated failure-rate windows (hourly)**: {len(windows)} hour(s) flagged.")
    if windows:
        lines.append("")
        lines.append("| Hour | Failure Rate | Events |")
        lines.append("|---|---|---|")
        for w in windows:
            lines.append(f"| {w['hour_start']} | {fmt(w['failure_rate'] * 100, '.2f', '%')} | {w['n_events']:,} |")
    lines.append("")

    lines.append("## Failure Analysis")
    lines.append("")
    lines.append(failures["summary"])
    lines.append("")
    distribution = failures.get("failure_distribution_by_status_code", {})
    if distribution:
        lines.append("**Failure breakdown by status code:**")
        lines.append("")
        lines.append("| Status Code | Label | Count |")
        lines.append("|---|---|---|")
        for code, count in sorted(distribution.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {code} | {STATUS_LABELS.get(int(code), 'n/a')} | {count:,} |")
        lines.append("")

    lines.append("**Daily failure-rate spikes:**")
    lines.append("")
    spikes = failures.get("daily_failure_rate_spikes", [])
    if spikes:
        lines.append("| Date | Failure Rate | Failures |")
        lines.append("|---|---|---|")
        for s in spikes:
            lines.append(f"| {s['date']} | {fmt(s['failure_rate_pct'], '.4f', '%')} | {s['n_failures']} |")
    else:
        lines.append("_None detected._")
    lines.append("")

    dominant = failures.get("per_head_dominant_failure", [])
    if dominant:
        lines.append("**Per-head dominant failure type** (heads with at least one failure):")
        lines.append("")
        for d in dominant:
            lines.append(f"- {d}")
        lines.append("")

    lines.append("**Consecutive failure bursts** (>=3 in a row, same head):")
    lines.append("")
    bursts = failures.get("consecutive_failure_bursts", [])
    if bursts:
        lines.append("| Head | Start | End | Count | Failure Types |")
        lines.append("|---|---|---|---|---|")
        for b in bursts:
            lines.append(f"| {b['head_id']} | {b['start_time']} | {b['end_time']} | {b['count']} | {b['failure_types']} |")
    else:
        lines.append("_None detected._")
    lines.append("")

    lines.append("## Heads With Unusual Patterns")
    lines.append("")
    lines.append("Cross-referencing `head_comparison`'s flagged outliers (>2σ from the group average):")
    lines.append("")
    flagged = comparison.get("flagged_heads", [])
    if flagged:
        for f in flagged:
            lines.append(f"- {f}")
    else:
        lines.append("_No heads flagged as statistical outliers._")
    lines.append("")
    if per_head:
        top_anomaly_head = max(per_head.items(), key=lambda kv: kv[1])
        lines.append(
            f"- **{top_anomaly_head[0]}** shows the most z-score torque anomalies "
            f"({top_anomaly_head[1]:,} events) -- this tracks each head's own torque spread, not "
            "necessarily a defect (see caveat above)."
        )
        lines.append("")

    lines.append("## Monitoring Recommendations")
    lines.append("")
    lines.append(
        f"- Treat z-score anomaly counts ({anomalies['total_anomalies']:,}) as a torque-variability "
        "signal, not a failure count -- track true failures (`failure_analysis`, reject status codes) "
        "as the primary quality KPI."
    )
    if bursts:
        lines.append(
            f"- Investigate **{bursts[0]['head_id']}** for the recorded consecutive-failure burst(s) -- "
            "worth a maintenance log check even if isolated so far."
        )
    lines.append(
        '- Re-run `anomaly_detection(method="iqr")` periodically alongside the default z-score method -- '
        "IQR is more robust to a handful of extreme outliers and can catch cases z-score's "
        "self-referential baseline might under-flag."
    )
    if spikes or windows:
        lines.append(
            "- The elevated failure-rate hours/days above are worth cross-checking against maintenance "
            "or changeover logs for that period, since they concentrate a disproportionate share of the "
            "archive's already-rare failures."
        )
    lines.append("")

    return "\n".join(lines)
