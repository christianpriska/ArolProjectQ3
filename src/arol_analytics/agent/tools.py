# Tool registry: describes every Layer-2 analytics function in a format the
# router LLM (and the keyword fallback) can reason about. Parameter names and
# defaults here must match the real Layer-2 signatures in
# arol_analytics.analytics -- see executor.py for the name -> function mapping.

from __future__ import annotations

import re
from typing import Any

TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "dataset_summary",
        "description": (
            "Overview of the whole dataset: total closure events, number of heads, time range covered, "
            "status breakdown (successful/failed/no-load/other), overall success rate, and data-quality "
            "flags from ingestion. No filters -- always covers the full dataset."
        ),
        "parameters": {},
        "examples": [
            "How many closure events are in the dataset?",
            "What time range does the data cover?",
            "Show me a dataset overview.",
            "How many heads does the machine have?",
        ],
    },
    {
        "name": "success_rate_analysis",
        "description": (
            "Success rate (successful / (successful + failed), no-load excluded) with flexible grouping. "
            "Flags groups whose success rate is more than 2 standard deviations below the average."
        ),
        "parameters": {
            "group_by": {
                "type": "string",
                "enum": ["overall", "per_head", "daily", "hourly", "per_file"],
                "default": "overall",
                "description": "How to bucket the success rate.",
            },
            "head_filter": {
                "type": "list[string] | null",
                "description": "Optional list of head IDs to restrict to, e.g. ['H01', 'H05']. Omit for all heads.",
            },
            "time_range": {
                "type": "[string, string] | null",
                "description": "Optional [start, end] ISO date/datetime strings to restrict the time window.",
            },
        },
        "examples": [
            "What percentage of capping operations were successful?",
            "What is the success rate per capping head?",
            "Which head shows the lowest success rate?",
            "How did the capping success rate evolve over time?",
            "Show a daily breakdown of successful vs failed closures.",
            "How many closures ended with a positive outcome?",
        ],
    },
    {
        "name": "torque_statistics",
        "description": (
            "Torque distribution statistics (count, mean, median, std, min, max, quartiles, IQR-outlier "
            "count, coefficient of variation) with filtering and grouping. Defaults to successful closures "
            "only -- torque is bimodal (near-0 during no-load) so mixing populations is misleading."
        ),
        "parameters": {
            "filter_status": {
                "type": "string",
                "enum": ["successful_only", "failed_only", "all_real", "all"],
                "default": "successful_only",
                "description": "Which closures to include. 'all' mixes no-load and is noisy -- avoid unless asked explicitly.",
            },
            "group_by": {
                "type": "string",
                "enum": ["overall", "per_head", "daily"],
                "default": "overall",
            },
            "head_filter": {"type": "list[string] | null", "description": "Optional head ID list."},
            "time_range": {"type": "[string, string] | null", "description": "Optional [start, end] window."},
        },
        "examples": [
            "What is the average closing torque for successful capping operations?",
            "Show the torque distribution for all successful closures.",
            "Which head shows the highest torque variability?",
            "Are there any missing or invalid torque values?",
        ],
    },
    {
        "name": "torque_trend_analysis",
        "description": (
            "Detects drift/trends in torque over time, per head: moving average, linear-regression slope "
            "(Nm/day) with significance, and changepoints. Always uses successful closures."
        ),
        "parameters": {
            "head_filter": {"type": "list[string] | null", "description": "Optional head ID list."},
            "window_size": {
                "type": "int | string",
                "default": 1000,
                "description": "Rolling window: an int (number of events) or a pandas offset string like '7D'.",
            },
            "time_range": {"type": "[string, string] | null", "description": "Optional [start, end] window."},
        },
        "examples": [
            "Did the average torque change over the observed time period?",
            "Is the torque drifting on any head?",
            "Show the torque trend for head H12.",
        ],
    },
    {
        "name": "anomaly_detection",
        "description": (
            "Flags anomalous closures by torque (z-score, IQR, or a fixed threshold range), plus hours with "
            "an elevated failure rate. Evaluated against real (non-idle) closures."
        ),
        "parameters": {
            "method": {
                "type": "string",
                "enum": ["zscore", "iqr", "threshold"],
                "default": "zscore",
            },
            "threshold_range": {
                "type": "[number, number] | null",
                "description": "Required only when method='threshold', e.g. [0.5, 4.0] Nm.",
            },
            "sensitivity": {"type": "number", "default": 3.0, "description": "Only used by method='zscore'."},
            "head_filter": {"type": "list[string] | null"},
            "time_range": {"type": "[string, string] | null"},
        },
        "examples": [
            "Are there specific time intervals with abnormal failure rates?",
            "Are there torque values outside the expected operating range of 0.5 to 4.0 Nm?",
            "Show me anomalous closures.",
            "Which events look unusual?",
        ],
    },
    {
        "name": "head_comparison",
        "description": (
            "Compares all heads (or a chosen subset) side by side: success rate, torque mean/std, total "
            "closures, plus a Kruskal-Wallis test on torque across heads and outlier flags."
        ),
        "parameters": {
            "heads": {"type": "list[string] | null", "description": "Optional list of heads to compare, e.g. ['H12', 'H29']. Omit for all heads."},
            "time_range": {"type": "[string, string] | null"},
        },
        "examples": [
            "Compare performance between head H12 and head H29.",
            "Which capping head behaves differently from the others?",
            "Compare all heads.",
        ],
    },
    {
        "name": "failure_analysis",
        "description": (
            "Deep-dive into failures: distribution by status code, daily failure-rate spikes, each head's "
            "dominant failure type, consecutive failure bursts (>=3 in a row), and cross-head failure correlation."
        ),
        "parameters": {
            "head_filter": {"type": "list[string] | null"},
            "time_range": {"type": "[string, string] | null"},
        },
        "examples": [
            "Which head contributes most to overall failures?",
            "Is there a head with an unusual number of failed closures?",
            "How many failed capping operations were recorded?",
            "List all failed capping events for head H29.",
        ],
    },
    {
        "name": "capping_speed_analysis",
        "description": (
            "Production speed in pieces/hour, reported two ways: machine_wide_throughput_pph (true "
            "aggregate rate of the whole machine) and per_head_average_speed_pph (average of individual "
            "head speeds -- NOT the machine's rate, useful only for head-to-head comparison)."
        ),
        "parameters": {
            "head_filter": {"type": "list[string] | null"},
            "time_range": {"type": "[string, string] | null"},
            "exclude_idle": {"type": "boolean", "default": True},
        },
        "examples": [
            "What is the machine's production speed?",
            "How many pieces per hour does the machine make?",
            "Is any head slower than the others?",
        ],
    },
    {
        "name": "idle_analysis",
        "description": (
            "Analyzes machine idle periods (all heads simultaneously no-load): utilization rate, idle "
            "period duration stats, idle time by hour-of-day, and the 10 longest idle periods."
        ),
        "parameters": {
            "time_range": {"type": "[string, string] | null"},
        },
        "examples": [
            "What is the machine's utilization rate?",
            "How much downtime did the machine have?",
            "Show the longest idle periods.",
            "When during the day is the machine most often idle?",
        ],
    },
    {
        "name": "generate_kpi_dashboard",
        "description": (
            "One-call overview compiling the key KPIs: success rate, mean torque, torque stability, "
            "machine-wide throughput, utilization rate, worst/best head, anomaly count, idle hours. "
            "Good default for broad 'how is the machine doing' questions."
        ),
        "parameters": {
            "time_range": {"type": "[string, string] | null"},
        },
        "examples": [
            "How is the machine doing overall?",
            "Generate a dashboard summary of capping performance.",
            "Give me a KPI report.",
            "Summarize the main issues observed in the capping process.",
        ],
    },
]

TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOL_REGISTRY)


def format_registry_for_prompt() -> str:
    """Render the registry as text for the router's system prompt."""
    lines = []
    for tool in TOOL_REGISTRY:
        lines.append(f"- {tool['name']}: {tool['description']}")
        if tool["parameters"]:
            for pname, pspec in tool["parameters"].items():
                extra = f" (default: {pspec['default']!r})" if "default" in pspec else ""
                lines.append(f"    - {pname}: {pspec.get('description', pspec.get('type', ''))}{extra}")
        else:
            lines.append("    (no parameters)")
    return "\n".join(lines)


def get_tool(name: str) -> dict[str, Any] | None:
    for tool in TOOL_REGISTRY:
        if tool["name"] == name:
            return tool
    return None


def normalize_enum_value(tool_name: str, param_name: str, value: Any) -> tuple[Any, bool]:
    """Coerce a router-supplied value onto the parameter's declared enum, if any.

    LLMs reliably get the *concept* right (e.g. "group by head") but don't always
    reproduce the exact enum string (e.g. "head" instead of "per_head"). Returns
    (value, True) unchanged if there's no enum to check or the value is already
    valid; (normalized_value, True) on a confident case-insensitive/substring
    match; (None, False) if nothing matches -- the caller should drop the
    parameter and let the tool's own default apply rather than pass it through.
    """
    tool = get_tool(tool_name)
    if tool is None:
        return value, True
    pspec = tool["parameters"].get(param_name)
    if pspec is None or "enum" not in pspec:
        return value, True
    enum_values: list[str] = pspec["enum"]
    if value in enum_values:
        return value, True
    if not isinstance(value, str):
        return None, False

    # strip separators entirely so "z-score"/"z score"/"z_score" all compare equal to "zscore"
    strip_seps = lambda s: re.sub(r"[\s\-_]+", "", s.lower())  # noqa: E731
    normalized = strip_seps(value)
    for candidate in enum_values:
        if strip_seps(candidate) == normalized:
            return candidate, True

    substring_matches = [c for c in enum_values if normalized in strip_seps(c) or strip_seps(c) in normalized]
    if len(substring_matches) == 1:
        return substring_matches[0], True
    if substring_matches:
        return min(substring_matches, key=lambda c: abs(len(strip_seps(c)) - len(normalized))), True

    return None, False
