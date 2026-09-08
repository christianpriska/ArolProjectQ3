# Demo Runbook

The deliverable asks for *"one end-to-end run that loads a dataset pool and
generates at least two different report types."* `scripts/demo.sh` is that run:
a single invocation that (1) loads the dataset pool, ingesting the raw CSV
archive under `src/data/` or reusing an existing ingestion, and (2) generates
three report types from it, so it clears the two-report minimum. It then sends a
few natural-language questions to the Layer-3 agent. That third part is not part
of the requirement; it covers the agentic-orchestration criteria (tool
selection, explainable answers, fallback with no LLM).

For the live run, pass `--fresh` so the ingestion step actually runs instead of
being skipped because `data/processed/` is left over from an earlier session.
Budget 2-3 minutes for it. Without `--fresh` the run still satisfies the
requirement, loading the dataset from the existing Parquet output via
`analytics.io.load_closure_events` / `load_idle_periods` and generating the three
reports, but point that out during the demo instead of letting it look skipped.

## Before the demo

```bash
source .venv/bin/activate
pip install -r requirements.txt   # if not already done
```

Ingest once beforehand so it doesn't eat into the live time:

```bash
PYTHONPATH=src python -m arol_analytics.ingestion src/data --output-dir data/processed
```

This takes about 2-3 minutes. If `data/processed/` is missing the demo script
runs it automatically.

To show LLM routing instead of the keyword fallback, set `OLLAMA_API_KEY`
(Ollama Cloud, no local install) or start `ollama serve` first; see the README's
"Optional: enabling the LLM-backed agent" section. The demo works and stays
reproducible without it, but the fourth agent question only produces a real
explanation when an LLM is reachable. In fallback mode it prints a single tool
summary instead.

## Running it

```bash
./scripts/demo.sh          # reuses data/processed/ if present (~1 minute)
./scripts/demo.sh --fresh  # re-ingests from src/data/ first (~2-3 minutes)
```

## What happens, stage by stage

**Stage 1 — Ingestion (Layer 1).** Skipped when `data/processed/` already
exists, which is the usual case for a live run. When it does run: 89 raw CSVs,
schema validation, corrupted-reading cleanup, per-head closure detection, then
`closure_events.parquet` and `idle_periods.parquet`.

**Stage 2 — Report generation (Layer 2), ~45s.** Runs
`python -m arol_analytics.reports data/processed --output reports/demo`, which
calls `generate_kpi_dashboard`, `head_comparison`, `anomaly_detection` and
`failure_analysis` on the real data and writes three Markdown files:

- `kpi_dashboard.md` — headline KPIs and the full per-head ranking table.
- `anomaly_report.md` — anomaly counts, failure breakdown, bursts, monitoring recommendations.
- `head_comparison_report.md` — full ranking, Kruskal-Wallis test, torque variability.

Open `reports/demo/kpi_dashboard.md` during the demo. Two things to point out:
the success rate is shown as `99.9965%`, not rounded to `100.00%`, and
throughput is reported machine-wide and per-head as two separate numbers.

**Stage 3 — Agent Q&A (Layer 3).** A few seconds in fallback mode, 10-20s with
Ollama (question 4 makes an extra call to compose the explanation). Runs four
fixed questions through `AROLAgent` (`scripts/demo_agent_queries.py`). They are
fixed rather than typed live so the run is reproducible regardless of what is
reachable on the day:

1. *"What is the overall success rate?"* — single tool (`success_rate_analysis`),
   answered with the explicit formula (numerator and denominator, not just a
   number). Same output with or without an LLM.
2. *"Compare all the heads and tell me which one is behaving differently."* —
   routes to `head_comparison` and reports the statistically flagged heads.
3. *"What preprocessing steps were applied to the raw data?"* — a meta question,
   answered from the static knowledge base without running an analytics tool.
4. *"Explain why some heads have more failed closures than others."* — an
   explanatory question. With an LLM the router selects `head_comparison` and
   `failure_analysis`, and `_synthesized_answer()` has the model write the
   explanation from those numbers without recomputing or inventing any. Without
   an LLM it routes to `failure_analysis` alone and prints its summary.

Each answer is followed by a `[tools: ... | llm=... | Ns]` line: the tool(s)
picked, whether the LLM or the keyword fallback routed it, and the time. Run
without Ollama to show the fallback path; run with Ollama to show question 4
producing an actual explanation.

## If something goes wrong

- **`data/processed/closure_events.parquet` missing and `src/data/` empty.** The
  raw CSVs aren't in the checkout, so there is nothing to ingest. Put the dataset
  under `src/data/` first.
- **Report generation looks slow.** It computes real statistics over 55M rows;
  ~45s for all three reports is normal, not a hang. Add `-v` to
  `python -m arol_analytics.reports data/processed --output reports/demo` for
  progress logging.
- **`LLM routing: OFF (keyword-fallback mode)`.** Expected unless Ollama was set
  up beforehand. Questions 1-3 still return correct answers. Question 4 needs the
  LLM to turn the numbers into an explanation; without it you get
  `failure_analysis`'s summary.
