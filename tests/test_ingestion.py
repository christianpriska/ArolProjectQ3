# Layer 1 (ingestion) tests. Run with: PYTHONPATH=src pytest tests/test_ingestion.py -v
# (or plain `pytest tests/` -- conftest.py adds src/ to sys.path itself).

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from arol_analytics.ingestion.closures import CarryState, detect_closures
from arol_analytics.ingestion.idle import detect_idle_runs_for_file, finalize_idle_periods
from arol_analytics.ingestion.loader import SchemaValidationError, discover_files, load_raw_file, validate_schema
from arol_analytics.ingestion.normalize import add_status_fields, dedupe_events
from arol_analytics.ingestion.pipeline import ingest_dataset
from arol_analytics.ingestion.quality import count_trailing_all_zero_rows, mask_corrupted_count_readings
from arol_analytics.ingestion.schema import IDLE_MIN_ROWS, IDLE_MIN_SECONDS

ONE_HEAD = ["H01"]


def _one_head_frame(
    seconds: list[int],
    counts: list[int],
    torque: list[float] | None = None,
    status: list[int] | None = None,
) -> pd.DataFrame:
    n = len(counts)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([f"2026-01-01T00:00:{s:02d}" for s in seconds]),
            "H01 Count": counts,
            "H01 AppTorque": torque if torque is not None else [2.5] * n,
            "H01 Status": status if status is not None else [0] * n,
        }
    )


def _write_raw_csv(path: Path, seconds: list[int], counts: list[int], status: list[int]) -> None:
    torque = [2.5 if c else 0.0 for c in counts]
    frame = _one_head_frame(seconds, counts, torque=torque, status=status)
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S.000")
    frame.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Schema parsing
# ---------------------------------------------------------------------------


class TestSchemaParsing:
    def test_valid_wide_format_is_parsed(self, tmp_csv_files: Path) -> None:
        files = discover_files(tmp_csv_files)
        assert len(files) == 2
        loaded = load_raw_file(files[0])
        assert sorted(loaded.head_ids) == ["H01", "H02", "H03"]
        assert not loaded.warnings
        assert "timestamp" in loaded.df.columns
        assert pd.api.types.is_datetime64_any_dtype(loaded.df["timestamp"])

    def test_files_discovered_in_chronological_sort_order(self, tmp_csv_files: Path) -> None:
        files = discover_files(tmp_csv_files)
        assert [f.name for f in files] == ["synthetic_2026-01-01.csv", "synthetic_2026-01-02.csv"]

    def test_missing_timestamp_column_raises(self) -> None:
        df = pd.DataFrame({"H01 Count": [1, 2], "H01 AppTorque": [2.0, 2.0], "H01 Status": [0, 0]})
        with pytest.raises(SchemaValidationError):
            validate_schema(df, "bad.csv")

    def test_incomplete_head_triplet_warns_but_does_not_raise(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": ["2026-01-01T00:00:00"],
                "H01 Count": [1.0],
                "H01 AppTorque": [2.0],
                "H01 Status": [0.0],
                "H02 Count": [1.0],  # missing AppTorque/Status for H02
            }
        )
        heads, warnings = validate_schema(df, "partial.csv")
        assert heads == ["H01"]
        assert any("incomplete head triplets" in w for w in warnings)

    def test_no_complete_triplet_raises(self) -> None:
        df = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00"], "H01 Count": [1.0]})
        with pytest.raises(SchemaValidationError):
            validate_schema(df, "empty_heads.csv")


# ---------------------------------------------------------------------------
# Closure detection
# ---------------------------------------------------------------------------


