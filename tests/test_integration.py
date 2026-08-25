# End-to-end integration tests: synthetic raw CSVs -> Layer 1 ingestion ->
# Layer 2 analytics, checking that outputs are internally consistent.
# Run with: PYTHONPATH=src pytest tests/test_integration.py -v

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from arol_analytics.analytics import (
    dataset_summary,
    generate_kpi_dashboard,
    head_comparison,
    load_closure_events,
    load_idle_periods,
    success_rate_analysis,
)
from arol_analytics.ingestion.pipeline import ingest_dataset

HEADS = ["H01", "H02", "H03"]
ROWS_PER_DAY = 200
N_DAYS = 5
STEP = {"H01": 1, "H02": 2, "H03": 3}  # head increments its Count every Nth row


@pytest.fixture
def synthetic_archive(tmp_path: Path) -> Path:
    """5 daily raw CSVs, 3 heads, 200 rows/day (1,000 rows total), each head
    incrementing its own Count at a different, known rate (every row / every
    2nd row / every 3rd row) continuously across all 5 files. All statuses are
    0 (successful) -- this fixture exercises the full pipeline end to end, not
    Layer-1 edge cases (those are covered in test_ingestion.py).

    Verified directly against ingest_dataset: 1,831 total closure events
    (H01=999, H02=499, H03=333) -- one fewer than each head's final counter
    value, since the very first row of the very first file has no prior value
    to compare against (see closures.detect_closures) and is therefore never
    itself a closure.
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    counters = {h: 0 for h in HEADS}
    for day in range(N_DAYS):
        start = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        timestamps = [start + pd.Timedelta(seconds=i) for i in range(ROWS_PER_DAY)]
        data: dict[str, list] = {"timestamp": [t.strftime("%Y-%m-%dT%H:%M:%S.000") for t in timestamps]}
        counts = {h: [] for h in HEADS}
        for i in range(ROWS_PER_DAY):
            global_row = day * ROWS_PER_DAY + i
            for h in HEADS:
                if global_row % STEP[h] == 0:
                    counters[h] += 1
                counts[h].append(counters[h])
        for h in HEADS:
            data[f"{h} Count"] = counts[h]
            data[f"{h} AppTorque"] = [2.0] * ROWS_PER_DAY
            data[f"{h} Status"] = [0] * ROWS_PER_DAY
        pd.DataFrame(data).to_csv(raw_dir / f"synthetic_2026-01-{day + 1:02d}.csv", index=False)

    return raw_dir


class TestIngestionOutputs:
    def test_parquet_outputs_exist_with_expected_row_counts(self, synthetic_archive: Path, tmp_path: Path) -> None:
        output_dir = tmp_path / "processed"
        result = ingest_dataset(str(synthetic_archive), output_dir=str(output_dir))

        assert (output_dir / "closure_events.parquet").exists()
        assert (output_dir / "idle_periods.parquet").exists()
        assert (output_dir / "data_quality_report.json").exists()
        assert (output_dir / "ingestion_summary.md").exists()

        assert len(result["closure_events"]) == 1831
        assert result["closure_events"]["head_id"].value_counts().to_dict() == {"H01": 999, "H02": 499, "H03": 333}
        assert result["data_quality_report"]["files_processed"] == 5
        assert not result["data_quality_report"]["schema_errors"]

    def test_reloaded_parquet_matches_in_memory_result(self, synthetic_archive: Path, tmp_path: Path) -> None:
        output_dir = tmp_path / "processed"
        result = ingest_dataset(str(synthetic_archive), output_dir=str(output_dir))

        reloaded = load_closure_events(output_dir)
        assert len(reloaded) == len(result["closure_events"])
        assert reloaded["head_id"].nunique() == 3


class TestAnalyticsConsistency:
    @pytest.fixture
    def processed(self, synthetic_archive: Path, tmp_path: Path) -> Path:
        output_dir = tmp_path / "processed"
        ingest_dataset(str(synthetic_archive), output_dir=str(output_dir))
        return output_dir

    def test_dataset_summary_total_matches_ingestion_row_count(self, processed: Path) -> None:
        events = load_closure_events(processed)
        summary = dataset_summary(events)
        assert summary["total_events"] == 1831
        assert summary["n_heads"] == 3

    def test_head_comparison_totals_sum_to_dataset_total(self, processed: Path) -> None:
        events = load_closure_events(processed)
        summary = dataset_summary(events)
        comparison = head_comparison(events)

        summed_per_head = sum(row["total_closures"] for row in comparison["table"])
        assert summed_per_head == summary["total_events"]

    def test_success_rate_consistent_between_tools(self, processed: Path) -> None:
        """success_rate_analysis(overall) and generate_kpi_dashboard's own KPI
        must report the identical number -- the dashboard calls the same
        success_rate_analysis internally rather than recomputing it."""
        events = load_closure_events(processed)
        idle_periods = load_idle_periods(processed)

        overall = success_rate_analysis(events, group_by="overall")
        dashboard = generate_kpi_dashboard(events, idle_periods)

        assert dashboard["kpis"]["overall_success_rate_pct"] == pytest.approx(
            overall["table"][0]["success_rate_pct"]
        )
        # every closure in this fixture is status 0 (successful)
        assert overall["table"][0]["success_rate_pct"] == pytest.approx(100.0)

    def test_dashboard_worst_and_best_head_are_consistent_with_per_head_rates(self, processed: Path) -> None:
        events = load_closure_events(processed)
        idle_periods = load_idle_periods(processed)

        per_head = success_rate_analysis(events, group_by="per_head")
        dashboard = generate_kpi_dashboard(events, idle_periods)

        rates_by_head = {row["group"]: row["success_rate_pct"] for row in per_head["table"]}
        worst = dashboard["kpis"]["worst_head"]
        best = dashboard["kpis"]["best_head"]
        assert rates_by_head[worst["head_id"]] == pytest.approx(worst["success_rate_pct"])
        assert rates_by_head[best["head_id"]] == pytest.approx(best["success_rate_pct"])

    def test_no_idle_periods_in_this_archive(self, processed: Path) -> None:
        """No head ever reports status=2 in this fixture, so no idle period
        should be detected -- idle_periods.parquet should exist but be empty."""
        idle_periods = load_idle_periods(processed)
        assert idle_periods.empty
