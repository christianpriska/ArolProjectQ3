"""Runs a fixed set of natural-language questions through the Layer-3 agent
and prints each answer -- the live Q&A segment of scripts/demo.sh.

Canned (not typed live) so the demo is reproducible: same questions, same
tool routing, regardless of what's reachable on the day. Covers a single-tool
question, a multi-tool question, and a meta/system question, so all three
paths traced in docs/agent_flow.md show up in the same run.

Run as: PYTHONPATH=src python scripts/demo_agent_queries.py [data_dir]
(or plain `python scripts/demo_agent_queries.py` -- it adds src/ to sys.path itself)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from arol_analytics.agent.agent import AROLAgent  # noqa: E402

DEMO_QUERIES = [
    "What is the overall success rate?",
    "Compare all the heads and tell me which one is behaving differently.",
    "What preprocessing steps were applied to the raw data?",
]


def main() -> int:
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/processed"
    print(f"Loading {data_dir} ...")
    agent = AROLAgent(data_dir)
    mode = f"ON ({agent.model})" if agent.llm_available else "OFF (keyword-fallback mode)"
    print(f"Ready. LLM routing: {mode}\n")

    for query in DEMO_QUERIES:
        print(f"> {query}")
        response = agent.query(query)
        print(response.answer)
        print(f"[tools: {response.tool_calls} | llm={response.used_llm} | {response.execution_time:.2f}s]\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
