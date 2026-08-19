"""Pipeline end-to-end: CSV grezzi -> eventi ricostruiti -> SQLite."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.config import DATA_DIR, DB_PATH
from src.ingestion.events import ClosureEvent, ClosureExtractor, discover_csv_files
from src.storage.database import (
    create_connection,
    create_tables,
    insert_events,
    mark_file_ingested,
)


@dataclass
class IngestionSummary:
    files_processed: int = 0
    events_detected: int = 0
    events_inserted: int = 0
    accepted_closures: int = 0
    quality_counts: Counter = field(default_factory=Counter)
    reset_counts: dict[str, int] = field(default_factory=dict)
    gaps_detected: int = 0
    padding_rows_removed: int = 0


def batched(events: Iterable[ClosureEvent], size: int) -> Iterable[list[ClosureEvent]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    batch: list[ClosureEvent] = []
    for event in events:
        batch.append(event)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def run_ingestion(
    data_dir: Path = DATA_DIR,
    database_path: Path = DB_PATH,
    batch_size: int = 10_000,
    max_files: int | None = None,
) -> IngestionSummary:
    """Elabora i CSV in ordine e salva gli eventi in modo incrementale."""

    files = discover_csv_files(data_dir)
    if max_files is not None:
        files = files[:max_files]
    if not files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    extractor = ClosureExtractor()
    summary = IngestionSummary()

    with create_connection(database_path) as connection:
        create_tables(connection)
        for path in files:
            file_detected = 0
            file_inserted = 0
            for batch in batched(extractor.iter_file(path), batch_size):
                file_detected += len(batch)
                file_inserted += insert_events(connection, batch)
                for event in batch:
                    summary.quality_counts[event.event_quality] += 1
                    summary.accepted_closures += event.accepted_closure_count or 0

            mark_file_ingested(
                connection,
                source_file=path.name,
                events_detected=file_detected,
                events_inserted=file_inserted,
            )
            summary.files_processed += 1
            summary.events_detected += file_detected
            summary.events_inserted += file_inserted

    summary.reset_counts = {
        head_id: count
        for head_id, count in extractor.reset_counts.items()
        if count > 0
    }
    summary.gaps_detected = len(extractor.gaps)
    summary.padding_rows_removed = sum(extractor.padding_rows.values())
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest AROL telemetry into SQLite")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--database", type=Path, default=DB_PATH)
    parser.add_argument("--max-files", type=int)
    args = parser.parse_args()

    summary = run_ingestion(
        data_dir=args.data_dir,
        database_path=args.database,
        max_files=args.max_files,
    )
    print(f"Files processed: {summary.files_processed}")
    print(f"Events detected: {summary.events_detected}")
    print(f"Events inserted: {summary.events_inserted}")
    print(f"Accepted closures: {summary.accepted_closures}")
    print(f"Event quality: {dict(summary.quality_counts)}")
    print(f"Resets: {sum(summary.reset_counts.values())}")
    print(f"Gaps: {summary.gaps_detected}")
    print(f"Trailing padding rows removed: {summary.padding_rows_removed}")


if __name__ == "__main__":
    main()
