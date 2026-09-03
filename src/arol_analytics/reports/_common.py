# Shared formatting helpers for the Markdown report renderers in this package.

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def fmt(value: Any, spec: str = ".2f", suffix: str = "") -> str:
    """Format a number, or 'n/a' for None/NaN -- matches the convention every
    Layer-2 tool and formatter already uses (see analytics/_common.py)."""
    if value is None or value != value:
        return "n/a"
    return f"{value:{spec}}{suffix}"


def dataset_period(events: pd.DataFrame) -> str:
    """The observed time range of a closure_events frame, for a report header."""
    if events.empty:
        return "n/a"
    start, end = events["timestamp"].min(), events["timestamp"].max()
    return f"{start} - {end}"


def generated_on() -> str:
    return date.today().isoformat()
