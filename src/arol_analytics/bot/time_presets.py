# Builds the guided-mode time-range preset buttons (Last 7 days / Last 30
# days / one per calendar month present in the data / Full Dataset) from the
# dataset's actual min/max timestamp -- computed once at bot startup rather
# than hardcoded, so the bot doesn't silently go stale if the archive grows.

from __future__ import annotations

import calendar
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimePreset:
    key: str
    label: str
    time_range: tuple[str, str] | None  # None means "no filter" (full dataset)


def build_time_presets(min_ts: pd.Timestamp, max_ts: pd.Timestamp) -> list[TimePreset]:
    presets: list[TimePreset] = [
        TimePreset("7d", "Last 7 days", (str(max_ts - pd.Timedelta(days=7)), str(max_ts))),
        TimePreset("30d", "Last 30 days", (str(max_ts - pd.Timedelta(days=30)), str(max_ts))),
    ]

    months = pd.period_range(min_ts.to_period("M"), max_ts.to_period("M"), freq="M")
    for i, period in enumerate(months):
        month_start = max(period.start_time, min_ts)
        month_end = min(period.end_time, max_ts)
        presets.append(TimePreset(f"m{i}", calendar.month_name[period.month], (str(month_start), str(month_end))))

    presets.append(TimePreset("full", "Full Dataset", None))
    return presets


def presets_by_key(presets: list[TimePreset]) -> dict[str, TimePreset]:
    return {p.key: p for p in presets}
