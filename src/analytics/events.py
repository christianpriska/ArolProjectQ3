"""Filtri e metriche deterministiche sugli eventi ricostruiti."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Iterable, Iterator, Optional

from src.ingestion.events import ClosureEvent, parse_timestamp


@dataclass(frozen=True)
class MachineSpeedPoint:
    """Velocità aggregata della macchina su una finestra temporale."""

    timestamp: str
    closures_in_window: int
    pieces_per_hour: float
    window_seconds: int


def filter_events(
    events: Iterable[ClosureEvent],
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    head_ids: Optional[Iterable[str]] = None,
    status_codes: Optional[Iterable[int]] = None,
    event_qualities: Optional[Iterable[str]] = None,
    accepted_only: bool = False,
) -> Iterator[ClosureEvent]:
    """Filtra gli eventi senza dipendere da Pandas o dal database."""

    start = parse_timestamp(start_time) if start_time else None
    end = parse_timestamp(end_time) if end_time else None
    selected_heads = {head.upper() for head in head_ids} if head_ids else None
    selected_statuses = set(status_codes) if status_codes else None
    selected_qualities = set(event_qualities) if event_qualities else None

    for event in events:
        timestamp = parse_timestamp(event.timestamp)
        if start is not None and timestamp < start:
            continue
        if end is not None and timestamp > end:
            continue
        if selected_heads is not None and event.head_id.upper() not in selected_heads:
            continue
        if selected_statuses is not None and event.status_code not in selected_statuses:
            continue
        if selected_qualities is not None and event.event_quality not in selected_qualities:
            continue
        if accepted_only and event.accepted_closure_count is None:
            continue
        yield event


def compute_machine_speed(
    events: Iterable[ClosureEvent],
    window_seconds: int = 300,
) -> Iterator[MachineSpeedPoint]:
    """Calcola la velocità complessiva usando una finestra mobile.

    Gli eventi devono essere ordinati per timestamp. Gli incrementi non
    accettati non contribuiscono. Quando compare un evento classificato come
    ``gap``, la finestra viene azzerata e la velocità riparte solo dopo una
    nuova finestra temporale completamente osservata.
    """

    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")

    window: deque[tuple[datetime, int]] = deque()
    closures_in_window = 0
    observation_start: Optional[datetime] = None

    def timestamp_key(event: ClosureEvent) -> str:
        return event.timestamp

    for timestamp_text, same_timestamp in groupby(events, key=timestamp_key):
        timestamp = parse_timestamp(timestamp_text)
        group_count = 0
        contains_gap = False

        for event in same_timestamp:
            if event.event_quality == "gap":
                contains_gap = True
            group_count += event.accepted_closure_count or 0

        if contains_gap:
            window.clear()
            closures_in_window = 0
            observation_start = timestamp
            continue

        if observation_start is None:
            observation_start = timestamp

        window.append((timestamp, group_count))
        closures_in_window += group_count

        cutoff = timestamp.timestamp() - window_seconds
        while window and window[0][0].timestamp() <= cutoff:
            _, removed_count = window.popleft()
            closures_in_window -= removed_count

        observed_seconds = (timestamp - observation_start).total_seconds()
        if observed_seconds < window_seconds:
            continue

        yield MachineSpeedPoint(
            timestamp=timestamp_text,
            closures_in_window=closures_in_window,
            pieces_per_hour=closures_in_window * 3600.0 / window_seconds,
            window_seconds=window_seconds,
        )
