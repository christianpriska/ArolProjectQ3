"""Ricostruzione robusta degli eventi di chiusura dai file CSV.

La classe :class:`ClosureExtractor` conserva lo stato tra file consecutivi e
distingue gli incrementi osservati, aggregati, avvenuti durante un gap e
fisicamente anomali. I reset vengono rilevati sulla serie grezza, prima di
qualsiasi deduplicazione.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional

from src.config import (
    DATA_DIR,
    MAX_CLOSURES_PER_HEAD_SECOND,
    MAX_CONTIGUOUS_GAP_SECONDS,
    NOMI_TESTE,
)


@dataclass
class HeadState:
    """Ultima misurazione valida osservata per una testa."""

    counter: int
    timestamp: datetime
    reset_epoch: int = 0


@dataclass(frozen=True)
class ClosureEvent:
    """Evento ricostruito senza inventare dettagli non osservati."""

    timestamp: str
    head_id: str
    counter: int
    counter_delta: int
    accepted_closure_count: Optional[int]
    torque_nm: Optional[float]
    status_code: Optional[int]
    reset_epoch: int
    event_quality: str
    source_file: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_timestamp(value: str) -> datetime:
    """Interpreta un timestamp ISO senza assumere un fuso orario."""

    if not value:
        raise ValueError("Missing timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"Invalid timestamp: {value!r}") from error


def parse_counter(value: str, column: str) -> int:
    """Converte i contatori salvati come float, rifiutando valori frazionari."""

    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid counter in {column}: {value!r}") from error
    if not number.is_integer():
        raise ValueError(f"Non-integer counter in {column}: {value!r}")
    return int(number)


def parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"Expected an integer value, found {value!r}")
    return int(number)


class ClosureExtractor:
    """Estrae eventi mantenendo continuità, reset e qualità dell'osservazione."""

    def __init__(
        self,
        head_ids: Iterable[str] = NOMI_TESTE,
        max_contiguous_gap_seconds: float = MAX_CONTIGUOUS_GAP_SECONDS,
        max_closures_per_head_second: float = MAX_CLOSURES_PER_HEAD_SECOND,
    ) -> None:
        if max_contiguous_gap_seconds <= 0:
            raise ValueError("max_contiguous_gap_seconds must be positive")
        if max_closures_per_head_second <= 0:
            raise ValueError("max_closures_per_head_second must be positive")

        self.head_ids = tuple(head_ids)
        self.max_contiguous_gap_seconds = max_contiguous_gap_seconds
        self.max_closures_per_head_second = max_closures_per_head_second
        self.state: dict[str, HeadState] = {}

    def iter_rows(
        self,
        rows: Iterable[Mapping[str, str]],
        source_file: str,
    ) -> Iterator[ClosureEvent]:
        """Estrae eventi da righe già lette, conservando lo stato tra chiamate."""

        for row in rows:
            timestamp_text = row.get("timestamp", "")
            timestamp = parse_timestamp(timestamp_text)

            for head_id in self.head_ids:
                count_column = f"{head_id} Count"
                if count_column not in row:
                    raise ValueError(f"Missing required column: {count_column}")

                counter = parse_counter(row[count_column], count_column)
                previous = self.state.get(head_id)

                if previous is None:
                    self.state[head_id] = HeadState(counter, timestamp)
                    continue

                delta = counter - previous.counter
                elapsed_seconds = (timestamp - previous.timestamp).total_seconds()

                if delta < 0:
                    self.state[head_id] = HeadState(
                        counter=counter,
                        timestamp=timestamp,
                        reset_epoch=previous.reset_epoch + 1,
                    )
                    continue

                current_state = HeadState(
                    counter=counter,
                    timestamp=timestamp,
                    reset_epoch=previous.reset_epoch,
                )
                self.state[head_id] = current_state

                if delta == 0:
                    continue

                quality, accepted_count = self._classify_increment(
                    delta,
                    elapsed_seconds,
                )

                yield ClosureEvent(
                    timestamp=timestamp_text,
                    head_id=head_id,
                    counter=counter,
                    counter_delta=delta,
                    accepted_closure_count=accepted_count,
                    torque_nm=parse_optional_float(row.get(f"{head_id} AppTorque")),
                    status_code=parse_optional_int(row.get(f"{head_id} Status")),
                    reset_epoch=current_state.reset_epoch,
                    event_quality=quality,
                    source_file=source_file,
                )

    def iter_file(self, path: Path) -> Iterator[ClosureEvent]:
        """Estrae eventi da un CSV senza caricarlo interamente in memoria."""

        with path.open(mode="r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise ValueError(f"The file {path} does not contain a header")
            yield from self.iter_rows(reader, source_file=path.name)

    def iter_files(self, paths: Iterable[Path]) -> Iterator[ClosureEvent]:
        """Elabora file ordinati mantenendo lo stato tra i loro confini."""

        for path in sorted(paths):
            yield from self.iter_file(path)

    def _classify_increment(
        self,
        delta: int,
        elapsed_seconds: float,
    ) -> tuple[str, Optional[int]]:
        if elapsed_seconds <= 0:
            return "anomalous", None
        if elapsed_seconds > self.max_contiguous_gap_seconds:
            return "gap", None

        plausible_limit = max(
            1,
            int(self.max_closures_per_head_second * elapsed_seconds),
        )
        if delta > plausible_limit:
            return "anomalous", None
        if delta == 1:
            return "observed", 1
        return "aggregated", delta


def discover_csv_files(data_dir: Path = DATA_DIR) -> list[Path]:
    """Restituisce tutti i CSV in ordine lessicografico/cronologico."""

    return sorted(data_dir.rglob("*.csv"))


if __name__ == "__main__":
    files = discover_csv_files()
    if not files:
        raise FileNotFoundError(f"No CSV files found in {DATA_DIR}")

    extractor = ClosureExtractor()
    quality_counts: dict[str, int] = {}
    total_accepted = 0
    for event in extractor.iter_files(files):
        quality_counts[event.event_quality] = (
            quality_counts.get(event.event_quality, 0) + 1
        )
        total_accepted += event.accepted_closure_count or 0

    print(f"CSV files processed: {len(files)}")
    print(f"Accepted closures: {total_accepted}")
    print(f"Event quality: {quality_counts}")
