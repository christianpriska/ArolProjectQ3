# Static registry shared by the terminal chat interface: the guided-menu
# tree (Mode 1, direct Layer-2 tool calls -- no LLM) and the free-text
# fallback into the Layer-3 agent (Mode 2). See keyboards.py for the
# callback_data convention this drives.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from arol_analytics.agent.tools import TOOL_REGISTRY
from arol_analytics.bot import formatters, keyboards
from arol_analytics.bot.formatters import FullTable

HELP_TEXT = """ℹ️ <b>AROL Analytics -- Help</b>

<b>Guided mode</b> (no AI needed): use /menu and tap through the categories --
KPI dashboard, success rate, torque, anomalies, head comparison, failures,
production speed, idle time, dataset info, visualizations.

<b>Free question mode</b>: just type a question in plain English, e.g.
  • "What is the average torque?"
  • "Compare head H01 and H29"
  • "Why does H29 have more failures?"
  • "What preprocessing was applied to the raw data?"
An AI agent (or a keyword-based fallback if the AI backend is unavailable)
picks the right analysis and answers. Not sure what to ask? Try /examples.

<b>Commands</b>
/start, /menu -- main menu
/kpi -- quick KPI dashboard
/heads -- quick head comparison overview
/ask &lt;question&gt; -- free-form question
/examples -- example questions you can ask
/status -- system status
/help -- this message"""


def _build_examples_text() -> str:
    """Surfaces the example questions already declared per-tool in
    agent/tools.py (used to build the LLM router's prompt) so a user can
    discover what's answerable without reading the source."""
    lines = ["🤖 <b>Example questions you can ask</b> (free question mode)", ""]
    for tool in TOOL_REGISTRY:
        title = tool["name"].replace("_", " ").title().replace("Kpi", "KPI")
        lines.append(f"<b>{formatters.esc(title)}</b>")
        lines += [f"  • {formatters.esc(ex)}" for ex in tool["examples"][:3]]
        lines.append("")
    lines.append("Your own wording is fine -- these are just a starting point.")
    return "\n".join(lines)


EXAMPLES_TEXT = _build_examples_text()


@dataclass(frozen=True)
class RunAction:
    tool: str
    params: dict[str, Any]
    formatter: Callable[[dict[str, Any]], tuple[str, FullTable]] | None
    menu_target: str
    is_chart: bool = False


MENUS: dict[str, tuple[str, Callable[[], Any]]] = {
    "main": ("🏠 <b>AROL Analytics -- Main Menu</b>\n\nPick a category, or just type a question.", keyboards.main_menu),
    "success": ("✅ <b>Success Rate Analysis</b>", keyboards.success_menu),
    "torque": ("🔧 <b>Torque Analysis</b>", keyboards.torque_menu),
    "anomaly": ("⚠️ <b>Anomaly Detection</b>", keyboards.anomaly_menu),
    "cmp": ("🔍 <b>Head Comparison</b>", keyboards.head_cmp_menu),
    "failure": ("❌ <b>Failure Analysis</b>", keyboards.failure_menu),
    "speed": ("🏭 <b>Production &amp; Speed</b>", keyboards.speed_menu),
    "idle": ("💤 <b>Idle &amp; Utilization</b>", keyboards.idle_menu),
    "info": ("📋 <b>Dataset Info</b>", keyboards.info_menu),
    "viz": ("📈 <b>Visualizations</b>", keyboards.viz_menu),
    "help": (HELP_TEXT, keyboards.simple_back),
}

