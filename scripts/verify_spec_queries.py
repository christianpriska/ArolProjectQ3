"""Fire every example query from the project specification through the Layer-3
agent and print, for each: the tool(s) the router picked, whether the LLM or the
keyword fallback did the routing, the composed answer, and any tool errors.

Usage:
    PYTHONPATH=src python scripts/verify_spec_queries.py data/processed

With Ollama configured (OLLAMA_API_KEY or a local `ollama serve`) this exercises
the real routing + grounded-synthesis path. Without it, every query falls back to
keyword routing -- useful only to check nothing crashes.
"""

from __future__ import annotations

import sys
import textwrap

from arol_analytics.agent.agent import AROLAgent

SPEC_QUERIES: list[tuple[str, list[str]]] = [
    ("Basic data exploration", [
        "How many capping operations were performed in March?",
        "How many closure events were performed by each head?",
        "Show me the time range covered by the dataset.",
        "Are there any missing or invalid torque values?",
    ]),
    ("Quality and success-rate", [
        "What percentage of capping operations were successful?",
        "How many closures ended with a positive outcome?",
        "How many failed capping operations were recorded?",
        "What is the success rate per capping head?",
        "Which head shows the lowest success rate?",
    ]),
    ("Torque-related analytical", [
        "What is the average closing torque for successful capping operations?",
        "Show the torque distribution for all successful closures.",
        "Are there torque values outside the expected operating range of 0.5 to 4.0 Nm?",
        "Compare the average torque of successful vs failed closures.",
        "Which head shows the highest torque variability?",
    ]),
    ("Time-based and trend", [
        "How did the capping success rate evolve over time?",
        "Show a daily breakdown of successful vs failed closures.",
        "Are there specific time intervals with abnormal failure rates?",
        "Did the average torque change over the observed month?",
        "Is there a correlation between time of day and failure probability?",
    ]),
    ("Filtering and conditional", [
        "Show only capping operations with a positive outcome.",
        "List all failed capping events with torque below 1.0 Nm.",
        "How many closures had torque above 3.0 Nm?",
        "Show all capping events for head 3 with failed outcome.",
        "Count successful closures after removing all duplicated entries.",
    ]),
    ("Diagnostic and comparative", [
        "Which capping head behaves differently from the others?",
        "Is there a head with an unusual number of failed closures?",
        "Compare performance between head 1 and head 2.",
        "Which head contributes most to overall failures?",
        "Does higher torque correlate with higher success rate?",
    ]),
    ("Explanation-oriented", [
        "Why is the overall success rate lower on certain days?",
        "Explain why head 4 has more failed closures.",
        "Summarize the main issues observed in the capping process.",
        "Which signals should be monitored more closely?",
        "Generate a short report on capping quality for this dataset.",
    ]),
    ("Visualization-oriented", [
        "Plot the closing torque over time for successful closures.",
        "Show a histogram of closing torque values.",
        "Create a chart showing success rate per head.",
        "Visualize failed closures over time.",
        "Generate a dashboard summary of capping performance.",
    ]),
    ("Meta / system", [
        "What preprocessing steps were applied to the raw data?",
        "How were duplicated closures detected and removed?",
        "Which assumptions were made during data cleaning?",
        "What features are used to classify a successful closure?",
    ]),
]


def main(argv: list[str]) -> int:
    data_dir = argv[1] if len(argv) > 1 else "data/processed"
    agent = AROLAgent(data_dir)
    print(f"data: {data_dir}")
    print(f"LLM routing: {'ON (' + agent.model + ')' if agent.llm_available else 'OFF (keyword fallback)'}")
    print("=" * 100)

    n = 0
    for category, queries in SPEC_QUERIES:
        print(f"\n########## {category} ##########")
        for q in queries:
            n += 1
            resp = agent.query(q)
            tools = ", ".join(
                f"{c['tool']}({', '.join(f'{k}={v!r}' for k, v in c['parameters'].items())})"
                for c in resp.tool_calls
            )
            print(f"\n[{n:02d}] Q: {q}")
            print(f"     routed -> {tools}   [llm={resp.used_llm}, {resp.execution_time:.1f}s]")
            if resp.errors:
                print(f"     ERRORS: {resp.errors}")
            body = textwrap.indent(resp.answer.strip(), "     | ")
            print(body)
    print("\n" + "=" * 100)
    print(f"{n} queries executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
