#Discovery, loading and schema validation of raw telemetry CSV files.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from arol_analytics.ingestion.schema import HEAD_COLUMN_RE, TIMESTAMP_COLUMN

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Raised when a raw file does not match the expected wide-format schema."""


@dataclass
class LoadedFile:
    path: Path
    df: pd.DataFrame
    head_ids: list[str]
    warnings: list[str] = field(default_factory=list)


def discover_files(data_path: str | Path) -> list[Path]:
    """Find all CSV files under data_path, sorted (sort order == chronological order)."""
    data_path = Path(data_path)
    if data_path.is_file():
        return [data_path]
    files = sorted(data_path.rglob("*.csv"))
    logger.info("discovered %d CSV files under %s", len(files), data_path)
    return files


def validate_schema(df: pd.DataFrame, filename: str) -> tuple[list[str], list[str]]:
    """Validate a raw dataframe against the expected wide-format schema.

    Returns (head_ids, warnings). Raises SchemaValidationError if the file is
    unusable (no timestamp column, or no valid per-head triplet found).
    """
    warnings: list[str] = []

    if TIMESTAMP_COLUMN not in df.columns:
        raise SchemaValidationError(f"{filename}: missing required '{TIMESTAMP_COLUMN}' column")

    heads_seen: dict[str, set[str]] = {}
    unmatched_columns: list[str] = []
    for col in df.columns:
        if col == TIMESTAMP_COLUMN:
            continue
        match = HEAD_COLUMN_RE.match(col)
        if not match:
            unmatched_columns.append(col)
            continue
        head_id, field_name = match.groups()
        heads_seen.setdefault(head_id, set()).add(field_name)

    if unmatched_columns:
        warnings.append(f"{filename}: {len(unmatched_columns)} column(s) not matching expected pattern: {unmatched_columns}")

    complete_heads = sorted(h for h, fields in heads_seen.items() if fields == {"Count", "AppTorque", "Status"})
    incomplete_heads = {h: fields for h, fields in heads_seen.items() if fields != {"Count", "AppTorque", "Status"}}
    if incomplete_heads:
        warnings.append(f"{filename}: incomplete head triplets (missing Count/AppTorque/Status): {incomplete_heads}")

    if not complete_heads:
        raise SchemaValidationError(f"{filename}: no complete H{{nn}} Count/AppTorque/Status triplet found")

    return complete_heads, warnings


def load_raw_file(path: Path) -> LoadedFile:
    """Read a raw CSV, parse the timestamp column, and validate its schema."""
    df = pd.read_csv(path)
    head_ids, warnings = validate_schema(df, path.name)

    ts = pd.to_datetime(df[TIMESTAMP_COLUMN], format="ISO8601", errors="coerce")
    n_bad_ts = int(ts.isna().sum())
    if n_bad_ts:
        warnings.append(f"{path.name}: {n_bad_ts} row(s) had unparsable timestamps (dropped)")
    df = df.assign(**{TIMESTAMP_COLUMN: ts})
    if n_bad_ts:
        df = df.dropna(subset=[TIMESTAMP_COLUMN]).reset_index(drop=True)

    for warning in warnings:
        logger.warning(warning)

    return LoadedFile(path=path, df=df, head_ids=head_ids, warnings=warnings)
