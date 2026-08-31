# Layer 4 — Bot interface

This layer is responsible for providing a clear and user-friendly interface for the end user who will be using this research and development tool.

---

## 1. The Problem and the Goal

Layer 3 exposes `AROLAgent`, but only via the CLI (`python -m arol_analytics.agent`) — no buttons, no graphs, just one way to interact (type a question and wait). The **goal of Layer 4** is to create an interface with two modes, which the user can freely choose for each interaction, rather than in a forced sequence:
- **Guided mode**: a menu organized by categories, where each item directly calls a Layer 2 tool—no LLM involved, and responses are always deterministic and reproducible.
- **Free mode**: the user types a question in natural language, and `AROLAgent` (Layer 3) responds—using an LLM if available, or falling back to keywords otherwise.

---

## 2. File Map: what each file does

This layer places most of its files in the `src/arol_analytics/bot/` folder

```
src/arol_analytics/bot/
├── __init__.py       →  no dependencies on external accounts or networks
├── __main__.py       →  python -m arol_analytics.bot [data_dir]
├── config.py         →  data path, LLM model, list of tests H01-H36
├── registry.py       →  static data: menus, actions, help/example texts
├── keyboards.py      →  menu structure (label, callback_data)
├── formatters.py     →  raw Layer 2 dictionary → human-readable text
├── terminal_sim.py   →  the actual interactive loop
└── time_presets.py   →  time interval presets (7 days, 30 days, months, all)
```

In addition, it adds some classes to the Layer 2 folder that were developed specifically to manage this layer

```
src/arol_analytics/analytics/
├── events.py    →  Tool 11: list_events (filtered raw event list)
├── charts.py    →  Tool 14: visualize (PNG charts)
├── torque.py    →  + torque_outcome_comparison (Tool 12, success vs. failure)
└── heads.py     →  + torque_success_correlation (Tool 13)
```

### `config.py`

Defines three constants:
- `DATA_DIR` (default `data/processed`)
- `LLM_MODEL` (optional override; otherwise determined by Layer 3’s `llm.py`)
- `HEADS` (list `H01`...`H36`, used by `keyboards.py` for the head selector).

### `registry.py` — data, not behavior

It defines three static structures that `terminal_sim.py` (channel simulator) reads:
- `MENUS: dict[str, (text, keyboard_function)]` — one entry for each category (`main`, `success`, `torque`, `anomaly`, `cmp`, `failure`, `speed`, `idle`, `info`, `viz`, `help`).
- `RUN_ACTIONS: dict[str, RunAction]` — a “canned” action for a direct button (e.g., `"success:per_head"` → calls `success_rate_analysis(group_by="per_head")` and formats with `formatters.fmt_success_rate`). `RunAction` has an `is_chart: bool` field to distinguish between actions that produce images and those that produce text.
- `FLOW_ACTIONS: dict[str, RunAction]` — the same actions but for “custom” flows that first request the header and then the time interval.

It also defines the function `_build_examples_text()` that generates the text for `/examples` by reading `TOOL_REGISTRY` from layer 3 (`agent/tools.py`) — the same ~45 example questions used for the LLM’s system prompt, reused here to help the user discover what they can ask without reading the source code.

### `keyboards.py` — the menu structure

In this file, each function (`main_menu()`, `torque_menu()`, `head_picker()`, etc.) constructs an `InlineKeyboardMarkup`—the data class from `python-telegram-bot`, used for convenience and not because it’s an actual Telegram bot.

| Prefix | Meaning |
|---|---|
| `m:<menu>` | open a submenu |
| `r:<tool>:<preset>` | perform a direct action |
| `c:<flow>:head` | enter the custom flow, request the head |
| `h:<flow>:<HEAD\|all>` | select a head within a custom flow |
| `t:<flow>:<preset>` | select a range within a custom flow → execute |
| `more` | show the complete table of the previous result |
| `ask` | switch to free-form question mode |
| `noop` | disabled button |

### `formatters.py` — from the raw dictionary to text

Provides an `fmt_*` function for each tool, all with the same signature: they take the dictionary returned by layer 2 and return `(short_text, full_table_or_None)`. The short text is always safe to display immediately; the full table (when present, e.g., 36 heads) remains “hidden” behind the “Show full table” button—so a question about a single number still doesn’t generate a wall of text.

It uses a small subset of HTML-like tags (`<b>`, `<i>`, `<pre>`) that `terminal_sim.py` converts to ANSI style.

### `terminal_sim.py` — the actual interaction loop

