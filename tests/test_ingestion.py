"""Focused regression tests for closure reconstruction and cross-file zeros.

Run with:
    PYTHONPATH=src python tests/test_ingestion.py -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from arol_analytics.analytics.summary import dataset_summary, success_rate_analysis  # noqa: E402
from arol_analytics.ingestion.closures import CarryState, detect_closures  # noqa: E402
from arol_analytics.ingestion.normalize import dedupe_events  # noqa: E402
from arol_analytics.ingestion.pipeline import ingest_dataset  # noqa: E402
from arol_analytics.ingestion.quality import (  # noqa: E402
    count_trailing_all_zero_rows,
    mask_corrupted_count_readings,
)


HEADS = ["H01"]


def raw_frame(
    seconds: list[int],
    counts: list[int],
    torque: list[float] | None = None,
    status: list[int] | None = None,
) -> pd.DataFrame:
    n = len(counts)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [f"2026-01-01T00:00:{second:02d}" for second in seconds]
            ),
            "H01 Count": counts,
            "H01 AppTorque": torque if torque is not None else [2.5] * n,
            "H01 Status": status if status is not None else [65] * n,
        }
    )


def write_raw_csv(path: Path, seconds: list[int], counts: list[int], status: list[int]) -> None:
    torque = [2.5 if count else 0.0 for count in counts]
    frame = raw_frame(seconds, counts, torque=torque, status=status)
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S.000")
    frame.to_csv(path, index=False)


class ClosureDetectionTests(unittest.TestCase):
    def test_single_and_aggregated_jump(self) -> None:
        events, _ = detect_closures(
            raw_frame([0, 1, 2], [10, 11, 14]), HEADS, "sample.csv", CarryState()
        )

        self.assertEqual(events["counter_delta"].tolist(), [1.0, 3.0])
        self.assertEqual(events["inferred_closure_count"].tolist(), [1.0, 3.0])
        self.assertEqual(events["data_quality"].tolist(), ["single", "aggregated"])

    def test_gap_jump_is_tagged(self) -> None:
        events, _ = detect_closures(
            raw_frame([0, 1, 2, 3, 10], [10, 10, 10, 10, 13]),
            HEADS,
            "sample.csv",
            CarryState(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events.iloc[0]["counter_delta"], 3)
        self.assertEqual(events.iloc[0]["data_quality"], "gap")

    def test_reset_creates_new_segment_and_dedupe_keeps_reused_counter(self) -> None:
        events, _ = detect_closures(
            raw_frame([0, 1, 2, 3, 4], [10, 11, 0, 0, 1]),
            HEADS,
            "sample.csv",
            CarryState(),
        )

        self.assertEqual(events["counter"].tolist(), [11, 1])
        self.assertEqual(events["segment_id"].tolist(), [0, 1])
        deduped, removed = dedupe_events(events)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(removed, {})

    def test_internal_corrupted_zero_run_is_masked(self) -> None:
        raw = raw_frame([0, 1, 2, 3], [100, 0, 0, 103])
        masked, count = mask_corrupted_count_readings(raw, HEADS)
        events, _ = detect_closures(masked, HEADS, "sample.csv", CarryState())

        self.assertEqual(count, 2)
        self.assertTrue(masked["H01 Count"].iloc[1:3].isna().all())
        self.assertEqual(events["counter_delta"].tolist(), [3.0])

    def test_terminal_zeros_are_counted_but_not_removed(self) -> None:
        raw = raw_frame(
            [0, 1, 2],
            [100, 0, 0],
            torque=[2.5, 0.0, 0.0],
            status=[65, 0, 0],
        )

        self.assertEqual(count_trailing_all_zero_rows(raw, HEADS), 2)
        masked, count = mask_corrupted_count_readings(raw, HEADS)
        self.assertEqual(count, 0)
        self.assertEqual(masked["H01 Count"].tolist(), [100, 0, 0])


class CrossFilePipelineTests(unittest.TestCase):
    def test_reset_on_first_row_of_new_file_is_in_quality_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_raw_csv(root / "day01.csv", [0, 1], [99, 100], [65, 65])
            write_raw_csv(root / "day02.csv", [2, 3], [0, 1], [0, 65])

            result = ingest_dataset(str(root), output_dir=None)
            quality = result["data_quality_report"]

            self.assertEqual(quality["counter_resets_total"], 1)
            self.assertEqual(quality["counter_resets_per_head"], {"H01": 1})
            self.assertEqual(len(quality["counter_reset_events"]), 1)
            reset = quality["counter_reset_events"][0]
            self.assertEqual(reset["head_id"], "H01")
            self.assertEqual(reset["previous_count"], 100)
            self.assertEqual(reset["new_count"], 0)
            self.assertEqual(reset["source_file"], "day02.csv")

    def test_cross_file_genuine_reset_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_raw_csv(root / "day01.csv", [0, 1, 2], [100, 0, 0], [65, 0, 0])
            write_raw_csv(root / "day02.csv", [3, 4], [0, 1], [0, 65])

            result = ingest_dataset(str(root), output_dir=None)
            events = result["closure_events"]
            quality = result["data_quality_report"]

            self.assertEqual(events["counter"].tolist(), [1])
            self.assertEqual(events["inferred_closure_count"].tolist(), [1])
            self.assertEqual(quality["corrupted_rows_masked_total"], 0)
            self.assertEqual(quality["trailing_all_zero_rows_preserved_total"], 2)
            self.assertEqual(quality["counter_resets_total"], 1)
            self.assertEqual(quality["boundary_gaps"], [])

    def test_cross_file_corrupted_zero_run_uses_future_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_raw_csv(root / "day01.csv", [0, 1, 2], [100, 0, 0], [65, 0, 0])
            write_raw_csv(root / "day02.csv", [3, 4], [0, 103], [0, 65])

            result = ingest_dataset(str(root), output_dir=None)
            events = result["closure_events"]
            quality = result["data_quality_report"]

            self.assertEqual(events["counter"].tolist(), [103])
            self.assertEqual(events["counter_delta"].tolist(), [3])
            self.assertEqual(events["inferred_closure_count"].tolist(), [3])
            self.assertEqual(quality["corrupted_rows_masked_total"], 3)
            self.assertEqual(quality["counter_resets_total"], 0)


class OutcomeSemanticsTests(unittest.TestCase):
    def test_aggregated_event_contributes_one_observed_status(self) -> None:
        events = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T00:00:00", "2026-01-01T00:00:01"]),
                "head_id": ["H01", "H01"],
                "source_file": ["sample.csv", "sample.csv"],
                "classification": ["successful", "failed"],
                "status_code": [65, 4],
                "is_successful": [True, False],
                "is_reject": [False, True],
                "inferred_closure_count": [4, 1],
            }
        )

        rate = success_rate_analysis(events)["table"][0]
        summary = dataset_summary(events)

        self.assertEqual(rate["total_closures"], 2)
        self.assertEqual(rate["inferred_closures"], 5)
        self.assertEqual(rate["closures_without_individual_status"], 3)
        self.assertEqual(rate["success_rate_pct"], 50.0)
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["total_inferred_closures"], 5)
        self.assertEqual(summary["closures_without_individual_status"], 3)


if __name__ == "__main__":
    unittest.main()
