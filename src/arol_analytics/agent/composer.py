# Response composer: turns raw tool output into a human-readable answer.
# Works with or without the LLM -- without it, the tool's own `summary` field
# (every Layer-2 tool always returns one) is used directly as a template
# response, so the agent never goes silent just because Ollama is down.

from __future__ import annotations

import logging
from typing import Any

from arol_analytics.agent import knowledge, llm
from arol_analytics.agent.executor import ExecutionResult
from arol_analytics.agent.router import ToolCall

logger = logging.getLogger(__name__)

MAX_TABLE_ROWS_FOR_LLM = 10
SINGLE_TOOL_PROMPT = """The user asked: "{query}"

The analysis tool "{tool}" returned this data:
{data}

Write a clear, concise answer for a technical user. Include the key numbers.
If there are notable findings (outliers, anomalies, trends, caveats/warnings), highlight them.
Keep it under 200 words. Do not invent numbers that aren't in the data above."""

REPORT_PROMPT = """The user asked: "{query}"

The following analyses were run, in order, and returned this data:
{data}

Write a structured report in this exact Markdown format:

## Report: {{goal}}
### Data Used
{{what data was queried -- time range, head filters, if any}}
### Analyses Executed
{{which tools were called, in what order, and why}}
### Findings
{{key results, with numbers}}
### Confidence & Limits
{{caveats, sample size, statistical notes -- carry over any warnings from the data above}}
### Recommended Next Steps
{{what to investigate further}}

Do not invent numbers that aren't in the data above."""


def _trim(value: Any, max_rows: int = MAX_TABLE_ROWS_FOR_LLM) -> Any:
    """Shrink a tool result for the LLM prompt: keep summary/scalars, truncate long lists."""
    if isinstance(value, list):
        if len(value) > max_rows:
            return value[:max_rows] + [f"... ({len(value) - max_rows} more rows omitted)"]
        return value
    if isinstance(value, dict):
        return {k: _trim(v, max_rows) for k, v in value.items()}
    return value


def _format_result_for_llm(result: dict[str, Any]) -> str:
    trimmed = _trim(result)
    lines = []
    for key, value in trimmed.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _meta_answer(query: str, use_llm: bool, model: str | None) -> str:
    topics = knowledge.pick_topics(query)
    facts = "\n\n".join(f"{t}: {knowledge.lookup(t)}" for t in topics)
    if not use_llm:
        return facts

    prompt = (
        f'The user asked about how the system works: "{query}"\n\n'
        f"Relevant facts:\n{facts}\n\n"
        "Answer conversationally in under 150 words, using only the facts above."
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
    if not use_llm:
        return result.result.get("summary", "(no summary returned)")

    prompt = SINGLE_TOOL_PROMPT.format(query=query, tool=result.tool, data=_format_result_for_llm(result.result))
    try:
        return llm.chat([{"role": "user", "content": prompt}], model=model)
    except llm.OllamaUnavailableError:
        return result.result.get("summary", "(no summary returned)")


def _multi_tool_answer(query: str, results: list[ExecutionResult], use_llm: bool, model: str | None) -> str:
    ok_results = [r for r in results if r.result is not None]
    if not use_llm:
        lines = ["## Report", "", "### Analyses Executed"]
        for r in ok_results:
            lines.append(f"- **{r.tool}**({r.parameters}): {r.result.get('summary', '')}")
        errored = [r for r in results if r.error]
        if errored:
            lines += ["", "### Errors"]
            lines += [f"- {r.tool}: {r.error}" for r in errored]
        return "\n".join(lines)

    data = "\n\n".join(f"[{r.tool}]\n{_format_result_for_llm(r.result)}" for r in ok_results)
    prompt = REPORT_PROMPT.format(query=query, data=data)
    try:
        return llm.chat([{"role": "user", "content": prompt}], model=model)
    except llm.OllamaUnavailableError:
        return _multi_tool_answer(query, results, use_llm=False, model=model)


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
