# CLI entry point: python -m arol_analytics.analytics data/processed/ --output reports/

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from arol_analytics.analytics._common import effective_time_range, to_jsonable
from arol_analytics.analytics.anomaly import anomaly_detection
from arol_analytics.analytics.dashboard import generate_kpi_dashboard
from arol_analytics.analytics.heads import failure_analysis, head_comparison
from arol_analytics.analytics.io import load_closure_events, load_idle_periods
from arol_analytics.analytics.production import capping_speed_analysis, idle_analysis
from arol_analytics.analytics.summary import dataset_summary
from arol_analytics.analytics.torque import torque_trend_analysis

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AROL Layer-2 analytics on Layer-1 ingested data.")
    parser.add_argument("data_dir", help="Directory containing closure_events.parquet and idle_periods.parquet.")
    parser.add_argument("--output", default="reports", help="Directory to write the analytics report (default: reports).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    data_dir = Path(args.data_dir)
    events = load_closure_events(data_dir)
    idle_periods = load_idle_periods(data_dir)
    quality_report = _load_quality_report(data_dir)

    dashboard = generate_kpi_dashboard(events, idle_periods)
    print(dashboard["summary"])

    logger.info("running full analytics suite...")
    results = {
        "dataset_summary": dataset_summary(events, quality_report=quality_report),
        "dashboard": dashboard,
        "head_comparison": head_comparison(events),
        "failure_analysis": failure_analysis(events),
        "torque_trend": torque_trend_analysis(events),
        "anomalies": anomaly_detection(events, method="zscore"),
        "capping_speed": capping_speed_analysis(events, idle_periods=idle_periods),
        "idle_analysis": idle_analysis(idle_periods, time_range=effective_time_range(events)),
    }

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_md = _build_markdown_report(results)
    (output_dir / "analytics_report.md").write_text(report_md)

    with open(output_dir / "analytics_report.json", "w") as f:
        json.dump(to_jsonable(results), f, indent=2)

    print(f"\nFull report written to {output_dir / 'analytics_report.md'} (+ .json)")
    return 0


def _load_quality_report(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "data_quality_report.json" if data_dir.is_dir() else None
    if path and path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _build_markdown_report(results: dict[str, Any]) -> str:
    lines = ["# AROL Analytics Report (Layer 2)", ""]

    lines += ["## Dataset Summary", "", results["dataset_summary"]["summary"], ""]

    lines += ["## KPI Dashboard", "", "```", results["dashboard"]["summary"], "```", ""]

    lines += ["## Head Comparison", "", results["head_comparison"]["summary"], ""]
    table = results["head_comparison"].get("table", [])
    if table:
        cols = ["head_id", "total_closures", "successful", "failed", "success_rate_pct", "mean_torque_nm", "std_torque_nm"]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * len(cols))
        for row in table:
            lines.append("| " + " | ".join(_fmt_cell(row.get(c)) for c in cols) + " |")
        lines.append("")
    flagged = results["head_comparison"].get("flagged_heads", [])
    if flagged:
        lines.append("**Flagged heads:**")
        lines += [f"- {f}" for f in flagged]
        lines.append("")

    lines += ["## Failure Analysis", "", results["failure_analysis"]["summary"], ""]
    dominant = results["failure_analysis"].get("per_head_dominant_failure", [])
    if dominant:
        lines.append("**Per-head dominant failure type:**")
        lines += [f"- {d}" for d in dominant]
        lines.append("")
    bursts = results["failure_analysis"].get("consecutive_failure_bursts", [])
    if bursts:
        lines.append(f"**Consecutive failure bursts** ({len(bursts)}):")
        for b in bursts[:20]:
            lines.append(f"- {b['head_id']}: {b['count']} in a row, {b['start_time']} -> {b['end_time']} (types {b['failure_types']})")
        lines.append("")

    lines += ["## Torque Trend", "", results["torque_trend"]["summary"], ""]
    per_head_trend = results["torque_trend"].get("per_head_trend", {})
    if per_head_trend:
        lines.append("| head | slope (Nm/day) | direction | significant | p-value |")
        lines.append("|---|---|---|---|---|")
        for h, t in sorted(per_head_trend.items()):
            lines.append(f"| {h} | {t['slope_nm_per_day']:.5f} | {t['direction']} | {t['significant']} | {t['p_value']:.4g} |")
        lines.append("")

    lines += ["## Anomalies (z-score method)", "", results["anomalies"]["summary"], ""]

    lines += ["## Capping Speed", "", results["capping_speed"]["summary"], ""]
    gap_hours = results["capping_speed"].get("gap_affected_hours", [])
    if gap_hours:
        lines.append("**Gap-affected hours (throughput reads inflated, do not use for peak-rate claims):**")
        for g in gap_hours:
            lines.append(f"- {g['hour']}: {g['pieces_per_hour']:.0f} pph -- {g['reason']}")
        lines.append("")

    lines += ["## Idle Analysis", "", results["idle_analysis"]["summary"], ""]
    longest = results["idle_analysis"].get("top_10_longest_idle_periods", [])
    if longest:
        lines.append("**Top longest idle periods:**")
        for p in longest:
            lines.append(f"- {p['start_time']} -> {p['end_time']} ({p['duration_seconds'] / 3600:.2f}h)")
        lines.append("")

    return "\n".join(lines)


def _fmt_cell(value: Any) -> str:
    if value is None or value != value:  # None or NaN
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