The `TerminalSession` class maintains the state of a conversation (equivalent to `bot_data`/`user_data`/`chat_data` in a real Telegram bot, hence the field names): `buttons` (the numbered buttons currently on screen), `awaiting` (waiting for a special text input, e.g., the pair threshold for a custom anomaly), `pending_head_filter`/`cmp2_head1` (status of multi-step flows), `last_full_text` (for the "show all" button).

The main loop (`main()`): displays the main menu, then reads one line per iteration. If it’s a number that matches a button on the screen, it performs that action. If it starts with `/`, it’s a command. Otherwise, it’s free text → mode 2. **There is no explicit choice between the two modes**: at every prompt, both options—a number or a question—are always available; the user chooses for themselves on a per-interaction basis—there’s no need to “enter” free mode to use it (the “🤖 Free Question” button in the menu exists only as a reminder/shortcut; it’s not a mandatory gateway).

`run_action()` executes a `RunAction`: it calls the actual tool via `ToolExecutor` (the same one as in Layer 3—no duplication, same data loaded only once at startup), then either formats the text (`action.formatter`) or, if `is_chart`, saves the images to the disk (
`_save_chart()`).

`handle_free_question()` calls `agent.query()`—the same `AROLAgent` as in Layer 3, a single instance shared with the guided mode (same data in memory, no reloading).

---

## 3. "Custom" Flows: Head and Time Interval in Two Steps

For tools that accept a head and a time interval (success rate, torque, failure), the "Custom" button doesn't ask for everything at once—too many parameters in a single prompt would be cumbersome to test or use—but instead splits the operation into multiple steps:
1. `c:<flow>:head` → displays the grid H01...H36 (+ “All Heads”).
2. `h:<flow>:<head>` → saves the selection to `pending_head_filter`, displays the time presets (calculated by `time_presets.py` based on the actual dataset range, not hardcoded: “Last 7 days,” “Last 30 days,” a button for each month present in the data, “Entire dataset”).
3. `t:<flow>:<preset>` → performs the action with the combined head and time interval.

Comparing two specific heads (`c:cmp2:first` → `h:cmp2:<head1>` →
`h:cmp2b:<header2>`) is a similar but distinct case, because it requires two headers, not a header plus a time period.

---

## 4. Charts (`analytics/charts.py`, Tool 14 `visualize`)

### Why Layer 2 and not Layer 4?

Even though a chart is a "presentation," `render_chart()` resides in Layer 2 along with the other tools, not in the bot—for the same reason the other tools are there:
it works directly on `events`/`idle_periods`, and by placing it here, Layer 3 (the agent) can call it like any other tool, without Layer 3 having to import code from Layer 4 (which would reverse the direction of dependency between the layers).

### Six chart types, not a generic one

`torque_over_time`, `torque_histogram`, `success_rate_per_head`, `failures_over_time`, `production_over_time`, `utilization`, plus `kpi_dashboard`, which groups them together. Colors taken **verbatim** from the project’s validated palette (blue/orange/green for series, red/green for critical/good statuses) — not reinvented.

---

## 5. Final Results

To test the correct usage of all functions, we ran the 35 queries in the proposal twice.

**Keyword fallback only** (no LLM in sandbox environment): after
adding the 3 new tools and the missing keywords, all the
"Filtering and conditional" and "Torque-related" that were previously broken now route to the correct tool—the remaining limitation is structural, not a bug: the keyword fallback selects only the *tool*, never the *parameters* (no grouping by header, no numerical thresholds extracted from the text).

**With a true LLM** (`gpt-oss:120b` via Ollama Cloud), on the 35 questions in the specification in a single pass: **34/35** correct on the first run (the only exception, “count successful closures after removing duplicates,” was resolved immediately afterward—and re-verified individually, not in a second full run of all 35). 

The multi-tool approach (a question that chains together more than one tool, e.g., “why is the success rate lower on certain days” → `success_rate_analysis` + `failure_analysis` in sequence, structured report) **works**, as verified with a real-world question.
All chart types were visually verified using real data, not merely checked for the absence of exceptions.

---

## 6. Execution

```bash
source .venv/bin/activate

# Guided menu + open-ended questions (LLM if configured, otherwise automatic fallback)
PYTHONPATH=src python -m arol_analytics.bot data/processed

# With Ollama Cloud instead of on-premises
export OLLAMA_API_KEY="<la-tua-chiave-da-ollama.com/settings/keys>"
export AROL_LLM_MODEL="<un-modello-dalla-lista-cloud-su-ollama.com/models>"
PYTHONPATH=src python -m arol_analytics.bot data/processed
```

No external account is required for the guided mode or for keyword fallback—only `OLLAMA_API_KEY` is optional, and only to unlock Layer 3's natural language responses.

---