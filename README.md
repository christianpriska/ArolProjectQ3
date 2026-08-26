# AROL Analytics

An agentic AI pipeline for analyzing telemetry data from a 36-head AROL capping
machine: raw daily CSV exports are cleaned and reconstructed into per-closure
events, summarized by 14 deterministic analytics tools, exposed to natural-language
questions through an LLM-backed agent (with a fully deterministic fallback when no
LLM is available), and made accessible through a guided-menu-or-free-text terminal
chat interface. Built as a PoliTO "SDP Project Proposal — AI Agents" course project.

## Architecture

Four layers, each building on the last:

1. **Ingestion** (`src/arol_analytics/ingestion/`) — 89 raw wide-format CSVs → two
   clean Parquet datasets (`closure_events.parquet`, `idle_periods.parquet`) plus a
   JSON/Markdown data-quality report.
2. **Analytics** (`src/arol_analytics/analytics/`) — 14 deterministic tools
   (success rate, torque statistics/trend/correlation, anomaly detection, head
   comparison, failure analysis, production speed, idle analysis, KPI dashboard,
   event listing, chart rendering) over the Layer-1 output.
3. **Agent** (`src/arol_analytics/agent/`) — routes a natural-language question to
   one or more Layer-2 tools via an LLM (Ollama, local or cloud), with a
   deterministic keyword-based fallback when no LLM is reachable.
4. **Terminal bot** (`src/arol_analytics/bot/`) — a local terminal chat interface
   (guided menu + free-text questions) over Layers 2 and 3. **Note**: despite the
   module name, this is a local terminal simulator, not a network-facing Telegram
   bot — it reuses `python-telegram-bot`'s keyboard classes purely as an in-memory
   data container. No bot token, no polling, no network service.

Full detail, including a data-flow diagram, real dataset statistics, the complete
status-code reference, every tool's method/parameters/caveats, and a traced
agent-routing example, is in [`docs/`](docs/) — see the links at the bottom of this
file.

## Prerequisites

- **Python 3.12+** (developed and tested with Python 3.14). The pinned NumPy and
  SciPy versions require Python 3.12 or newer; verify the interpreter version
  before creating the virtual environment.
- **An LLM backend for Layer 3/4's free-question mode — optional.** Only
  [Ollama](https://ollama.com) is supported (`src/arol_analytics/agent/llm.py`),
  either:
  - a **local** `ollama serve` instance (`http://localhost:11434`, no auth,
    requires `ollama pull <model>` first), or
  - **Ollama Cloud** (`https://ollama.com`) — no local install needed, just an API
    key from [ollama.com/settings/keys](https://ollama.com/settings/keys).
  Without either, the agent and bot still work fully via deterministic keyword
  routing — this is not a hard requirement to run the project.
- **No Telegram token, no network service** — Layer 4 is a local terminal
  interface (see the architecture note above).

## Installation

```bash
git clone <this-repo-url>
cd ArolProjectQ3
python3 --version                  # must be 3.12 or newer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Place the raw telemetry CSVs under `src/data/` (or point the ingestion CLI at any
other directory containing them — see below).

### Optional: enabling the LLM-backed agent

```bash
# Option A: local Ollama
ollama serve                      # in a separate terminal
ollama pull mistral                # or any other local model
export AROL_LLM_MODEL=mistral      # optional, "mistral" is the default

# Option B: Ollama Cloud (no local install)
export OLLAMA_API_KEY=<your-key-from-ollama.com/settings/keys>
export AROL_LLM_MODEL=<a-model-name-from-ollama.com/models>   # no ":cloud" suffix
```

`AROL_OLLAMA_HOST` overrides the host explicitly if neither default applies.

## Running each component

All commands assume the virtualenv is active. `PYTHONPATH=src` is required for
the module CLIs below (pytest picks it up automatically from `pyproject.toml`).

```bash
# Layer 1: ingestion -- incrementally reads src/data/ and writes data/processed/
PYTHONPATH=src python -m arol_analytics.ingestion src/data --output-dir data/processed

# Layer 2: analytics CLI -- runs the full tool suite, writes reports/ (~40-90s)
PYTHONPATH=src python -m arol_analytics.analytics data/processed --output reports

# Layer 3: agent, interactive CLI (loads data/processed/ once, then a query loop)
PYTHONPATH=src python -m arol_analytics.agent data/processed

# Layer 4: terminal bot -- guided menu + free-question mode
PYTHONPATH=src python -m arol_analytics.bot data/processed
```

The ingestion CLI writes each processed CSV directly into the output Parquet
file. It therefore keeps roughly one daily CSV in memory instead of collecting
all 55 million closure events before writing them. `data/processed/` and
`reports/` are gitignored (generated artifacts) — regenerate them with the
commands above after cloning, or whenever the raw data changes.

## Running tests

The full suite is synthetic-data-only (no real dataset needed) and mocks the LLM
entirely (no live Ollama needed):

```bash
PYTHONPATH=src pytest tests/ -v
```

(`pyproject.toml` already sets `pythonpath = ["src"]` for pytest, so plain
`pytest tests/ -v` from the repo root works too.) 113 tests across ingestion,
analytics, agent, and end-to-end integration.

## Project structure

```
├── docs/                          # Architecture, data schema, analytics methods, agent flow
├── reports/
│   └── samples/                   # Sample reports generated from the real dataset
├── src/arol_analytics/
│   ├── ingestion/                 # Layer 1: raw CSV -> clean Parquet
│   ├── analytics/                 # Layer 2: 14 deterministic analytics tools
│   ├── agent/                     # Layer 3: LLM-backed query routing + composition
│   └── bot/                       # Layer 4: terminal chat interface
├── tests/                         # pytest suite (conftest.py + 4 test modules)
├── pyproject.toml                 # pytest configuration
└── requirements.txt
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system overview, data-flow
  diagram, and per-layer implementation detail.
- [`docs/data_schema.md`](docs/data_schema.md) — raw and processed data formats,
  the complete closure status-code reference, key dataset statistics.
- [`docs/analytics_methods.md`](docs/analytics_methods.md) — every analytics
  tool's method, parameters, interpretation notes, and known caveats.
- [`docs/agent_flow.md`](docs/agent_flow.md) — the full query → routing →
  execution → composition pipeline, the verbatim system prompt, and three traced
  example queries.
- [`docs/PHASE1_WALKTHROUGH.md`](docs/PHASE1_WALKTHROUGH.md) –
  [`PHASE4_WALKTHROUGH.md`](docs/PHASE4_WALKTHROUGH.md) — earlier, narrative
  development-session walkthroughs for each layer (kept for development history;
  the `docs/*.md` files above are the current, structured reference).

## Sample reports

Generated from the real dataset in `data/processed/` — see
[`reports/samples/`](reports/samples/):

- [`kpi_dashboard.md`](reports/samples/kpi_dashboard.md) — KPI summary + full
  36-head performance table.
- [`anomaly_report.md`](reports/samples/anomaly_report.md) — anomaly detection +
  failure breakdown, bursts, and monitoring recommendations.
- [`head_comparison_report.md`](reports/samples/head_comparison_report.md) — full
  36-head ranking, statistical test results, and torque variability analysis.