class TestClosureDetection:
    def test_exact_closure_counts_per_head(self, synthetic_raw_df: pd.DataFrame) -> None:
        events, _ = detect_closures(synthetic_raw_df, ["H01", "H02", "H03"], "synthetic.csv", CarryState())
        assert len(events) == 1049
        counts = events["head_id"].value_counts().to_dict()
        assert counts == {"H01": 439, "H03": 390, "H02": 220}
        assert (events["counter_delta"] == 1).all()
        assert (events["data_quality"] == "single").all()

    def test_single_and_aggregated_jump(self) -> None:
        events, _ = detect_closures(_one_head_frame([0, 1, 2], [10, 11, 14]), ONE_HEAD, "s.csv", CarryState())
        assert events["counter_delta"].tolist() == [1.0, 3.0]
        assert events["inferred_closure_count"].tolist() == [1.0, 3.0]
        assert events["data_quality"].tolist() == ["single", "aggregated"]

    def test_gap_jump_is_tagged(self) -> None:
        events, _ = detect_closures(
            _one_head_frame([0, 1, 2, 3, 10], [10, 10, 10, 10, 13]), ONE_HEAD, "s.csv", CarryState()
        )
        assert len(events) == 1
        assert events.iloc[0]["counter_delta"] == 3
        assert events.iloc[0]["data_quality"] == "gap"

    def test_counter_decrement_is_a_reset_not_a_closure(self) -> None:
        """A counter decrement must never itself be recorded as a closure event."""
        events, carry = detect_closures(
            _one_head_frame([0, 1, 2], [10, 11, 5]), ONE_HEAD, "s.csv", CarryState()
        )
        # Only the 10->11 increment is a closure; 11->5 is a reset, not a closure.
        assert events["counter"].tolist() == [11]
        assert len(carry.reset_events) == 1
        assert carry.reset_events[0]["previous_count"] == 11
        assert carry.reset_events[0]["new_count"] == 5

    def test_reset_starts_a_new_segment(self) -> None:
        events, _ = detect_closures(
            _one_head_frame([0, 1, 2, 3, 4], [10, 11, 0, 0, 1]), ONE_HEAD, "s.csv", CarryState()
        )
        assert events["counter"].tolist() == [11, 1]
        assert events["segment_id"].tolist() == [0, 1]


# ---------------------------------------------------------------------------
# Corrupted-reading masking
# ---------------------------------------------------------------------------


class TestCorruptedReadingMasking:
    def test_internal_corrupted_zero_run_is_masked(self) -> None:
        raw = _one_head_frame([0, 1, 2, 3], [100, 0, 0, 103])
        masked, count = mask_corrupted_count_readings(raw, ONE_HEAD)
        assert count == 2
        assert masked["H01 Count"].iloc[1:3].isna().all()
        events, _ = detect_closures(masked, ONE_HEAD, "s.csv", CarryState())
        assert events["counter_delta"].tolist() == [3.0]

    def test_genuine_reset_zero_run_is_not_masked(self) -> None:
        raw = _one_head_frame([0, 1, 2, 3], [1000, 0, 0, 5])  # post (5) << pre (1000): genuine reset
        masked, count = mask_corrupted_count_readings(raw, ONE_HEAD)
        assert count == 0
        assert masked["H01 Count"].tolist() == [1000, 0, 0, 5]

    def test_terminal_zeros_are_counted_but_not_removed(self) -> None:
        raw = _one_head_frame([0, 1, 2], [100, 0, 0], torque=[2.5, 0.0, 0.0], status=[65, 0, 0])
        assert count_trailing_all_zero_rows(raw, ONE_HEAD) == 2
        masked, count = mask_corrupted_count_readings(raw, ONE_HEAD)
        assert count == 0  # no future value available in this single file -- left untouched, not dropped
        assert masked["H01 Count"].tolist() == [100, 0, 0]


# ---------------------------------------------------------------------------
# Duplicate removal
# ---------------------------------------------------------------------------


class TestDuplicateRemoval:
    def test_flicker_duplicate_within_a_segment_is_removed(self) -> None:
        """A duplicate (head_id, segment_id, counter) triple -- a flicker where
        the same closure gets logged twice -- must be removed, keeping the
        first occurrence and every other real event."""
        events = pd.DataFrame(
            {
                "timestamp": pd.to_datetime([f"2026-01-01T00:00:0{i}" for i in range(4)]),
                "head_id": ["H01"] * 4,
                "segment_id": [0, 0, 0, 0],
                "counter": [5, 6, 6, 7],  # counter=6 flickers twice
                "counter_delta": [1, 1, 1, 1],
                "inferred_closure_count": [1, 1, 1, 1],
                "data_quality": ["single"] * 4,
                "torque_nm": [2.0, 2.0, 2.0, 2.0],
                "status_code": [0, 0, 0, 0],
                "source_file": ["s.csv"] * 4,
            }
        )
        deduped, removed = dedupe_events(events)
        assert len(deduped) == 3
        assert deduped["counter"].tolist() == [5, 6, 7]
        assert removed == {"H01": 1}

    def test_counter_value_reused_after_a_real_reset_is_not_a_duplicate(self) -> None:
        """segment_id changes across a reset, so a counter value legitimately
        revisited after a reset must be kept, not deduplicated away."""
        events, _ = detect_closures(
            _one_head_frame([0, 1, 2, 3, 4], [10, 11, 0, 0, 1]), ONE_HEAD, "s.csv", CarryState()
        )
        deduped, removed = dedupe_events(events)
        assert len(deduped) == 2
        assert removed == {}

    def test_no_duplicates_returns_empty_removed_dict(self, synthetic_closure_events: pd.DataFrame) -> None:
        deduped, removed = dedupe_events(synthetic_closure_events)
        assert len(deduped) == len(synthetic_closure_events)
        assert removed == {}


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


