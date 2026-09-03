#!/usr/bin/env bash
# AROL Analytics -- end-to-end demo.
#
# Loads the raw telemetry dataset (ingesting it first if it hasn't been
# already), generates three report types from it, and runs a few
# natural-language questions through the Layer-3 agent.
#
# Usage:
#   ./scripts/demo.sh            # reuses data/processed/ if it already exists
#   ./scripts/demo.sh --fresh    # re-runs ingestion from the raw CSVs first
#
# Expects the virtualenv to already be active (source .venv/bin/activate).

set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="data/processed"
RAW_DIR="src/data"
REPORT_DIR="reports/demo"
FRESH=false
[[ "${1:-}" == "--fresh" ]] && FRESH=true

section() {
    echo
    echo "=============================================================="
    echo "  $1"
    echo "=============================================================="
}

section "Stage 1/3 -- Ingestion (Layer 1)"
if [[ ! -f "$DATA_DIR/closure_events.parquet" || "$FRESH" == true ]]; then
    echo "Loading raw telemetry CSVs from $RAW_DIR ..."
    PYTHONPATH=src python -m arol_analytics.ingestion "$RAW_DIR" --output-dir "$DATA_DIR"
else
    echo "$DATA_DIR already has ingested data -- skipping (pass --fresh to re-ingest)."
fi

section "Stage 2/3 -- Report generation (Layer 2)"
echo "Generating the KPI dashboard, anomaly report, and head comparison report..."
PYTHONPATH=src python -m arol_analytics.reports "$DATA_DIR" --output "$REPORT_DIR"
echo
echo "Reports written to $REPORT_DIR/:"
ls -la "$REPORT_DIR"

section "Stage 3/3 -- Agent Q&A (Layer 3)"
PYTHONPATH=src python scripts/demo_agent_queries.py "$DATA_DIR"

section "Demo complete"
echo "Open the files under $REPORT_DIR/ to walk through the generated reports."
