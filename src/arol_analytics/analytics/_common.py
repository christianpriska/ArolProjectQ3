# Shared filtering, timing, and serialization helpers used by every analytics tool.

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np
import pandas as pd

from arol_analytics.ingestion.schema import IDLE_STATUS_CODE, SUCCESS_STATUS_CODE

logger = logging.getLogger(__name__)

# a (start, end) pair -- anything pd.Timestamp() accepts (str, datetime, Timestamp)
TimeRange = tuple[Any, Any]

SLOW_OPERATION_SECONDS = 5.0


def format_percentage(value: Any, suffix: str = "%") -> str:
    """Format rates without rounding a non-perfect result to 100.00%.

    Two decimals stay readable for ordinary rates; values very close to either
    boundary use four so rare failures do not disappear from the presentation.
    """
    if value is None or value != value:
        return "n/a"
    numeric = float(value)
    decimals = 4 if (0.0 < numeric < 0.01) or (99.99 < numeric < 100.0) else 2
    return f"{numeric:.{decimals}f}{suffix}"


def effective_time_range(events: pd.DataFrame, requested: TimeRange | None = None) -> TimeRange | None:
    """Use the requested window, or the observed event span when omitted."""
    if requested is not None:
        return requested
    if events.empty:
        return None
    return events["timestamp"].min(), events["timestamp"].max()


@contextmanager
def log_duration(operation: str) -> Iterator[None]:
    """Log how long a block took; escalate to INFO if it crosses SLOW_OPERATION_SECONDS."""
    start = time.monotonic()
    logger.debug("starting %s", operation)
    yield
    elapsed = time.monotonic() - start
    level = logging.INFO if elapsed > SLOW_OPERATION_SECONDS else logging.DEBUG
    logger.log(level, "%s took %.1fs", operation, elapsed)


def filter_events(
    events: pd.DataFrame,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> pd.DataFrame:
    """Apply the (head_filter, time_range) filters every tool accepts."""
    if head_filter:
        events = events[events["head_id"].isin(head_filter)]
    if time_range:
        start, end = pd.Timestamp(time_range[0]), pd.Timestamp(time_range[1])
        events = events[(events["timestamp"] >= start) & (events["timestamp"] <= end)]
    return events


def real_closures(events: pd.DataFrame) -> pd.DataFrame:
    """Exclude No Load (status 2) events -- not real capping attempts."""
    return events[events["status_code"] != IDLE_STATUS_CODE]


def successful_closures(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["status_code"] == SUCCESS_STATUS_CODE]


def failed_closures(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["is_reject"]]


def group_mean_std_flags(values: pd.Series, sensitivity: float = 2.0) -> tuple[float, float, pd.Series]:
    """Return (mean, std, boolean mask of |v - mean| > sensitivity*std) for a set of per-group values.

    Needs at least 2 non-null values and a non-zero std, otherwise nothing is flagged.
    """
    clean = values.dropna()
    if len(clean) < 2:
        return float("nan"), float("nan"), pd.Series(False, index=values.index)
    mean, std = float(clean.mean()), float(clean.std(ddof=0))
    if std == 0:
        return mean, std, pd.Series(False, index=values.index)
    flags = (values - mean).abs() > sensitivity * std
    return mean, std, flags.fillna(False)


def to_jsonable(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalars to native Python types for json.dump."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj) if not np.isnan(obj) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if isinstance(obj, float) and np.isnan(obj):
        return None
    return obj