RUN_ACTIONS: dict[str, RunAction] = {
    "kpi:main": RunAction("generate_kpi_dashboard", {}, formatters.fmt_kpi_dashboard, "m:main"),
    "success:overall": RunAction("success_rate_analysis", {"group_by": "overall"}, formatters.fmt_success_rate, "m:success"),
    "success:per_head": RunAction("success_rate_analysis", {"group_by": "per_head"}, formatters.fmt_success_rate, "m:success"),
    "success:daily": RunAction("success_rate_analysis", {"group_by": "daily"}, formatters.fmt_success_rate, "m:success"),
    "torque:stats": RunAction(
        "torque_statistics", {"filter_status": "successful_only", "group_by": "overall"}, formatters.fmt_torque_statistics, "m:torque"
    ),
    "torque:dist": RunAction(
        "torque_statistics", {"filter_status": "all_real", "group_by": "overall"}, formatters.fmt_torque_statistics, "m:torque"
    ),
    "torque:trend": RunAction("torque_trend_analysis", {}, formatters.fmt_torque_trend, "m:torque"),
    "torque:outcome": RunAction("torque_outcome_comparison", {}, formatters.fmt_torque_outcome_comparison, "m:torque"),
    "anomaly:zscore": RunAction("anomaly_detection", {"method": "zscore"}, formatters.fmt_anomaly_detail, "m:anomaly"),
    "anomaly:iqr": RunAction("anomaly_detection", {"method": "iqr"}, formatters.fmt_anomaly_detail, "m:anomaly"),
    "anomaly:summary": RunAction("anomaly_detection", {"method": "zscore"}, formatters.fmt_anomaly_summary, "m:anomaly"),
    "cmp:all": RunAction("head_comparison", {}, lambda r: formatters.fmt_head_comparison(r, flagged_only=False), "m:cmp"),
    "cmp:flagged": RunAction("head_comparison", {}, lambda r: formatters.fmt_head_comparison(r, flagged_only=True), "m:cmp"),
    "cmp:correlation": RunAction("torque_success_correlation", {}, formatters.fmt_torque_success_correlation, "m:cmp"),
    "failure:overall": RunAction("failure_analysis", {}, formatters.fmt_failure_overall, "m:failure"),
    "failure:bursts": RunAction("failure_analysis", {}, formatters.fmt_failure_bursts, "m:failure"),
    "failure:perhead": RunAction("failure_analysis", {}, formatters.fmt_failure_per_head, "m:failure"),
    "failure:list": RunAction("list_events", {"outcome": "failed"}, formatters.fmt_list_events, "m:failure"),
    "speed:summary": RunAction("capping_speed_analysis", {}, formatters.fmt_speed_summary, "m:speed"),
    "speed:overtime": RunAction("capping_speed_analysis", {}, formatters.fmt_speed_over_time, "m:speed"),
    "idle:util": RunAction("idle_analysis", {}, formatters.fmt_idle_utilization, "m:idle"),
    "idle:periods": RunAction("idle_analysis", {}, formatters.fmt_idle_periods, "m:idle"),
    "idle:daily": RunAction("idle_analysis", {}, formatters.fmt_idle_daily_pattern, "m:idle"),
    "info:summary": RunAction("dataset_summary", {}, formatters.fmt_dataset_summary, "m:info"),
    "info:quality": RunAction("dataset_summary", {}, formatters.fmt_data_quality, "m:info"),
    "viz:torque_over_time": RunAction("visualize", {"chart_type": "torque_over_time"}, None, "m:viz", is_chart=True),
    "viz:torque_histogram": RunAction("visualize", {"chart_type": "torque_histogram"}, None, "m:viz", is_chart=True),
    "viz:success_rate_per_head": RunAction("visualize", {"chart_type": "success_rate_per_head"}, None, "m:viz", is_chart=True),
    "viz:failures_over_time": RunAction("visualize", {"chart_type": "failures_over_time"}, None, "m:viz", is_chart=True),
    "viz:production_over_time": RunAction("visualize", {"chart_type": "production_over_time"}, None, "m:viz", is_chart=True),
    "viz:utilization": RunAction("visualize", {"chart_type": "utilization"}, None, "m:viz", is_chart=True),
    "viz:kpi_dashboard": RunAction("visualize", {"chart_type": "kpi_dashboard"}, None, "m:viz", is_chart=True),
}

# Custom (head/time) flows, keyed by the flow name used in c:<flow>:head / h:<flow>:.. / t:<flow>:..
FLOW_ACTIONS: dict[str, RunAction] = {
    "success": RunAction("success_rate_analysis", {"group_by": "per_head"}, formatters.fmt_success_rate, "m:success"),
    "torque": RunAction(
        "torque_statistics", {"filter_status": "successful_only", "group_by": "per_head"}, formatters.fmt_torque_statistics, "m:torque"
    ),
    "failure": RunAction("failure_analysis", {}, formatters.fmt_failure_overall, "m:failure"),
}
