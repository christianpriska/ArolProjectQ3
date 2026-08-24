# CLI entry point: python -m arol_analytics.agent data/processed/
# Interactive loop: type a question, get an answer. Ctrl-D or "exit"/"quit" to leave.

from __future__ import annotations

import argparse
import logging
import sys

from arol_analytics.agent.agent import AROLAgent

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AROL Layer-3 agent: ask questions about the capping-machine data.")
    parser.add_argument("data_dir", help="Directory containing closure_events.parquet and idle_periods.parquet.")
    parser.add_argument("--model", default=None, help="Ollama model name (default: env AROL_LLM_MODEL or 'mistral').")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"Loading data from {args.data_dir} ...")
    agent = AROLAgent(args.data_dir, model=args.model)
    print(f"Ready. LLM routing: {'ON (' + agent.model + ')' if agent.llm_available else 'OFF (keyword fallback mode)'}")
    print("Type a question about the AROL capping data, or 'exit'/'quit' to leave.\n")

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            break

        response = agent.query(query)
        print(f"\n{response.answer}\n")
        print(f"[tools: {response.tool_calls} | llm={response.used_llm} | {response.execution_time:.2f}s]\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
