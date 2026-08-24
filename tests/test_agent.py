# Smoke test for src/arol_analytics/agent (Layer 3).
# Run as: PYTHONPATH=src python tests/test_agent.py
# (or plain `python tests/test_agent.py` -- it adds src/ to sys.path itself)
#
# Three things are checked:
# 1. Keyword fallback picks a sensible tool for >=10 example queries (no data needed).
# 2. The full router -> executor -> composer pipeline runs end to end with the LLM
#    forced off (graceful degradation) -- this must always pass, Ollama or not.
# 3. If an Ollama server is actually reachable, the full LLM-backed pipeline is
#    exercised on a handful of validation queries from the project spec.

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import pandas as pd  # noqa: E402

from arol_analytics.agent import llm  # noqa: E402
from arol_analytics.agent.agent import AROLAgent  # noqa: E402
from arol_analytics.agent.composer import compose  # noqa: E402
from arol_analytics.agent.executor import ToolExecutor  # noqa: E402
from arol_analytics.agent.fallback import keyword_route  # noqa: E402
from arol_analytics.agent.router import route  # noqa: E402
from arol_analytics.agent.tools import normalize_enum_value  # noqa: E402

CLOSURE_EVENTS_PATH = REPO_ROOT / "data" / "processed" / "closure_events.parquet"
IDLE_PERIODS_PATH = REPO_ROOT / "data" / "processed" / "idle_periods.parquet"
SAMPLE_SIZE = 100_000

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
]

VALIDATION_QUERIES = [
    "How many capping operations were performed?",
    "What is the success rate per capping head?",
    "What is the average closing torque for successful operations?",
    "Which head shows the highest torque variability?",
    "Are there specific time intervals with abnormal failure rates?",
    "Explain why head H29 has more failed closures.",
    "Generate a short report on capping quality for this dataset.",
    "What preprocessing steps were applied to the raw data?",
]


def load_sample(path: Path, n: int = SAMPLE_SIZE) -> pd.DataFrame:
    """Read only the first ~n rows of a Parquet file without loading the whole file."""
    pf = pq.ParquetFile(path)
    batches = []
    got = 0
    for batch in pf.iter_batches(batch_size=n):
        batches.append(batch)
        got += batch.num_rows
        if got >= n:
            break
    table = pa.Table.from_batches(batches)
    return table.to_pandas().head(n)


def make_sample_data_dir(tmp_dir: Path) -> Path:
    """Write a small closure_events.parquet + idle_periods.parquet sample into tmp_dir
    so the agent's ToolExecutor (which reads a whole directory) stays fast in tests."""
    events = load_sample(CLOSURE_EVENTS_PATH)
    events.to_parquet(tmp_dir / "closure_events.parquet")
    if IDLE_PERIODS_PATH.exists():
        idle = pd.read_parquet(IDLE_PERIODS_PATH)
    else:
        idle = pd.DataFrame(columns=["start_time", "end_time", "duration_seconds"])
    idle.to_parquet(tmp_dir / "idle_periods.parquet")
    return tmp_dir


ENUM_NORMALIZATION_CASES = [
    # (tool, param, raw LLM value, expected normalized value or None if it should be dropped)
    ("success_rate_analysis", "group_by", "head", "per_head"),  # the actual bug hit against the real cloud LLM
    ("success_rate_analysis", "group_by", "per_head", "per_head"),  # already valid -> unchanged
    ("torque_statistics", "filter_status", "success", "successful_only"),
    ("torque_statistics", "filter_status", "failed", "failed_only"),
    ("anomaly_detection", "method", "z-score", "zscore"),
    ("anomaly_detection", "method", "Z Score", "zscore"),
    ("success_rate_analysis", "group_by", "not_a_real_group", None),  # nothing matches -> dropped
    ("success_rate_analysis", "head_filter", ["H01"], ["H01"]),  # no enum on this param -> passed through unchanged
]


def test_enum_normalization() -> None:
    print("--- enum normalization (router param repair) ---")
    for tool, param, raw, expected in ENUM_NORMALIZATION_CASES:
        value, ok = normalize_enum_value(tool, param, raw)
        if expected is None:
            assert not ok, f"{tool}.{param}={raw!r}: expected drop, got {value!r}"
        else:
            assert ok and value == expected, f"{tool}.{param}={raw!r}: expected {expected!r}, got {value!r} (ok={ok})"
        print(f"[OK] {tool}.{param}={raw!r} -> {value!r}")
    print(f"All {len(ENUM_NORMALIZATION_CASES)} enum-normalization cases passed.\n")


def test_keyword_fallback() -> None:
    print("--- keyword fallback ---")
    for query, expected_tool in KEYWORD_CASES:
        got = keyword_route(query)
        assert got == expected_tool, f"query={query!r}: expected {expected_tool!r}, got {got!r}"
        print(f"[OK] {query!r} -> {got}")
    print(f"All {len(KEYWORD_CASES)} keyword-fallback cases passed.\n")


def test_graceful_degradation(data_dir: Path) -> None:
    print("--- graceful degradation (LLM forced off) ---")
    executor = ToolExecutor(data_dir)
    for query in VALIDATION_QUERIES:
        route_result = route(query, use_llm=False)
        assert not route_result.used_llm
        assert route_result.tool_calls, f"no tool_calls for {query!r}"

        executable = [c for c in route_result.tool_calls if c.tool not in {"meta_knowledge", "none"}]
        exec_results = executor.execute_all(executable)
        for r in exec_results:
            assert r.error is None, f"{query!r} -> {r.tool} failed: {r.error}"

        answer = compose(query, route_result.tool_calls, exec_results, route_result.reasoning, use_llm=False)
        assert isinstance(answer, str) and answer, f"empty answer for {query!r}"
        print(f"[OK] {query!r} -> tool={route_result.tool_calls[0].tool!r}")
    print(f"All {len(VALIDATION_QUERIES)} queries answered without the LLM.\n")


def test_full_agent_with_llm(data_dir: Path) -> None:
    print("--- full agent pipeline (LLM) ---")
    if not llm.is_ollama_available():
        print(f"SKIP: no Ollama server reachable at {llm.OLLAMA_HOST}.\n")
        return

    agent = AROLAgent(data_dir)
    assert agent.llm_available
    for query in VALIDATION_QUERIES:
        response = agent.query(query)
        print(f"\nQ: {query}")
        print(f"tools: {response.tool_calls}")
        print(f"A: {response.answer[:300]}")
        assert isinstance(response.answer, str) and response.answer
        assert response.execution_time >= 0
    print("\nFull LLM-backed pipeline checks passed.\n")


def main() -> None:
    if not CLOSURE_EVENTS_PATH.exists():
        print(f"SKIP: {CLOSURE_EVENTS_PATH} not found -- run the ingestion pipeline first.")
        return

    test_enum_normalization()
    test_keyword_fallback()

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = make_sample_data_dir(Path(tmp))
        test_graceful_degradation(data_dir)
        test_full_agent_with_llm(data_dir)

    print("All agent (Layer 3) checks passed.")


if __name__ == "__main__":
    main()
