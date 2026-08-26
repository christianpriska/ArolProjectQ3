"""Build the human-readable ingestion summary (data_quality_report.json feeds straight
from quality.aggregate_quality; this module only builds the Markdown summary)."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_ingestion_summary(
    file_reports: list[dict[str, Any]],
    schema_errors: list[dict[str, str]],
    closure_events: pd.DataFrame,
    idle_periods: pd.DataFrame,
    dup_counts: dict[str, int],
    quality_report: dict[str, Any],
) -> str:
    lines: list[str] = ["# AROL Telemetry Ingestion Summary", ""]

    lines.append("## Files processed")
    lines.append("")
    lines.append(f"- Files found: {len(file_reports) + len(schema_errors)}")
    lines.append(f"- Files ingested successfully: {len(file_reports)}")
    lines.append(f"- Files rejected (schema errors): {len(schema_errors)}")
    if schema_errors:
        for e in schema_errors:
            lines.append(f"  - `{e['file']}`: {e['error']}")
    total_rows = sum(r["rows"] for r in file_reports)
    lines.append(f"- Total raw rows ingested: {total_rows:,}")
    if quality_report.get("time_range"):
        lines.append(
            f"- Time range: {quality_report['time_range']['first_timestamp']} -> "
            f"{quality_report['time_range']['last_timestamp']}"
        )
    lines.append("")

    lines.append("## Closures detected per head")
    lines.append("")
    lines.append(
        "_\"Observed events\" is the number of closure_events entries; \"Inferred closures\" sums "
        "inferred_closure_count, so it also counts closures inferred from a counter jump "
        "by a counter jump >1 (see data_quality below) -- use this for production totals._"
    )
    lines.append("")
    per_head_rows = quality_report.get("closure_rows_per_head", {})
    per_head_inferred = quality_report.get("inferred_closures_per_head", {})
    if per_head_rows:
        lines.append("| Head | Observed events | Inferred closures |")
        lines.append("|------|-----------------|-------------------|")
        for h in sorted(per_head_rows):
            lines.append(f"| {h} | {per_head_rows[h]:,} | {int(per_head_inferred[h]):,} |")
    else:
        lines.append("_No closures detected._")
    lines.append("")

    lines.append("## Overall closure outcome rates")
    lines.append("")
    lines.append(
        "_Each row contributes one observed status, including aggregated/gap rows. "
        "The additional closures inferred from a jump do not duplicate that status._"
    )
    lines.append("")
    counts = quality_report.get("classification_breakdown", {})
    total = sum(counts.values())
    if total:
        lines.append("| Outcome | Count | % |")
        lines.append("|---------|-------|---|")
        for label in ("successful", "failed", "no_load", "other"):
            n = int(counts.get(label, 0))
            lines.append(f"| {label} | {n:,} | {100.0 * n / total:.3f}% |")
        lines.append(f"| **Total** | {total:,} | 100% |")
    lines.append("")

    lines.append("## Closure data quality breakdown")
    lines.append("")
    breakdown = quality_report.get("data_quality_breakdown", {})
    total_events = sum(breakdown.values())
    if total_events:
        lines.append("| Quality | Count | % | Meaning |")
        lines.append("|---------|-------|---|---------|")
        meanings = {
            "single": "one closure, normal ~1s sampling interval",
            "aggregated": "counter jumped by >1 within a normal interval",
            "gap": "transition spans a detected sampling gap -- timestamp/torque/status are for the last closure in the jump only",
        }
        for label in ("single", "aggregated", "gap"):
            n = breakdown.get(label, 0)
            lines.append(f"| {label} | {n:,} | {100.0 * n / total_events:.3f}% | {meanings[label]} |")
    lines.append("")

    lines.append("## Data quality warnings")
    lines.append("")
    lines.append(f"- Counter resets (backward jumps) total: {quality_report.get('counter_resets_total', 0):,}")
    lines.append(f"- Negative torque readings: {quality_report.get('negative_torque_total', 0):,}")
    lines.append(f"- Torque outliers (>3sigma from per-head mean): {quality_report.get('torque_outliers_total', 0):,}")
    lines.append(
        f"- Trailing all-zero rows preserved for cross-file classification: "
        f"{quality_report.get('trailing_all_zero_rows_preserved_total', 0):,}"
    )
    lines.append(
        f"- Corrupted Count readings masked (per-head, based on pre/post-run value comparison): "
        f"{quality_report.get('corrupted_rows_masked_total', 0):,}"
    )
    unexpected = quality_report.get("unexpected_status_codes", {})
    if unexpected:
        lines.append(f"- **Unexpected status codes found (not in the documented table)**: {unexpected}")
    else:
        lines.append("- No status codes outside the documented table were found.")
    n_gap_files = len(quality_report.get("files_with_gaps", []))
    lines.append(f"- Files with sampling gaps (> 2x median interval): {n_gap_files}")
    boundary_gaps = quality_report.get("boundary_gaps", [])
    if boundary_gaps:
        lines.append(f"- **Sampling gaps at file boundaries (missed by per-file checks alone)**: {len(boundary_gaps)}")
        for g in boundary_gaps:
            lines.append(f"  - {g['prev_file']} -> {g['next_file']}: {g['gap_seconds']:.1f}s")
    else:
        lines.append("- No sampling gaps found at file boundaries.")
    total_dups = sum(dup_counts.values())
    if total_dups:
        lines.append(f"- Duplicate (head, counter) events removed: {total_dups} — {dup_counts}")
    else:
        lines.append("- No duplicate closure events found.")
    lines.append("")

    lines.append("## Idle periods")
    lines.append("")
    if len(idle_periods):
        total_idle_h = idle_periods["duration_seconds"].sum() / 3600.0
        lines.append(f"- Idle periods detected: {len(idle_periods)}")
        lines.append(f"- Total idle time: {total_idle_h:.2f} hours")
        longest = idle_periods.loc[idle_periods["duration_seconds"].idxmax()]
        lines.append(
            f"- Longest idle period: {longest['duration_seconds'] / 3600.0:.2f}h "
            f"({longest['start_time']} -> {longest['end_time']})"
        )
    else:
        lines.append("_No idle periods detected._")
    lines.append("")

    return "\n".join(lines)
