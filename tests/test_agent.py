# Layer 3 (agent) tests. Run with: PYTHONPATH=src pytest tests/test_agent.py -v
#
# Every test here mocks the LLM (monkeypatching arol_analytics.agent.llm.chat /
# llm.is_ollama_available) -- no live Ollama server or network access is ever
# required to run this suite.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arol_analytics.agent import llm
from arol_analytics.agent.agent import AROLAgent
from arol_analytics.agent.composer import compose
from arol_analytics.agent.executor import ToolExecutor
from arol_analytics.agent.fallback import keyword_route
from arol_analytics.agent.router import route
from arol_analytics.agent.tools import normalize_enum_value

# ---------------------------------------------------------------------------
# Keyword fallback routing (no LLM involved at all)
# ---------------------------------------------------------------------------

KEYWORD_CASES = [
    ("How many closure events are in the dataset?", "dataset_summary"),
    ("What is the success rate per capping head?", "success_rate_analysis"),
    ("What percentage of capping operations were successful?", "success_rate_analysis"),
    ("What is the average closing torque for successful operations?", "torque_statistics"),
    ("Which head shows the highest torque variability?", "torque_statistics"),
    ("Did the average torque change over the observed time period?", "torque_trend_analysis"),
    ("Are there any anomalies in the data?", "anomaly_detection"),
    ("Compare performance between head H12 and head H29.", "head_comparison"),
    ("Which head contributes most to overall failures?", "failure_analysis"),
    ("What is the machine's production speed?", "capping_speed_analysis"),
    ("What is the machine's utilization rate?", "idle_analysis"),
    ("Generate a short report on capping quality for this dataset.", "generate_kpi_dashboard"),
    ("What preprocessing steps were applied to the raw data?", "meta_knowledge"),
    ("Plot the torque over time.", "visualize"),
]


class TestKeywordFallback:
    @pytest.mark.parametrize("query,expected_tool", KEYWORD_CASES)
    def test_keyword_route_matches_expected_tool(self, query: str, expected_tool: str) -> None:
        assert keyword_route(query) == expected_tool

    def test_at_least_ten_cases_covered(self) -> None:
        assert len(KEYWORD_CASES) >= 10

    def test_no_match_returns_none(self) -> None:
        assert keyword_route("asdkjhaskjdh completely unrelated gibberish") is None

    def test_route_falls_back_to_kpi_dashboard_when_nothing_matches(self) -> None:
        result = route("asdkjhaskjdh completely unrelated gibberish", use_llm=False)
        assert not result.used_llm
        assert result.tool_calls[0].tool == "generate_kpi_dashboard"


# ---------------------------------------------------------------------------
# Enum parameter normalization (router repairs close-but-inexact LLM output)
# ---------------------------------------------------------------------------

ENUM_NORMALIZATION_CASES = [
    ("success_rate_analysis", "group_by", "head", "per_head"),
    ("success_rate_analysis", "group_by", "per_head", "per_head"),
    ("torque_statistics", "filter_status", "success", "successful_only"),
    ("torque_statistics", "filter_status", "failed", "failed_only"),
    ("anomaly_detection", "method", "z-score", "zscore"),
    ("anomaly_detection", "method", "Z Score", "zscore"),
    ("success_rate_analysis", "group_by", "not_a_real_group", None),
    ("success_rate_analysis", "head_filter", ["H01"], ["H01"]),
]


class TestEnumNormalization:
    @pytest.mark.parametrize("tool,param,raw,expected", ENUM_NORMALIZATION_CASES)
    def test_normalize_enum_value(self, tool: str, param: str, raw, expected) -> None:
        value, ok = normalize_enum_value(tool, param, raw)
        if expected is None:
            assert not ok
        else:
            assert ok
            assert value == expected


# ---------------------------------------------------------------------------
# Tool execution against a mocked routing decision
# ---------------------------------------------------------------------------


