# Phase 3 - The AI Agent

Using the computational functions developed in Phase 2, this phase focuses on interacting with the AI agent.

---

## 1. The Problem and the Goal

Phase 2 provides 10 deterministic Python functions that answer specific questions about the data; however, these are not understandable to the average user without a technical background in computer science.


**Objective**: to develop an agent that receives a question in natural language, autonomously decides which tool(s) to call, executes them, and returns a readable response-using an LLM as the "brain" for routing and composing the response, but **never** for calculating numbers: those always remain part of Layer 2's classical computation, the LLM reads and explains them, it does not invent them.

---

## 2. File Map: what each file does

```
src/arol_analytics/agent/
├── __init__.py       →  Exposes AROLAgent as the package's entry point
├── __main__.py       →  Interactive CLI: python -m arol_analytics.agent data/processed
├── tools.py          →  list of the 10 tools + normalization of enum parameters
├── llm.py            →  HTTP client for Ollama (local or cloud)
├── router.py         →  decides which tool(s) to call, given the query text
├── fallback.py       →  keyword routing, used if the LLM does not respond properly
├── executor.py       →  loads the data once and actually runs the tools
├── composer.py       →  transforms the raw output of the tools into a readable response
├── knowledge.py      →  static facts for questions like "how does the system work?"
└── agent.py          →  the orchestrator (AROLAgent) that brings everything together
```

Even without connecting to an LLM, you can still test some of the files: `router.py`, `fallback.py`, and `composer.py`.

### `tools.py` - the tool registry

A list of dictionaries, one for each of the 10 tools developed in Layer 2. For each tool, the following information is provided:
- name
- description
- accepted parameters (with valid values when the parameter is an enum,
e.g., `group_by` in `success_rate_analysis` can only be one of `overall`,
`per_head`, `daily`, `hourly`, `per_file`)
- examples of prompts that should trigger it

The `format_registry_for_prompt()` function converts all of this into text for the LLM's system prompt.

Meanwhile, `get_tool()` retrieves the definition of a tool by name.

Finally, `normalize_enum_value()` compares a value received from the LLM with the enum values declared in the dictionaries and corrects it if necessary, preventing potential bugs.

### `llm.py` - Communicating with LLM (Ollama)

A minimal HTTP client (using `requests`) for Ollama's `/api/chat` endpoint.
It works both locally (`http://localhost:11434`, no authentication required) and with Ollama Cloud (`https://ollama.com`, requires an API key).

The `is_ollama_available()` function checks (GET
`/api/tags`) before trusting that the server will respond; `chat()` sends messages and returns only the response text, raising an `OllamaUnavailableError` for any network issues or malformed responses.

### `router.py` - deciding which tool to use

The trickiest part. It receives the user's question and:

1. Constructs a **system prompt** that lists all 10 tools (from `tools.py`) plus two special entries: `meta_knowledge` (for questions about how the system works, not about the data) and `none` (if no tool can answer).
2. Asks the LLM to **respond only** with a JSON object: `{"reasoning": "...", "tool_calls": [{'tool': "...", "parameters": {...}}]}`.
3. **Extracts the JSON from the response**, even if the LLM has wrapped it in a ```` ```json ... ``` ```` block or added text before or after it (this often happens with smaller local models, and occasionally with cloud models as well).
4. If parsing fails, it attempts **a single retry** with a stricter prompt.
5. If it still fails, or if the LLM is unreachable, it hands control over to `fallback.py`.
6. Before returning the `tool_calls`, **normalize the parameters** against the enums declared in `tools.py`

### `fallback.py` - keyword routing

This component contains an ordered list of `(keyword, tool name)` pairs that are used if the LLM is unavailable, does not respond for an extended period, or if the response cannot be parsed.
The order of the pairs is important; the more specific entries come first so they can be checked before the more generic cases (e.g., "contributes most" → `failure_analysis` is checked before the generic entry "failure/failed" → same tool, but also before "compare/comparison" → `head_comparison`, to avoid ambiguity between similar questions).

### `executor.py` - Actually run the tools

