"""Persistenza SQLite per eventi ricostruiti e metadati di ingestion."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from src.config import DB_PATH
from src.ingestion.events import ClosureEvent


def create_connection(path: Path = DB_PATH) -> sqlite3.Connection:
    """Apre il database e restituisce righe accessibili per nome colonna."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    """Crea lo schema senza eliminare eventuali tabelle precedenti."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS closure_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            head_id TEXT NOT NULL,
            counter INTEGER NOT NULL,
            counter_delta INTEGER NOT NULL,
            elapsed_seconds REAL NOT NULL,
            accepted_closure_count INTEGER,
            torque_nm REAL,
            status_code INTEGER,
            reset_epoch INTEGER NOT NULL,
            event_quality TEXT NOT NULL CHECK (
                event_quality IN ('observed', 'aggregated', 'gap', 'anomalous')
            ),
            source_file TEXT NOT NULL,
            UNIQUE (timestamp, head_id, reset_epoch, counter, source_file)
        );

        CREATE INDEX IF NOT EXISTS idx_closure_events_timestamp
            ON closure_events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_closure_events_head_timestamp
            ON closure_events(head_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_closure_events_quality
            ON closure_events(event_quality);

        CREATE TABLE IF NOT EXISTS ingested_files (
            source_file TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            events_detected INTEGER NOT NULL,
            events_inserted INTEGER NOT NULL
        );
        """
    )
    connection.commit()


def insert_events(
    connection: sqlite3.Connection,
    events: Iterable[ClosureEvent],
) -> int:
    """Inserisce gli eventi in modo idempotente e restituisce le nuove righe."""

    before = connection.total_changes
    connection.executemany(
        """
        INSERT OR IGNORE INTO closure_events (
            timestamp,
            head_id,
            counter,
            counter_delta,
            elapsed_seconds,
            accepted_closure_count,
            torque_nm,
            status_code,
            reset_epoch,
            event_quality,
            source_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                event.timestamp,
                event.head_id,
                event.counter,
                event.counter_delta,
                event.elapsed_seconds,
                event.accepted_closure_count,
                event.torque_nm,
                event.status_code,
                event.reset_epoch,
                event.event_quality,
                event.source_file,
            )
            for event in events
        ),
    )
    connection.commit()
    return connection.total_changes - before


def mark_file_ingested(
    connection: sqlite3.Connection,
    source_file: str,
    events_detected: int,
    events_inserted: int,
) -> None:
    connection.execute(
        """
        INSERT INTO ingested_files (
            source_file, events_detected, events_inserted
        ) VALUES (?, ?, ?)
        ON CONFLICT(source_file) DO UPDATE SET
            processed_at = CURRENT_TIMESTAMP,
            events_detected = excluded.events_detected,
            events_inserted = excluded.events_inserted
        """,
        (source_file, events_detected, events_inserted),
    )
    connection.commit()


def query_events(
    connection: sqlite3.Connection,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    head_id: Optional[str] = None,
    event_quality: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Interroga gli eventi usando filtri opzionali e parametri SQL sicuri."""

    conditions: list[str] = []
    parameters: list[object] = []
    if start_time is not None:
        conditions.append("timestamp >= ?")
        parameters.append(start_time)
    if end_time is not None:
        conditions.append("timestamp <= ?")
        parameters.append(end_time)
    if head_id is not None:
        conditions.append("head_id = ?")
        parameters.append(head_id.upper())
    if event_quality is not None:
        conditions.append("event_quality = ?")
        parameters.append(event_quality)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return list(
        connection.execute(
            f"""
            SELECT *
            FROM closure_events
            {where_clause}
            ORDER BY timestamp, head_id
            """,
            parameters,
        )
    )
