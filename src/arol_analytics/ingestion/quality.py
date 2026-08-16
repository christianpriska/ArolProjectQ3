#Per-file and aggregate data-quality metrics.

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from arol_analytics.ingestion.schema import (
    GAP_FACTOR,
    TIMESTAMP_COLUMN,
    VALID_STATUS_CODES,
)

logger = logging.getLogger(__name__)


def strip_trailing_padding(df: pd.DataFrame, head_ids: list[str]) -> tuple[pd.DataFrame, int]:
    """Drop a trailing run of rows where every head's Count/AppTorque/Status is 0.

    This is a known export artifact (not a real machine reading — Count is a
    cumulative counter and cannot legitimately drop to 0 mid-archive). Only a
    *trailing, contiguous* all-zero run is stripped, so a genuine mid-file
    all-zero reading (if it ever occurred) is left untouched.
    """
    value_cols = [f"{h} {field}" for h in head_ids for field in ("Count", "AppTorque", "Status")]
    all_zero = (df[value_cols] == 0).all(axis=1)
    if not all_zero.iloc[-1]:
        return df, 0
    # length of the trailing True (all-zero) run
    reversed_zero = all_zero.iloc[::-1].to_numpy()
    run_len = len(df) if reversed_zero.all() else int(reversed_zero.argmin())
    if run_len <= 0:
        return df, 0
    return df.iloc[: len(df) - run_len].reset_index(drop=True), run_len


def compute_file_quality(df: pd.DataFrame, head_ids: list[str], filename: str) -> dict[str, Any]:
    ts = df[TIMESTAMP_COLUMN]
    first_ts, last_ts = ts.iloc[0], ts.iloc[-1]
    duration_seconds = (last_ts - first_ts).total_seconds()

    diffs = ts.diff().dropna().dt.total_seconds()
    median_interval = float(diffs.median()) if len(diffs) else float("nan")
    gaps = pd.DataFrame()
    if len(diffs) and not np.isnan(median_interval) and median_interval > 0:
        gap_mask = diffs > GAP_FACTOR * median_interval
        gap_idx = diffs[gap_mask].index
        gaps = pd.DataFrame(
            {
                "gap_seconds": diffs[gap_mask].values,
                "starts_after": ts.loc[gap_idx - 1].values,
                "ends_at": ts.loc[gap_idx].values,
            }
        )

    value_cols = [f"{h} {field}" for h in head_ids for field in ("Count", "AppTorque", "Status")]
    n_cells = df[value_cols].size
    n_missing = int(df[value_cols].isna().sum().sum())

    invalid_torque = {}
    status_distribution: dict[str, dict[int, int]] = {}
    unexpected_status: dict[str, dict[int, int]] = {}
    reset_events: dict[str, int] = {}
    torque_outliers: dict[str, int] = {}

    for h in head_ids:
        count_col, torque_col, status_col = df[f"{h} Count"], df[f"{h} AppTorque"], df[f"{h} Status"]

        n_negative = int((torque_col < 0).sum())
        incremented = count_col.diff() > 0
        n_zero_on_increment = int(((torque_col == 0) & incremented).sum())
        mean, std = torque_col.mean(), torque_col.std()
        if std and std > 0:
            n_outliers = int(((torque_col - mean).abs() > 3 * std).sum())
        else:
            n_outliers = 0
        invalid_torque[h] = {
            "negative": n_negative,
            "zero_on_increment": n_zero_on_increment,
            "outliers_gt_3sigma": n_outliers,
        }
        torque_outliers[h] = n_outliers

        vc = status_col.dropna().astype(int).value_counts().to_dict()
        status_distribution[h] = vc
        unexpected = {code: cnt for code, cnt in vc.items() if code not in VALID_STATUS_CODES}
        if unexpected:
            unexpected_status[h] = unexpected

        reset_events[h] = int((count_col.diff() < 0).sum())

    return {
        "file": filename,
        "rows": int(len(df)),
        "n_heads": len(head_ids),
        "first_timestamp": str(first_ts),
        "last_timestamp": str(last_ts),
        "duration_seconds": duration_seconds,
        "median_sampling_interval_seconds": median_interval,
        "n_gaps": int(len(gaps)),
        "gaps": gaps.astype(str).to_dict(orient="records") if len(gaps) else [],
        "missing_cells": n_missing,
        "missing_pct": (100.0 * n_missing / n_cells) if n_cells else 0.0,
        "invalid_torque_per_head": invalid_torque,
        "status_distribution_per_head": status_distribution,
        "unexpected_status_codes_per_head": unexpected_status,
        "counter_resets_per_head": reset_events,
    }


def aggregate_quality(
    file_reports: list[dict[str, Any]],
    schema_errors: list[dict[str, str]],
    padding_rows: dict[str, int],
    boundary_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    boundary_gaps = boundary_gaps or []
    if not file_reports:
        return {"files_processed": 0, "schema_errors": schema_errors, "boundary_gaps": boundary_gaps}

    all_first = min(r["first_timestamp"] for r in file_reports)
    all_last = max(r["last_timestamp"] for r in file_reports)
    total_rows = sum(r["rows"] for r in file_reports)
    total_missing = sum(r["missing_cells"] for r in file_reports)

    overall_status: dict[int, int] = {}
    overall_unexpected: dict[int, int] = {}
    overall_resets: dict[str, int] = {}
    overall_negative_torque = 0
    overall_outliers = 0
    for r in file_reports:
        for h, vc in r["status_distribution_per_head"].items():
            for code, cnt in vc.items():
                overall_status[code] = overall_status.get(code, 0) + cnt
        for h, vc in r["unexpected_status_codes_per_head"].items():
            for code, cnt in vc.items():
                overall_unexpected[code] = overall_unexpected.get(code, 0) + cnt
        for h, cnt in r["counter_resets_per_head"].items():
            overall_resets[h] = overall_resets.get(h, 0) + cnt
        for h, d in r["invalid_torque_per_head"].items():
            overall_negative_torque += d["negative"]
            overall_outliers += d["outliers_gt_3sigma"]

    return {
        "files_processed": len(file_reports),
        "schema_errors": schema_errors,
        "total_rows": total_rows,
        "time_range": {"first_timestamp": all_first, "last_timestamp": all_last},
        "missing_cells_total": total_missing,
        "missing_pct_overall": (100.0 * total_missing / sum(r["rows"] * r["n_heads"] * 3 for r in file_reports)) if file_reports else 0.0,
        "status_code_distribution": overall_status,
        "unexpected_status_codes": overall_unexpected,
        "counter_resets_per_head": overall_resets,
        "counter_resets_total": sum(overall_resets.values()),
        "negative_torque_total": overall_negative_torque,
        "torque_outliers_total": overall_outliers,
        "padding_rows_stripped_per_file": padding_rows,
        "padding_rows_stripped_total": sum(padding_rows.values()),
        "files_with_gaps": [{"file": r["file"], "n_gaps": r["n_gaps"], "gaps": r["gaps"]} for r in file_reports if r["n_gaps"] > 0],
        "boundary_gaps": boundary_gaps,
    }
