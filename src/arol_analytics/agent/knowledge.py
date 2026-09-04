# Static knowledge base for meta/system questions ("what preprocessing was
# applied?", "what assumptions were made?"). Facts here are taken from
# docs/1layer_data_prep.md and docs/2layer_analytic_function.md -- keep them in
# sync if those documents change; do not invent numbers here.

from __future__ import annotations

META_KNOWLEDGE: dict[str, str] = {
    "preprocessing": (
        "89 daily CSV files (Feb-Apr 2026, ~4.6 GB total) covering 36 heads are read in chronological "
        "order. Each file is schema-validated (timestamp column + H{nn} Count/AppTorque/Status triplets); "
        "a malformed file is rejected without stopping the pipeline. Trailing all-zero rows are preserved "
        "until later files provide enough context to distinguish a true reset from corrupted reporting. "
        "Corrupted Count readings (sensor blips) are detected and masked before closures "
        "are counted. Closures are detected per head from Count increments, enriched with readable status "
        "labels and derived metrics, true duplicate closures are removed, and everything is written to "
        "closure_events.parquet + idle_periods.parquet."
    ),
    "closure_detection": (
        "A closure event is recorded when a head's Count value increases versus the previous valid row for "
        "that head (across file boundaries too, via carried-over state). A decrease is a counter reset, not "
        "a closure, and is excluded automatically. Since Count can jump by more than 1 in one step, each "
        "closure also records counter_delta (how much it rose), inferred_closure_count (how many closures "
        "to count -- currently always equal to counter_delta), and data_quality: 'single' (normal jump of "
        "1), 'aggregated' (jump >1 within a normal sampling interval), or 'gap' (the jump spans a detected "
        "sampling gap -- we know how many closures happened, not exactly when)."
    ),
    "corrupted_readings": (
        "Some heads show Count==0 for a short block mid-file while AppTorque keeps reading real, variable "
        "values (~2 Nm) -- proof production never stopped, only the counter briefly failed to report. These "
        "are distinguished from true counter resets by comparing the value just before the zero-block to "
        "the value just after: if it recovers near or above the prior value, it's a corrupted reading (Count "
        "is masked, AppTorque/Status are kept as real data); if it drops back near 0, it's a true reset (left "
        "untouched). Verified against all 2,088 zero-blocks in the archive with zero ambiguous cases."
    ),
    "duplicate_handling": (
        "Duplicate detection (same head, same counter value) is scoped to a single reset segment -- the span "
        "between one counter reset and the next for that head -- because a reset legitimately revisits "
        "counter values used before it, and those are real closures, not duplicates. After corrupted Count "
        "readings are cleaned before closure detection, this check now finds zero true duplicates across the "
        "archive (versus 551 in an earlier version of the pipeline, all traced to those same corrupted "
        "readings -- fixed at the source rather than cleaned up after)."
    ),
    "idle_detection": (
        "The machine is considered idle when all 36 heads simultaneously show status=2 (No Load) for at "
        "least 30 consecutive rows or 30 seconds (threshold from the spec). Sampling gaps split idle runs, "
        "because an interval without observations cannot be assumed to be idle. Runs spanning a file boundary "
        "are merged only when the timestamps remain continuous."
    ),
    "timestamps": (
        "Raw timestamps are naive US local time, not UTC despite the ISO-like format -- confirmed by a "
        "1-hour shift between the 2026-03-08 and 2026-03-09 files, exactly matching US DST start. Each "
        "'daily' file actually starts around 16:00-17:00 the previous day and ends 15:59:59/16:59:59 on the "
        "nominal date."
    ),
    "status_codes": (
        "13 status codes are documented in the machine's spec, but only 5 actually occur in this dataset: "
        "0 (Closure OK / success), 2 (No Load -- excluded from success-rate math), 4 (No Closure), "
        "9 (EarlyRaise, reject), and 65 (RotatingAtRaise, reject). No values outside the documented table "
        "were found, and no negative torque values were found."
    ),
    "torque_caveat": (
        "Torque is bimodal: near 0 Nm during no-load, ~2 Nm during real closures. Mixing both populations "
        "in one statistic is misleading, so torque_statistics defaults to successful closures only and "
        "warns explicitly if asked to include everything."
    ),
    "trend_caveat": (
        "On the full archive, torque_trend_analysis finds a 'statistically significant' increasing trend on "
        "every head, but r-squared is only ~0.0004 -- time explains about 0.04% of torque variance. With "
        "~900k events per head, statistical significance is easy to reach even when the real effect is "
        "negligible; the tool appends this caveat to its own summary automatically when r_squared < 0.01."
    ),
    "speed_caveat": (
        "capping_speed_analysis reports two different numbers on purpose: machine_wide_throughput_pph (true "
        "aggregate rate, summing all heads per hour, ~26,610 pph on the full archive) and "
        "per_head_average_speed_pph (mean of individual head speeds, ~1,521 pph -- about 17.5x smaller). An "
        "earlier version only reported the second number as generic 'production speed', which reads as "
        "machine throughput when it isn't. Peak real hours reach ~51,800-51,877 pph, consistent with typical "
        "36-head AROL capping-machine specs (50,000-72,000 pph depending on cap type)."
    ),
    "gap_hours_caveat": (
        "9 hours in the archive bundle closures backlogged by an unsampled data gap into the single hour "
        "where sampling resumed, reading as an inflated throughput (e.g. one hour showed 236,795 pph, ~4x "
        "the real peak, from the 2026-02-04 gap). The total closure count is still correct -- only that "
        "hour's rate is misleading. These hours are flagged (gap_affected: true) rather than dropped."
    ),
    "data_scope": (
        "36 heads (not up to 48 as the original spec allowed), 55,130,461 closure-event rows representing "
        "55,954,882 inferred closures (the difference is aggregated multi-closure jumps recovered from "
        "sampling gaps), 3,493 idle periods totaling ~1,418.35 hours (~66.4% of the archive, i.e. ~33.6% "
        "utilization), 108 true counter resets (recounted correctly across file boundaries in a 2026-08-22 "
        "ingestion fix -- an earlier version undercounted these at 36 by checking each file in isolation), "
        "96,518 corrupted Count readings cleaned before closure detection, 21 files with an internal "
        "sampling gap, no gap found exactly at a file boundary in the current pipeline version."
    ),
    "kpi_snapshot": (
        "Full-archive KPI dashboard snapshot: 99.9965% overall success rate (1,096 failures are a "
        "tiny fraction of the total), mean torque 2.014 Nm on successful closures, torque stability (std of "
        "per-head means) 0.001 Nm, machine-wide throughput 26,610 pph, utilization 33.63%, worst head H29 "
        "(99.99% success), best head H24 (100.00%), ~307,821 anomalies flagged by the z-score method (mostly "
        "the bimodal-torque effect, see torque_caveat), 1,418.35 idle hours total. This snapshot can go stale -- "
        "prefer generate_kpi_dashboard for current numbers."
    ),
}


TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "preprocessing": ("preprocessing", "clean", "pipeline", "ingest", "raw data"),
    "closure_detection": ("closure detection", "detect a closure", "detect closures", "classify a closure", "successful closure", "what features"),
    "corrupted_readings": ("corrupted", "sensor blip", "zero block", "zero-block"),
    "duplicate_handling": ("duplicate", "doppion", "removed"),
    "idle_detection": ("idle detection", "no load", "how is idle", "downtime detect"),
    "timestamps": ("timestamp", "timezone", "time zone", "dst", "daylight"),
    "status_codes": ("status code", "error code", "status codes"),
    "torque_caveat": ("torque bimodal", "torque caveat", "why does torque", "torque distribution shape"),
    "trend_caveat": ("trend caveat", "r-squared", "r2", "significant trend", "statistically significant"),
    "speed_caveat": ("speed caveat", "throughput caveat", "two numbers", "machine-wide vs per-head", "per head vs machine"),
    "gap_hours_caveat": ("gap", "sampling gap", "backlog", "inflated"),
    "data_scope": ("how many heads", "how much data", "data scope", "archive size", "how many events"),
}


def lookup(topic: str) -> str | None:
    return META_KNOWLEDGE.get(topic)


def pick_topics(query: str) -> list[str]:
    """Match a natural-language meta-question to relevant knowledge-base topics."""
    lowered = query.lower()
    matched = [topic for topic, keywords in TOPIC_KEYWORDS.items() if any(kw in lowered for kw in keywords)]
    return matched or ["preprocessing", "closure_detection", "duplicate_handling"]


def format_all() -> str:
    return "\n\n".join(f"### {k}\n{v}" for k, v in META_KNOWLEDGE.items())
