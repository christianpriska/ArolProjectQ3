# Response composer: turns raw tool output into a human-readable answer.
# Numerical answers are deterministic: the LLM routes the request, but never
# rewrites tool results or recomputes formulas. This keeps the natural-language
# interface without allowing a model to change a denominator or invent a KPI.

from __future__ import annotations

import logging

from arol_analytics.analytics._common import format_percentage
from arol_analytics.agent import knowledge, llm
from arol_analytics.agent.executor import ExecutionResult
from arol_analytics.agent.router import ToolCall

logger = logging.getLogger(__name__)

MAX_DISPLAY_GROUPS = 10


def _meta_answer(query: str, use_llm: bool, model: str | None) -> str:
    topics = knowledge.pick_topics(query)
    facts = "\n\n".join(f"{t}: {knowledge.lookup(t)}" for t in topics)
    if not use_llm:
        return facts

    prompt = (
        f'The user asked about how the system works: "{query}"\n\n'
        f"Relevant facts:\n{facts}\n\n"
        "Answer conversationally in English in under 150 words, using only the facts above. "
        "Always answer in English, regardless of the language used by the user."
    )
    try:
        return llm.chat([{"role": "user", "content": prompt}], model=model)
    except llm.OllamaUnavailableError:
        return facts


def _none_answer(reasoning: str) -> str:
    base = "I don't have a tool that can answer that question with the available data."
    return f"{base} {reasoning}" if reasoning else base


def _error_answer(results: list[ExecutionResult]) -> str:
    lines = ["The request could not be completed:"]
    for r in results:
        if r.error:
            lines.append(f"- {r.tool}({r.parameters}): {r.error}")
    return "\n".join(lines)


def _single_tool_answer(query: str, result: ExecutionResult, use_llm: bool, model: str | None) -> str:
    assert result.result is not None
    if result.tool == "success_rate_analysis":
        return _format_success_rate(result.result)
    return result.result.get("summary", "(no summary returned)")


def _format_success_rate(data: dict) -> str:
    """Render the success-rate formula from tool-owned fields only."""
    table = data.get("table", [])
    if not table:
        return data.get("summary", "No success-rate data available.")

    if data.get("group_by") != "overall":
        lines = [data.get("summary", "Success-rate analysis:"), ""]
        for row in table[:MAX_DISPLAY_GROUPS]:
            lines.append(
                f"- {row['group']}: {format_percentage(row['success_rate_pct'])} "
                f"({int(row['successful']):,} successful / {int(row['failed']):,} failed)"
            )
        if len(table) > MAX_DISPLAY_GROUPS:
            lines.append(f"- … {len(table) - MAX_DISPLAY_GROUPS} additional group(s) omitted")
        return "\n".join(lines)

    row = table[0]
    successful = int(row["successful"])
    failed = int(row["failed"])
    denominator = int(row["evaluated_status_observations"])
    other = int(row["other_count"])
    inferred_without_status = int(row["closures_without_individual_status"])
    return "\n".join(
        [
            "Success rate (overall)",
            "",
            f"- Successful observed outcomes: {successful:,}",
            f"- Failed observed outcomes: {failed:,}",
            f"- Other observed outcomes (excluded): {other:,}",
            f"- Success rate: {format_percentage(row['success_rate_pct'])}",
            "",
            "Formula:",
            f"{successful:,} / ({successful:,} + {failed:,}) = "
            f"{successful:,} / {denominator:,} = {format_percentage(row['success_rate_pct'])}",
            "",
            "No-load events are excluded from the denominator.",
            f"The {inferred_without_status:,} additional inferred closures come from counter jumps: "
            "they do not have an individually observed status and are not automatically missing or corrupted data.",
        ]
    )


def _multi_tool_answer(query: str, results: list[ExecutionResult], use_llm: bool, model: str | None) -> str:
    ok_results = [r for r in results if r.result is not None]
    lines = ["## Report", "", "### Analyses Executed"]
    for r in ok_results:
        lines.append(f"- **{r.tool}**({r.parameters}): {r.result.get('summary', '')}")
    errored = [r for r in results if r.error]
    if errored:
        lines += ["", "### Errors"]
        lines += [f"- {r.tool}: {r.error}" for r in errored]
    return "\n".join(lines)


def compose(
    query: str,
    tool_calls: list[ToolCall],
    exec_results: list[ExecutionResult],
    reasoning: str,
    use_llm: bool = True,
    model: str | None = None,
) -> str:
    """Produce the final human-readable answer for a query, given the tool
    call(s) the router chose and their execution results."""
    if len(tool_calls) == 1 and tool_calls[0].tool == "none":
        return _none_answer(reasoning)
    if len(tool_calls) == 1 and tool_calls[0].tool == "meta_knowledge":
        return _meta_answer(query, use_llm, model)

    successful = [r for r in exec_results if r.result is not None]
    if not successful:
        return _error_answer(exec_results)

    if len(successful) == 1 and len(exec_results) == 1:
        return _single_tool_answer(query, successful[0], use_llm, model)

    return _multi_tool_answer(query, exec_results, use_llm, model)
