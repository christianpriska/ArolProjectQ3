# Layer 3 entry point: ties router -> executor -> composer together.
# Works with or without Ollama running -- see llm.is_ollama_available().

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arol_analytics.agent import composer, llm, router
from arol_analytics.agent.executor import ExecutionResult, ToolExecutor
from arol_analytics.agent.router import ToolCall

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    answer: str
    tool_calls: list[dict[str, Any]]
    raw_data: dict[str, Any]
    execution_time: float
    used_llm: bool
    reasoning: str = ""
    errors: list[str] = field(default_factory=list)


class AROLAgent:
    """Natural-language interface over the Layer-2 analytics tools.

    Loads closure_events/idle_periods once at construction. Ollama performs
    natural-language routing when available; numerical answers are always
    rendered deterministically from Layer-2 output. If Ollama isn't reachable,
    keyword routing keeps the same deterministic answer path available.
    """

    def __init__(self, data_path: str | Path, model: str | None = None):
        self.model = model or llm.DEFAULT_MODEL
        self.executor = ToolExecutor(data_path)
        self.llm_available = llm.is_ollama_available()
        if not self.llm_available:
            if llm.OLLAMA_API_KEY:
                hint = f"check OLLAMA_API_KEY and that {self.model!r} is a valid model on ollama.com/models"
            else:
                hint = (
                    f"start it with `ollama serve` (and `ollama pull {self.model}`), or set OLLAMA_API_KEY "
                    "to use Ollama Cloud instead -- no local install needed"
                )
            logger.warning(
                "Ollama not reachable at %s (model=%r) -- falling back to keyword routing and "
                "template responses. %s.",
                llm.OLLAMA_HOST,
                self.model,
                hint,
            )

    def query(self, user_message: str) -> AgentResponse:
        start = time.monotonic()

        route_result = router.route(user_message, use_llm=self.llm_available, model=self.model)

        executable_calls: list[ToolCall] = [
            c for c in route_result.tool_calls if c.tool not in {"meta_knowledge", "none"}
        ]
        exec_results: list[ExecutionResult] = self.executor.execute_all(executable_calls)

        answer = composer.compose(
            query=user_message,
            tool_calls=route_result.tool_calls,
            exec_results=exec_results,
            reasoning=route_result.reasoning,
            use_llm=self.llm_available,
            model=self.model,
        )

        raw_data = {r.tool: (r.result if r.result is not None else {"error": r.error}) for r in exec_results}
        errors = [f"{r.tool}: {r.error}" for r in exec_results if r.error]

        return AgentResponse(
            answer=answer,
            tool_calls=[{"tool": c.tool, "parameters": c.parameters} for c in route_result.tool_calls],
            raw_data=raw_data,
            execution_time=time.monotonic() - start,
            used_llm=route_result.used_llm,
            reasoning=route_result.reasoning,
            errors=errors,
        )