1. **Load** `closure_events.parquet`, `idle_periods.parquet`, and (if present)
`data_quality_report.json` **only once**, at construction (`ToolExecutor`), not for every query.
2. **Map** each **tool** name to the Layer 2 function using `arol_analytics.analytics`.
3. **Convert the parameters** to the format expected by the functions (e.g., `time_range` from a JSON list `[start, end]` to a tuple).
4. Execute.
   - *No tool exception ever reaches the user as a crash*: it is caught and transformed into an `ExecutionResult` with the `error` field populated, which the composer can explain in natural language.

### `composer.py` - transforming numbers into a response

It receives the raw output (one or more `ExecutionResult` objects) and produces the final text. It behaves differently depending on the type of output received:
- **One query, one tool, not an explanatory question**: uses only data and formulas generated by the code. The success rate has a dedicated formatter; other tools use their own deterministic `summary`.
- **Explanatory or diagnostic question** (contains "why", "explain", "cause", "what should be monitored", "summarize the issues"), **or multiple tools**, **with an LLM available**: `_synthesized_answer()` gives the LLM each tool's `summary` plus a trimmed JSON of its result and asks for a prose answer built *strictly on those numbers*. The prompt forbids recomputing formulas, estimating, or introducing any figure that is not present, and requires the model to say so when the data shows *that* something happens but not *why*. The LLM connects the numbers, it does not produce them.
- **Same shapes with no LLM** (or the LLM failing mid-composition): deterministically lists the `summary`s of the executed tools and any errors under a `## Report` heading.

To prevent possible hallucinations, we introduce:
`meta_knowledge`: retrieves relevant facts from `knowledge.py` and, if the LLM is available, rephrases them in a conversational manner-without ever adding facts that are not in the knowledge base.
`none`: explains why no tool can respond, using the reasoning provided by the LLM (or the fallback).

### `knowledge.py` - what the system knows about itself

It contains a static dictionary of ~12 topics (preprocessing, closure detection, corrupted reads, duplicates, timestamps, status codes, the various "caveats" developed in layers 1-2, etc.), with **system-related information** drawn from the documentation.

The `pick_topics()` function performs keyword matching between the question and the available topics, so that `composer.py` sends only the relevant facts to the LLM, rather than the entire knowledge base for every question.

This approach was preferred over having the LLM read the code directly to prevent hallucinations.

### `agent.py` - the orchestrator

The `AROLAgent` class: 
1. creates a `ToolExecutor` (loads the data)
2. checks once whether Ollama is reachable (`llm.is_ollama_available()`) 
   - stores this in `self.llm_available`.  
3. the `query()` method executes `router.route()` → `executor.execute_all()` → `composer.compose()` in sequence 
4. returns an `AgentResponse` containing the text response, which tools were called and with what parameters, the raw data (`raw_data`, useful for programmatic use as well as text-based), the execution time, and any errors.

### `__main__.py` - the interactive CLI

```bash
PYTHONPATH=src python -m arol_analytics.agent data/processed
```

Loads the data once, then enters a `> question` → answer loop until you type
`exit`/`quit` or press Ctrl-D. It also prints which tool was used, whether the LLM was active, and how long it took-useful for understanding *what* the agent decided, not just *what* it replied.

---

## 3. Tools from layer 2

The router doesn't "know" anything on its own about the AROL data-it only knows what `tools.py` provides it in the system prompt. 

These are the available tools and how they can be used.    

| # | Tool | Responds to | Example Question |
|---|---|---|---|
| 1 | `dataset_summary` | General overview: number of closures, number of heads, time range, overall success rate | "How many closures are there in the dataset?" |
| 2 | `success_rate_analysis` | Success rate, groupable by head/day/hour/file | "What is the success rate per head?" |
| 3 | `torque_statistics` | Torque statistics (mean, quartiles, outliers), filterable by outcome | "What is the average torque in successful closures?" |
| 4 | `torque_trend_analysis` | Torque drift/trend over time, per head | "Is the torque changing over time?" |
| 5 | `anomaly_detection` | Anomalous capping by torque + hours with anomalous failure rates | "Are there any anomalous events?" |
| 6 | `head_comparison` | Direct comparison between heads (or a subset) | "Compare head H12 with H29" |
| 7 | `failure_analysis` | In-depth analysis of failures: bursts, daily peaks, dominant cause, failure rate by hour of day | "Why does head H29 fail more often?" |
| 8 | `capping_speed_analysis` | Production speed (entire machine vs. single head) | "What is the machine's production speed?" |
| 9 | `idle_analysis` | Downtime, utilization rate | "What is the machine's utilization rate?" |
| 10 | `generate_kpi_dashboard` | Summary dashboard (calls other tools internally) | "How is the machine performing overall?" |

