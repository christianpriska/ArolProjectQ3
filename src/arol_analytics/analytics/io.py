# Load Layer-1 (ingestion) Parquet outputs for use by the analytics tools.

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# low-cardinality text columns -- downcast to category to cut memory on a 55M-row frame
CLOSURE_EVENTS_CATEGORICAL_COLUMNS = ["head_id", "status_label", "classification", "source_file"]


def _resolve(path: str | Path, filename: str) -> Path:
    path = Path(path)
    return path / filename if path.is_dir() else path


def load_closure_events(path: str | Path) -> pd.DataFrame:
    """Load closure_events.parquet. `path` may be the file itself or its containing directory."""
    file_path = _resolve(path, "closure_events.parquet")
    logger.info("loading closure events from %s", file_path)
    df = pd.read_parquet(file_path)
    for col in CLOSURE_EVENTS_CATEGORICAL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype("category")
    logger.info("loaded %d closure events, %d heads", len(df), df["head_id"].nunique())
    return df


def load_idle_periods(path: str | Path) -> pd.DataFrame:
    """Load idle_periods.parquet. `path` may be the file itself or its containing directory."""
    file_path = _resolve(path, "idle_periods.parquet")
    logger.info("loading idle periods from %s", file_path)
    df = pd.read_parquet(file_path)
    logger.info("loaded %d idle periods", len(df))
    return df
