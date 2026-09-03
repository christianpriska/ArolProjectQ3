# Layer 4 config: data path and the shared constants every other module in
# this package needs (head list, LLM model override).

from __future__ import annotations

import os

# Directory containing closure_events.parquet / idle_periods.parquet / data_quality_report.json
# -- same layout ToolExecutor and AROLAgent already expect.
DATA_DIR: str = os.environ.get("AROL_DATA_DIR", "data/processed")

# Ollama model override, forwarded to AROLAgent -- None lets it fall back to
# llm.DEFAULT_MODEL (env AROL_LLM_MODEL or "mistral").
LLM_MODEL: str | None = os.environ.get("AROL_LLM_MODEL")

# Heads are always H01..H36 on this machine -- the raw archive only ever
# reports 36 heads, even though ingestion/schema.py's MAX_HEADS=48 leaves room
# for a larger layout.
HEADS: list[str] = [f"H{i:02d}" for i in range(1, 37)]
