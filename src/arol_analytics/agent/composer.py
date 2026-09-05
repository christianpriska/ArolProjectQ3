# Response composer: turns raw tool output into a human-readable answer.
#
# Two paths:
#  - Deterministic (always for a single non-explanatory tool result, and for any
#    result when no LLM is available): numbers come only from code-owned fields;
#    success rate has a dedicated formatter that prints its exact denominator.
#  - Grounded synthesis (LLM available, and the question is explanatory/
#    diagnostic or needed more than one tool): the LLM writes the prose answer
#    but is instructed to use only the numbers the tools returned -- it connects
#    and interprets results, it does not recompute formulas or invent figures.

from __future__ import annotations

import json
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


# Question intents that need a synthesized explanation rather than a raw stat
# dump: "why is X", "explain X", "what should be monitored", "summarize the
# issues". Kept deliberately broad -- a false positive just routes a normal
# question through the (still grounded) LLM write-up instead of the template.
_EXPLANATORY_MARKERS: tuple[str, ...] = (
    "why", "explain", "reason", "because", "cause", "causing", "root cause",
    "diagnos", "what is driving", "what's driving", "account for", "attributable",
    "monitored more", "monitor more closely", "should be monitored", "what should i watch",
    "what to watch", "recommend", "summarize", "summarise", "main issues", "key issues",
)


def _wants_explanation(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _EXPLANATORY_MARKERS)


def _fmt_params(params: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in params.items()) if params else ""


def _compact_result(result: dict) -> dict:
    """Trim a tool result for the synthesis prompt: drop raw image bytes and cap
    long tables so the context stays small without losing the headline numbers."""
    compact: dict = {}
    for key, value in result.items():
        if key == "images":
            continue
        if isinstance(value, list) and len(value) > 20:
            compact[key] = value[:20] + [f"... ({len(value) - 20} more rows omitted)"]
        else:
            compact[key] = value
    return compact


def _synthesized_answer(query: str, results: list[ExecutionResult], model: str | None) -> str | None:
    """LLM-written answer grounded strictly in the tool results. Returns None if
    the LLM is unreachable, so the caller can fall back to a deterministic path."""
    ok_results = [r for r in results if r.result is not None]
    errored = [r for r in results if r.error]
    if not ok_results:
        return None

    blocks = []
    for r in ok_results:
        payload = json.dumps(_compact_result(r.result), default=str)
        if len(payload) > 6000:
            payload = payload[:6000] + " ...(truncated)"
        blocks.append(
            f"### {r.tool}({_fmt_params(r.parameters)})\n"
            f"summary: {r.result.get('summary', '(no summary)')}\n"
            f"data: {payload}"
        )
    context = "\n\n".join(blocks)

    prompt = (
        f'The user asked: "{query}"\n\n'
        f"You ran {len(ok_results)} analysis tool(s) on the capping-machine dataset and got these "
        f"results:\n\n{context}\n\n"
        "Write a direct, concise answer to the user's question (under 200 words), based ONLY on the "
        "numbers in these results. Do not compute, estimate, or introduce any figure that is not "
        "present above. Quote the specific numbers that support each statement. If the results show "
        "THAT something happens but not WHY, say so plainly and name the further analysis that would "
        "be needed -- do not invent a cause. Answer in English."
    )
    try:
        answer = llm.chat([{"role": "user", "content": prompt}], model=model).strip()
    except llm.OllamaUnavailableError:
        return None

    if errored:
        answer += "\n\n(Note: " + "; ".join(f"{r.tool} failed: {r.error}" for r in errored) + ")"
    return answer


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

    single = len(successful) == 1 and len(exec_results) == 1

    # Grounded synthesis for explanatory/diagnostic questions and any multi-tool
    # request, when an LLM is available. Numbers still come only from the tool
    # results; the model connects and interprets them. Falls through to the
    # deterministic path if the LLM turns out to be unreachable.
    if use_llm and (not single or _wants_explanation(query)):
        synthesized = _synthesized_answer(query, exec_results, model)
        if synthesized is not None:
            return synthesized

    if single:
        return _single_tool_answer(query, successful[0], use_llm, model)

    return _multi_tool_answer(query, exec_results, use_llm, model)
