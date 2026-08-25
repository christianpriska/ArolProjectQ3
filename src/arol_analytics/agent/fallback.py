# Keyword-based router: used when the LLM is unavailable or its response
# can't be parsed into a valid tool call. Keeps the agent answering even if
# Ollama is down or the local model misbehaves.

from __future__ import annotations

# Ordered: first matching entry wins, so more specific phrases go first.
KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("preprocessing", "duplicate", "assumption", "how were", "how do you", "what features", "how is a successful closure"), "meta_knowledge"),
    (("plot", "chart", "histogram", "visualize", "visualise", "graph of", "graph the"), "visualize"),
    (("successful vs failed", "successful versus failed", "torque of successful and failed", "successful and failed closures", "successful and failed torque"), "torque_outcome_comparison"),
    (("torque correlate", "does higher torque", "torque and success rate", "success rate correlate"), "torque_success_correlation"),
    (("list all", "show all", "torque above", "torque below", "torque threshold"), "list_events"),
    (("dashboard", "kpi", "overview", "how is the machine", "main issues", "short report", "summarize"), "generate_kpi_dashboard"),
    (("idle", "downtime", "utilization", "inactive", "shift"), "idle_analysis"),
    (("speed", "throughput", "pieces per hour", "pph", "production rate"), "capping_speed_analysis"),
    (("burst", "consecutive fail", "contributes most", "dominant failure"), "failure_analysis"),
    (("compare", "comparison", "vs head", "behaves differently", "differ", "closes the most", "produces the most", "most closures", "highest production", "busiest"), "head_comparison"),
    (("anomaly", "anomalies", "outlier", "unusual", "abnormal"), "anomaly_detection"),
    (("trend", "drift", "change over time", "moving average", "over the observed"), "torque_trend_analysis"),
    (("torque", "coppia"), "torque_statistics"),
    (("failure", "failures", "failed", "reject", "error"), "failure_analysis"),
    (("success rate", "successful", "positive outcome", "success/failure"), "success_rate_analysis"),
    (("time range", "how many", "overview", "dataset", "summary"), "dataset_summary"),
]


def keyword_route(query: str) -> str | None:
    """Return the best-matching tool name for `query`, or None if nothing matches."""
    lowered = query.lower()
    for keywords, tool_name in KEYWORD_MAP:
        if any(kw in lowered for kw in keywords):
            return tool_name
    return None