class TestToolExecution:
    def test_known_routing_decision_executes_correctly(self, tmp_parquet_files: Path) -> None:
        executor = ToolExecutor(tmp_parquet_files)
        # keyword_route only ever picks a tool name, never parameters (see
        # fallback.py) -- it maps "success rate" to success_rate_analysis with
        # {} parameters, so this runs the tool's "overall" default grouping.
        route_result = route("What is the success rate per head?", use_llm=False)
        assert route_result.tool_calls[0].tool == "success_rate_analysis"
        assert route_result.tool_calls[0].parameters == {}

        results = executor.execute_all(route_result.tool_calls)
        assert len(results) == 1
        assert results[0].error is None
        assert results[0].result is not None
        # 200 total events: 115 successful, 85 failed (see synthetic_closure_events).
        assert results[0].result["table"][0]["success_rate_pct"] == pytest.approx(57.5)

    def test_llm_routed_tool_call_executes_correctly(self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_response = json.dumps(
            {
                "reasoning": "the user wants a per-head success rate breakdown",
                "tool_calls": [{"tool": "success_rate_analysis", "parameters": {"group_by": "per_head"}}],
            }
        )
        monkeypatch.setattr(llm, "chat", lambda messages, model=None, temperature=0.0: fake_response)

        route_result = route("What is the success rate per head?", use_llm=True)
        assert route_result.used_llm
        assert route_result.tool_calls == [route_result.tool_calls[0]]
        assert route_result.tool_calls[0].tool == "success_rate_analysis"
        assert route_result.tool_calls[0].parameters == {"group_by": "per_head"}

        executor = ToolExecutor(tmp_parquet_files)
        results = executor.execute_all(route_result.tool_calls)
        assert results[0].error is None

    def test_llm_enum_typo_is_normalized_before_execution(
        self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_response = json.dumps(
            {"reasoning": "group by head", "tool_calls": [{"tool": "success_rate_analysis", "parameters": {"group_by": "head"}}]}
        )
        monkeypatch.setattr(llm, "chat", lambda messages, model=None, temperature=0.0: fake_response)

        route_result = route("group success by head", use_llm=True)
        assert route_result.tool_calls[0].parameters["group_by"] == "per_head"

        executor = ToolExecutor(tmp_parquet_files)
        results = executor.execute_all(route_result.tool_calls)
        assert results[0].error is None  # would have raised ValueError with the un-normalized "head"

    def test_unknown_tool_returns_structured_error(self, tmp_parquet_files: Path) -> None:
        from arol_analytics.agent.router import ToolCall

        executor = ToolExecutor(tmp_parquet_files)
        result = executor.execute(ToolCall(tool="not_a_real_tool", parameters={}))
        assert result.error is not None
        assert result.result is None

    def test_tool_exception_does_not_crash_executor(self, tmp_parquet_files: Path) -> None:
        from arol_analytics.agent.router import ToolCall

        executor = ToolExecutor(tmp_parquet_files)
        # anomaly_detection requires threshold_range when method="threshold" -- omitting it raises ValueError inside the tool.
        result = executor.execute(ToolCall(tool="anomaly_detection", parameters={"method": "threshold"}))
        assert result.error is not None
        assert "threshold_range" in result.error


# ---------------------------------------------------------------------------
# Response structure (AgentResponse fields)
# ---------------------------------------------------------------------------


class TestResponseStructure:
    def test_agent_response_has_expected_fields_without_llm(
        self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm, "is_ollama_available", lambda: False)
        agent = AROLAgent(tmp_parquet_files)
        assert agent.llm_available is False

        response = agent.query("What is the overall success rate?")

        assert isinstance(response.answer, str) and response.answer
        assert isinstance(response.tool_calls, list) and response.tool_calls
        assert all({"tool", "parameters"} <= c.keys() for c in response.tool_calls)
        assert isinstance(response.raw_data, dict)
        assert response.execution_time >= 0
        assert response.used_llm is False
        assert isinstance(response.errors, list)

    def test_agent_response_with_mocked_llm(self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "is_ollama_available", lambda: True)
        fake_route = json.dumps({"reasoning": "overall success rate requested", "tool_calls": [{"tool": "success_rate_analysis", "parameters": {}}]})
        monkeypatch.setattr(llm, "chat", lambda messages, model=None, temperature=0.0: fake_route)

        agent = AROLAgent(tmp_parquet_files)
        assert agent.llm_available is True

        response = agent.query("What is the overall success rate?")
        assert response.used_llm is True
        assert "115 / (115 + 85)" in response.answer
        assert "57.50%" in response.answer
        assert response.tool_calls[0]["tool"] == "success_rate_analysis"

    def test_llm_cannot_rewrite_success_rate_denominator(self) -> None:
        from arol_analytics.agent.executor import ExecutionResult
        from arol_analytics.agent.router import ToolCall

        call = ToolCall(tool="success_rate_analysis", parameters={})
        result = ExecutionResult(
            tool="success_rate_analysis",
            parameters={},
            result={
                "summary": "success summary",
                "group_by": "overall",
                "table": [
                    {
                        "group": "overall",
                        "successful": 31_670_096,
                        "failed": 1_096,
                        "other_count": 12,
                        "evaluated_status_observations": 31_671_192,
                        "inferred_closures": 32_251_622,
                        "closures_without_individual_status": 580_418,
                        "success_rate_pct": 99.996539,
                    }
                ],
            },
            error=None,
            elapsed_s=0.1,
        )

        answer = compose("Qual è la percentuale di successo?", [call], [result], reasoning="", use_llm=True)

        assert "31,670,096 / (31,670,096 + 1,096)" in answer
        assert "31,670,096 / 31,671,192" in answer
        assert "32,251,622" not in answer
        assert "not automatically missing or corrupted data" in answer

    def test_meta_question_response_structure(self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "is_ollama_available", lambda: False)
        agent = AROLAgent(tmp_parquet_files)
        response = agent.query("What preprocessing steps were applied to the raw data?")
        assert isinstance(response.answer, str) and response.answer
        assert response.tool_calls[0]["tool"] == "meta_knowledge"
        assert response.raw_data == {}  # meta_knowledge is never executed as a Layer-2 tool call


# ---------------------------------------------------------------------------
# LLM unavailable -- graceful degradation
# ---------------------------------------------------------------------------


class TestLLMUnavailable:
    def test_agent_construction_does_not_raise_when_ollama_down(
        self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm, "is_ollama_available", lambda: False)
        agent = AROLAgent(tmp_parquet_files)
        assert agent.llm_available is False

    def test_connection_failure_during_chat_falls_back_to_keyword_routing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args, **kwargs):
            raise llm.OllamaUnavailableError("connection refused")

        monkeypatch.setattr(llm, "chat", _raise)
        result = route("What is the success rate per head?", use_llm=True)
        assert not result.used_llm
        assert result.tool_calls[0].tool == "success_rate_analysis"

    def test_full_pipeline_runs_end_to_end_without_llm(
        self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm, "is_ollama_available", lambda: False)
        agent = AROLAgent(tmp_parquet_files)

        queries = [
            "What is the overall success rate?",
            "Compare all heads.",
            "What is the machine's utilization rate?",
            "What preprocessing steps were applied to the raw data?",
        ]
        for q in queries:
            response = agent.query(q)
            assert isinstance(response.answer, str) and response.answer
            assert not response.errors or all(isinstance(e, str) for e in response.errors)

    def test_malformed_llm_json_falls_back_to_keyword_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "chat", lambda messages, model=None, temperature=0.0: "not valid json at all")
        result = route("What is the success rate per head?", use_llm=True)
        assert not result.used_llm
        assert result.tool_calls[0].tool == "success_rate_analysis"

    def test_compose_does_not_call_llm_for_numeric_answer(
        self, tmp_parquet_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arol_analytics.agent.router import ToolCall

        def _raise(*args, **kwargs):
            raise llm.OllamaUnavailableError("down")

        monkeypatch.setattr(llm, "chat", _raise)
        executor = ToolExecutor(tmp_parquet_files)
        call = ToolCall(tool="success_rate_analysis", parameters={})
        results = executor.execute_all([call])

        answer = compose("What is the success rate?", [call], results, reasoning="", use_llm=True)
        assert isinstance(answer, str) and answer
        assert "115 / (115 + 85)" in answer
        assert "57.50%" in answer
