# Demo Runbook

Deliverable requirement, verbatim: *"one end-to-end run that loads a dataset
pool and generates at least two different report types."* `scripts/demo.sh`
is that run — a single script, one invocation, that (1) loads the dataset
pool (ingests the raw CSV archive under `src/data/`, or reuses an
already-ingested one) and (2) generates **three** report types from it
(exceeding the ≥2 minimum). It also runs a few natural-language questions
through the Layer-3 agent afterward, as a bonus segment for the agentic
orchestration criteria (tool selection, explainable answers, graceful
failure with no LLM) — that part isn't required by the deliverable text
above, only the first two stages are.

**For the live run in front of the professor, use `--fresh`** so the
ingestion step (loading the dataset pool from raw CSVs) is genuinely part of
the demonstrated run, not silently skipped because `data/processed/` already
existed from an earlier session. Budget ~2-3 minutes for that. If time is
tight, the default (no `--fresh`) still satisfies the requirement as written
— it loads the dataset pool via `analytics.io.load_closure_events`/
`load_idle_periods` from the already-ingested Parquet output and generates
the three report types from it — but say so explicitly rather than let it
look skipped.

## Before the demo

```bash
source .venv/bin/activate
pip install -r requirements.txt   # if not already done
```

Make sure `data/processed/` already exists (run
`PYTHONPATH=src python -m arol_analytics.ingestion src/data --output-dir data/processed`
once beforehand, ~1-2 minutes) — the demo script will ingest automatically if
it's missing, but that adds a couple of minutes live that's better spent
talking through the results instead.

Optional: if you want to show LLM-backed routing rather than the keyword
fallback, set `OLLAMA_API_KEY` (Ollama Cloud, no local install) or start
`ollama serve` beforehand — see the README's "Optional: enabling the
LLM-backed agent" section. Not required: the whole demo works, and is fully
reproducible, without it.

## Running it

```bash
./scripts/demo.sh          # reuses data/processed/ if present (~1 minute)
./scripts/demo.sh --fresh  # re-ingests from src/data/ first (~2-3 minutes)
```

## What happens, stage by stage

**Stage 1 — Ingestion (Layer 1).** Skipped if `data/processed/` already
exists (the common case for a live demo). If run, this is the point to talk
through: 89 raw CSVs → schema validation → corrupted-reading cleanup →
per-head closure detection → `closure_events.parquet` / `idle_periods.parquet`.

**Stage 2 — Report generation (Layer 2), ~45s.** Runs
`python -m arol_analytics.reports data/processed --output reports/demo`,
which calls the real analytics functions (`generate_kpi_dashboard`,
`head_comparison`, `anomaly_detection`, `failure_analysis`) live and writes
three Markdown reports:
- `kpi_dashboard.md` — headline KPIs + full per-head ranking table.
- `anomaly_report.md` — anomaly counts, failure breakdown, bursts, monitoring recommendations.
- `head_comparison_report.md` — full ranking, Kruskal-Wallis test, torque variability.

Open one or two of these (`reports/demo/kpi_dashboard.md`) to show real
numbers from the real 55M-row dataset, not a mockup. Point out the
`format_percentage` precision (`99.9965%`, not a misleadingly rounded
`100.00%`) and the machine-wide-vs-per-head throughput distinction as
examples of correctness details the pipeline gets right.

**Stage 3 — Agent Q&A (Layer 3), a few seconds.** Runs three canned questions
through `AROLAgent` (`scripts/demo_agent_queries.py`) — canned rather than
typed live so the demo is reproducible regardless of what's reachable that
day:
1. *"What is the overall success rate?"* — single-tool routing
   (`success_rate_analysis`), with the dedicated formula-based answer
   (exact numerator/denominator, not just a number).
2. *"Compare all the heads and tell me which one is behaving differently."*
   — routes to `head_comparison`, surfaces the statistically flagged heads.
3. *"What preprocessing steps were applied to the raw data?"* — a meta
   question, answered from the static knowledge base rather than by running
   an analytics tool at all.

The printed `[tools: ... | llm=... | Ns]` line after each answer is worth
calling out: it shows which tool was picked, whether the LLM or the keyword
fallback did the routing, and the timing — the graceful-failure story
(`docs/agent_flow.md`'s fallback table) is demonstrated just by running this
with no Ollama configured, which is the default state.

## If something goes wrong

- **`data/processed/closure_events.parquet` missing and `src/data/` is
  empty**: the raw CSVs aren't in the repo/checkout — nothing to ingest.
  Confirm the dataset was placed under `src/data/` first.
- **Report generation looks slow**: it's computing real statistics over
  55M rows (~45s total for all three reports) — this is expected, not a
  hang. `PYTHONPATH=src python -m arol_analytics.reports data/processed
  --output reports/demo -v` adds progress logging if you want to narrate
  what's running.
- **Agent stage says `LLM routing: OFF (keyword-fallback mode)`**: expected
  unless Ollama was set up beforehand — the answers are still real and
  correct, this is the documented fallback behavior, not a bug.
