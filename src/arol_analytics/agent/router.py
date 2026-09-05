# Query router: decides which Layer-2 tool(s) a natural-language question maps
# to. Tries the LLM first (with one stricter retry on a malformed response),
# then falls back to keyword matching so the agent always produces a result.

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from arol_analytics.agent import llm
from arol_analytics.agent.fallback import keyword_route
from arol_analytics.agent.tools import TOOL_NAMES, format_registry_for_prompt, normalize_enum_value

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an AI assistant that analyzes industrial capping machine telemetry data.
You have access to the following analysis tools:

{tools}

Also available:
- meta_knowledge: for questions about how the system itself works (preprocessing, data cleaning, \
assumptions, how success/failure is classified) rather than questions about the data's values.
- none: if the question cannot be answered with any of the above.

Given a user question, decide which tool(s) to call and with what parameters.
Understand questions in any language, but always write the reasoning field in English.
Respond ONLY with a JSON object, no other text, in this exact format:
{{
    "reasoning": "brief explanation of why you chose this tool",
    "tool_calls": [
        {{"tool": "tool_name", "parameters": {{}}}}
    ]
}}

If the question requires multiple tools, list them in order in tool_calls.
Only include parameters the user actually specified or implied; omit the rest so the tool's defaults apply.
For a question that asks WHY something happens, or to EXPLAIN, DIAGNOSE, or RECOMMEND what to monitor, \
pick the set of tools whose combined output is the evidence for an answer -- usually two or three, e.g. a \
breakdown over time or per head plus failure_analysis and/or anomaly_detection -- so the explanation can \
be grounded in real numbers rather than a single aggregate.
Resolve any named or relative time period in the question ("in March", "the selected month", "the first \
week of data") into an explicit [start, end] pair of ISO date strings in the time_range parameter, using \
the dataset's own date range below; the end is exclusive.
If you cannot answer the question with the available tools, respond with tool_calls containing a single \
entry: {{"tool": "none", "parameters": {{}}}}, and explain why in reasoning.{data_range}"""

STRICT_RETRY_SUFFIX = (
    "\n\nYour previous reply was not valid JSON matching the required format. "
    "Reply with ONLY the JSON object -- no markdown fences, no commentary, no extra text before or after it."
)


@dataclass
class ToolCall:
    tool: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteResult:
    reasoning: str
    tool_calls: list[ToolCall]
    used_llm: bool
    raw_llm_output: str | None = None


def _build_system_prompt(data_range: tuple[str, str] | None = None) -> str:
    range_note = ""
    if data_range:
        range_note = f"\n\nThe dataset covers {data_range[0]} to {data_range[1]} (local time)."
    return SYSTEM_PROMPT_TEMPLATE.format(tools=format_registry_for_prompt(), data_range=range_note)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from LLM output that may
    include markdown fences or stray text around the JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


_HEAD_REF_RE = re.compile(r"^\s*(?:head\s*)?h?[\s\-_]?(\d{1,2})\s*$", re.IGNORECASE)


def _normalize_head_ref(value: Any) -> Any:
    """Map a loose head reference ("3", "head 3", "h3", "H3") to the canonical
    "H03" form the Layer-2 tools expect. Leaves anything unrecognized alone."""
    if not isinstance(value, str):
        return value
    match = _HEAD_REF_RE.match(value)
    return f"H{int(match.group(1)):02d}" if match else value


def _normalize_head_param(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_head_ref(value)
    if isinstance(value, list):
        return [_normalize_head_ref(v) for v in value]
    return value


def _normalize_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Coerce router-supplied parameters onto what the tool expects: enum values
    onto the declared enum (e.g. group_by="head" -> "per_head"), and loose head
    references onto the canonical "H03" form. Enum values that don't match
    anything are dropped so the tool's own default applies instead of raising."""
    normalized: dict[str, Any] = {}
    for pname, pvalue in params.items():
        if pname in {"head_filter", "heads"} and pvalue is not None:
            fixed = _normalize_head_param(pvalue)
            if fixed != pvalue:
                logger.info("router: normalized %s.%s: %r -> %r", tool_name, pname, pvalue, fixed)
            normalized[pname] = fixed
            continue
        value, ok = normalize_enum_value(tool_name, pname, pvalue)
        if not ok:
            logger.warning("router: dropping %s.%s=%r -- no matching enum value", tool_name, pname, pvalue)
            continue
        if value != pvalue:
            logger.info("router: normalized %s.%s: %r -> %r", tool_name, pname, pvalue, value)
        normalized[pname] = value
    return normalized


def _validate(parsed: dict[str, Any]) -> RouteResult | None:
    if not isinstance(parsed, dict) or "tool_calls" not in parsed:
        return None
    raw_calls = parsed.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        return None

    calls: list[ToolCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict) or "tool" not in raw:
            return None
        name = raw["tool"]
        if name not in TOOL_NAMES and name not in {"meta_knowledge", "none"}:
            logger.warning("router: LLM named unknown tool %r, dropping call", name)
            continue
        params = raw.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        calls.append(ToolCall(tool=name, parameters=_normalize_params(name, params)))

    if not calls:
        return None
    return RouteResult(reasoning=str(parsed.get("reasoning", "")), tool_calls=calls, used_llm=True)


def _route_via_llm(query: str, model: str | None, data_range: tuple[str, str] | None) -> RouteResult | None:
    system_prompt = _build_system_prompt(data_range)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]

    for attempt in range(2):
        try:
            raw = llm.chat(messages, model=model)
        except llm.OllamaUnavailableError as exc:
            logger.warning("router: Ollama call failed: %s", exc)
            return None

        parsed = _extract_json(raw)
        if parsed is not None:
            result = _validate(parsed)
            if result is not None:
                result.raw_llm_output = raw
                return result

        logger.info("router: could not parse LLM response as a valid tool call (attempt %d)", attempt + 1)
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": STRICT_RETRY_SUFFIX})

    return None


def route(
    query: str,
    use_llm: bool = True,
    model: str | None = None,
    data_range: tuple[str, str] | None = None,
) -> RouteResult:
    """Decide which tool(s) to call for `query`. Falls back to keyword
    matching if the LLM is unavailable or its output can't be parsed.
    `data_range` (dataset start/end, ISO strings) is given to the LLM so it can
    resolve named time periods like "in March" into an explicit time_range."""
    if use_llm:
        result = _route_via_llm(query, model, data_range)
        if result is not None:
            return result
        logger.info("router: falling back to keyword routing for query: %r", query)

    tool_name = keyword_route(query) or "generate_kpi_dashboard"
    return RouteResult(
        reasoning=f"keyword fallback matched tool={tool_name!r}",
        tool_calls=[ToolCall(tool=tool_name, parameters={})],
        used_llm=False,
    )