class TestStatusClassification:
    @pytest.mark.parametrize(
        "status_code,expected_classification,expected_is_successful,expected_is_reject",
        [
            (0, "successful", True, False),
            (2, "no_load", False, False),
            (4, "other", False, False),  # documented, but not a reject code
            (9, "failed", False, True),
            (65, "failed", False, True),
        ],
    )
    def test_status_code_classification(
        self, status_code: int, expected_classification: str, expected_is_successful: bool, expected_is_reject: bool
    ) -> None:
        raw = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T00:00:00"]),
                "head_id": ["H01"],
                "counter": [1],
                "counter_delta": [1],
                "inferred_closure_count": [1],
                "data_quality": ["single"],
                "torque_nm": [2.0],
                "status_code": [status_code],
                "source_file": ["s.csv"],
            }
        )
        events = add_status_fields(raw)
        assert events.iloc[0]["classification"] == expected_classification
        assert bool(events.iloc[0]["is_successful"]) == expected_is_successful
        assert bool(events.iloc[0]["is_reject"]) == expected_is_reject


# ---------------------------------------------------------------------------
# Idle detection
# ---------------------------------------------------------------------------


class TestIdleDetection:
    def test_sustained_all_heads_idle_produces_one_period(self, synthetic_raw_df: pd.DataFrame) -> None:
        runs, pending = detect_idle_runs_for_file(synthetic_raw_df, ["H01", "H02", "H03"], None)
        assert pending is None
        idle_periods = finalize_idle_periods(runs, IDLE_MIN_ROWS, IDLE_MIN_SECONDS)
        assert len(idle_periods) == 1
        row = idle_periods.iloc[0]
        assert row["start_time"] == pd.Timestamp("2026-01-01 00:05:00")
        assert row["end_time"] == pd.Timestamp("2026-01-01 00:05:59")
        assert row["duration_seconds"] == 59.0

    def test_short_idle_below_threshold_is_dropped(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=5, freq="s"),
                "H01 Status": [2, 2, 2, 2, 2],
                "H01 Count": [1, 1, 1, 1, 1],
                "H01 AppTorque": [0.0] * 5,
            }
        )
        runs, _ = detect_idle_runs_for_file(df, ["H01"], None)
        idle_periods = finalize_idle_periods(runs, IDLE_MIN_ROWS, IDLE_MIN_SECONDS)
        assert idle_periods.empty  # 5 rows/seconds < IDLE_MIN_ROWS=30 and < IDLE_MIN_SECONDS=30.0

    def test_not_all_heads_idle_is_not_an_idle_period(self) -> None:
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=40, freq="s"),
                "H01 Status": [2] * 40,
                "H02 Status": [0] * 40,  # H02 is still producing -- machine is not idle
            }
        )
        runs, _ = detect_idle_runs_for_file(df, ["H01", "H02"], None)
        assert runs == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dataframe_detect_closures(self) -> None:
        empty = pd.DataFrame(
            {
                "timestamp": pd.to_datetime([]),
                "H01 Count": pd.Series(dtype=float),
                "H01 AppTorque": pd.Series(dtype=float),
                "H01 Status": pd.Series(dtype=float),
            }
        )
        events, carry = detect_closures(empty, ONE_HEAD, "s.csv", CarryState())
        assert events.empty
        assert carry.last_count == {}

    def test_single_row_no_closure_without_prior_state(self) -> None:
        """A single row has no prior value to compare against in a fresh
        CarryState(), so it can never itself be a closure."""
        events, carry = detect_closures(_one_head_frame([0], [42]), ONE_HEAD, "s.csv", CarryState())
        assert events.empty
        assert carry.last_count == {"H01": 42.0}

    def test_single_row_is_a_closure_when_carried_from_a_previous_file(self) -> None:
        prior_state = CarryState(last_count={"H01": 40.0})
        events, _ = detect_closures(_one_head_frame([0], [42]), ONE_HEAD, "s.csv", prior_state)
        assert len(events) == 1
        assert events.iloc[0]["counter_delta"] == 2

    def test_missing_columns_raises_schema_validation_error(self) -> None:
        df = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00"]})
        with pytest.raises(SchemaValidationError):
            validate_schema(df, "no_heads.csv")

    def test_ingest_dataset_raises_on_no_csv_files(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            ingest_dataset(str(empty_dir), output_dir=None)


# ---------------------------------------------------------------------------
# Cross-file (pipeline-level) behavior
# ---------------------------------------------------------------------------


class TestCrossFilePipeline:
    def test_full_pipeline_runs_on_synthetic_two_file_archive(self, tmp_csv_files: Path) -> None:
        result = ingest_dataset(str(tmp_csv_files), output_dir=None)
        events = result["closure_events"]
        idle = result["idle_periods"]
        quality = result["data_quality_report"]

        assert quality["files_processed"] == 2
        assert not quality["schema_errors"]
        # Cross-file continuity: the split at row 250 (mid-file-2 idle block)
        # must not change the totals from a single-file run.
        assert len(events) == 1049
        assert events["head_id"].value_counts().to_dict() == {"H01": 439, "H03": 390, "H02": 220}
        assert len(idle) == 1

    def test_streaming_pipeline_matches_in_memory_pipeline(self, tmp_csv_files: Path, tmp_path: Path) -> None:
        expected = ingest_dataset(str(tmp_csv_files), output_dir=None)
        output_dir = tmp_path / "streamed"

        streamed = ingest_dataset(str(tmp_csv_files), output_dir=str(output_dir), streaming=True)
        actual = pd.read_parquet(output_dir / "closure_events.parquet")

        sort_columns = ["head_id", "timestamp", "counter"]
        expected_events = expected["closure_events"].sort_values(sort_columns).reset_index(drop=True)
        actual = actual.sort_values(sort_columns).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected_events)
        assert streamed["closure_events"].empty
        assert streamed["closure_event_count"] == len(expected_events)
        assert streamed["data_quality_report"] == expected["data_quality_report"]
        assert streamed["ingestion_summary"] == expected["ingestion_summary"]
        assert not (output_dir / ".closure_events.parquet.tmp").exists()

    def test_reset_on_first_row_of_new_file_is_recorded(self, tmp_path: Path) -> None:
        root = tmp_path / "raw"
        root.mkdir()
        _write_raw_csv(root / "day01.csv", [0, 1], [99, 100], [0, 0])
        _write_raw_csv(root / "day02.csv", [2, 3], [0, 1], [0, 0])

        result = ingest_dataset(str(root), output_dir=None)
        quality = result["data_quality_report"]

        assert quality["counter_resets_total"] == 1
        assert quality["counter_resets_per_head"] == {"H01": 1}
        reset = quality["counter_reset_events"][0]
        assert reset["head_id"] == "H01"
        assert reset["previous_count"] == 100
        assert reset["new_count"] == 0
        assert reset["source_file"] == "day02.csv"

    def test_corrupted_zero_run_across_a_file_boundary_uses_future_value(self, tmp_path: Path) -> None:
        root = tmp_path / "raw"
        root.mkdir()
        _write_raw_csv(root / "day01.csv", [0, 1, 2], [100, 0, 0], [0, 0, 0])
        _write_raw_csv(root / "day02.csv", [3, 4], [0, 103], [0, 0])  # recovers >= 100 -> corrupted, not reset

        result = ingest_dataset(str(root), output_dir=None)
        events = result["closure_events"]
        quality = result["data_quality_report"]

        assert events["counter"].tolist() == [103]
        assert events["counter_delta"].tolist() == [3]
        assert quality["corrupted_rows_masked_total"] == 3
        assert quality["counter_resets_total"] == 0

    def test_genuine_reset_across_a_file_boundary_is_preserved(self, tmp_path: Path) -> None:
        root = tmp_path / "raw"
        root.mkdir()
        _write_raw_csv(root / "day01.csv", [0, 1, 2], [1000, 0, 0], [0, 0, 0])
        _write_raw_csv(root / "day02.csv", [3, 4], [0, 5], [0, 0])  # recovers near 0 -> genuine reset

        result = ingest_dataset(str(root), output_dir=None)
        events = result["closure_events"]
        quality = result["data_quality_report"]

        assert events["counter"].tolist() == [5]
        assert quality["corrupted_rows_masked_total"] == 0
        assert quality["counter_resets_total"] == 1