Plus two special entries, not present in Layer 2, managed directly by the router:

| Entry | What it does |
|---|---|
| `meta_knowledge` | Questions about how the system itself works (preprocessing, assumptions) - answer from `knowledge.py`, not from the data (Section 8) |
| `none` | No tool can answer the question - the agent explicitly states this instead of making up an answer |

Note that in layer 4 more tools are added and are present in `tools.py`, however they don't belong to the structure of this layer.
 
---

## 4. Question Handling Pipeline

1. **Routing**: `router.route(question)` attempts to contact the LLM (if available). It constructs the system prompt from `tools.py` (plus the dataset's date range, so the model can resolve "in March" into a `time_range`), sends the question and prompt, attempts to parse the response as valid JSON (with a retry if necessary), and normalizes parameters: enum values onto the declared enum, and loose head references ("head 3", "2") onto the canonical "H03" form. If all of this fails, it falls back to `fallback.keyword_route()`.
2. **Execution**: `executor.execute_all()` takes the list of `tool_calls` determined by the router (one or more) and actually executes them against the data already loaded into memory. Each call is isolated: if one fails, the others continue regardless.
3. **Composition**: `composer.compose()` takes the results (including any errors) and produces the answer. Single-tool numeric results and the no-LLM path stay fully deterministic; explanatory or multi-tool questions get a prose write-up that the LLM composes *from the tool results only* (no recomputed or invented numbers). The availability of the LLM affects wording, never the figures.
4. **Response**: `agent.query()` packages everything into an `AgentResponse` and returns it-the CLI (`__main__.py`) prints it, but any other interface (e.g., a future web app, according to `bot_proposal.md`) could use the same object.

---

## 5. Ollama: Local or Cloud-Your Choice

The client (`llm.py`) uses the same HTTP protocol whether Ollama is running locally (`ollama serve` on your own machine, `ollama pull <model>` to download it) or whether you're using [Ollama Cloud](https://ollama.com) (no local installation required; you just need an API key from ollama.com/settings/keys). The choice is made automatically based on environment variables:

| Variable | Effect |
|---|---|
| (none set) | local, `http://localhost:11434`, no authentication |
| `OLLAMA_API_KEY=... ` | cloud, `https://ollama.com`, `Authorization: Bearer ...` header added automatically |
| `AROL_OLLAMA_HOST=...` | explicit host override, always takes precedence over the two rules above |
| `AROL_LLM_MODEL=...` | model name (default `mistral`, valid only locally) |

**Note on model names**: When connecting via a local `ollama serve`, cloud models are referenced with the suffix `:cloud` (e.g., `gpt-oss:120b-cloud`). However, when calling `https://ollama.com` **directly** (as this client does when an `OLLAMA_API_KEY` is present), you use the exact name returned by `GET /api/tags` on that host, **without** the suffix-the suffix is only used for internal routing within a local `ollama serve` and makes no sense when there is no local binary involved.

---

## 6. Execution

```bash
source .venv/bin/activate

# Interactive CLI for the full dataset (local, if Ollama is not configured: automatic fallback)
PYTHONPATH=src python -m arol_analytics.agent data/processed

# Same thing, but using Ollama Cloud instead of a local instance
export OLLAMA_API_KEY="<la-tua-chiave-da-ollama.com>"
export AROL_LLM_MODEL="<un-modello-dalla-lista-cloud-su-ollama.com/models>"
PYTHONPATH=src python -m arol_analytics.agent data/processed

# Test (always executable; the part involving the actual LLM is activated only if Ollama is accessible)
PYTHONPATH=src python tests/test_agent.py
```