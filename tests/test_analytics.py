# Layer 2 (analytics) tests. Run with: PYTHONPATH=src pytest tests/test_analytics.py -v

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
import pytest

from arol_analytics.analytics import (
    anomaly_detection,
    capping_speed_analysis,
    dataset_summary,
    failure_analysis,
    generate_kpi_dashboard,
    head_comparison,
    idle_analysis,
    success_rate_analysis,
    torque_statistics,
)
from arol_analytics.analytics._common import format_percentage
from arol_analytics.ingestion.normalize import add_status_fields, compute_derived_metrics


# ---------------------------------------------------------------------------
# success_rate_analysis
# ---------------------------------------------------------------------------


class TestSuccessRateAnalysis:
    def test_near_perfect_rate_is_not_displayed_as_100_percent(self) -> None:
        assert format_percentage(99.996539) == "99.9965%"
        assert format_percentage(100.0) == "100.00%"

    def test_overall_rate_from_90_of_100(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        successes = event_block_factory("H50", "2026-04-01T00:00:00", 90, 1, 0, 2.0, "s.csv")
        failures = event_block_factory("H50", "2026-04-01T02:00:00", 10, 1, 65, 2.0, "s.csv", counter_start=1000)
        events = compute_derived_metrics(add_status_fields(pd.concat([successes, failures], ignore_index=True)))

        result = success_rate_analysis(events, group_by="overall")

        assert len(result["table"]) == 1
        assert result["table"][0]["success_rate_pct"] == pytest.approx(90.0)
        assert result["table"][0]["successful"] == 90
        assert result["table"][0]["failed"] == 10

    def test_per_head_rates_100_50_0(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = success_rate_analysis(synthetic_closure_events, group_by="per_head")
        rates = {row["group"]: row["success_rate_pct"] for row in result["table"]}
        assert rates == {"H01": pytest.approx(100.0), "H02": pytest.approx(50.0), "H03": pytest.approx(0.0)}
        # ranked worst-to-best
        ranked = sorted(result["table"], key=lambda r: r["rank_worst_to_best"])
        assert [r["group"] for r in ranked] == ["H03", "H02", "H01"]

    def test_no_load_excluded_from_rate(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        successes = event_block_factory("H51", "2026-04-01T00:00:00", 10, 1, 0, 2.0, "s.csv")
        no_load = event_block_factory("H51", "2026-04-01T01:00:00", 5, 1, 2, 0.0, "s.csv", counter_start=100)
        events = compute_derived_metrics(add_status_fields(pd.concat([successes, no_load], ignore_index=True)))

        result = success_rate_analysis(events, group_by="overall")
        assert result["table"][0]["success_rate_pct"] == pytest.approx(100.0)
        assert result["table"][0]["total_closures"] == 10  # no-load rows excluded before grouping

    def test_invalid_group_by_raises(self, synthetic_closure_events: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            success_rate_analysis(synthetic_closure_events, group_by="not_a_real_grouping")


# ---------------------------------------------------------------------------
# torque_statistics
# ---------------------------------------------------------------------------


class TestTorqueStatistics:
    def test_known_mean_and_std(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        # 50 values at 2.4, 1 at 2.5, 50 at 2.6 -> mean exactly 2.5, sample std exactly 0.1.
        torque_values = [2.4] * 50 + [2.5] * 1 + [2.6] * 50
        events = event_block_factory("H52", "2026-03-01T00:00:00", 101, 1, 0, torque_values, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))

        result = torque_statistics(events, filter_status="successful_only", group_by="overall")

        row = result["table"][0]
        assert row["mean"] == pytest.approx(2.5)
        assert row["std"] == pytest.approx(0.1)
        assert row["count"] == 101

    def test_all_status_sets_bimodal_warning(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = torque_statistics(synthetic_closure_events, filter_status="all", group_by="overall")
        assert result["warning"] is not None
        assert "bimodal" in result["warning"]

    def test_successful_only_has_no_warning(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = torque_statistics(synthetic_closure_events, filter_status="successful_only", group_by="overall")
        assert result["warning"] is None

    def test_invalid_filter_status_raises(self, synthetic_closure_events: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            torque_statistics(synthetic_closure_events, filter_status="bogus")


# ---------------------------------------------------------------------------
# time_range filtering
# ---------------------------------------------------------------------------


class TestTimeRangeFiltering:
    def test_february_only_returns_expected_subset(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = success_rate_analysis(
            synthetic_closure_events, group_by="per_head", time_range=("2026-02-01", "2026-02-28")
        )
        totals = {row["group"]: row["total_closures"] for row in result["table"]}
        assert totals == {"H02": 35, "H03": 50}  # H01 is entirely in January
        assert sum(totals.values()) == 85

    def test_january_only_returns_expected_subset(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = success_rate_analysis(
            synthetic_closure_events, group_by="per_head", time_range=("2026-01-01", "2026-01-31")
        )
        totals = {row["group"]: row["total_closures"] for row in result["table"]}
        assert totals == {"H01": 80, "H02": 35}
        assert sum(totals.values()) == 115


# ---------------------------------------------------------------------------
# head_comparison
# ---------------------------------------------------------------------------


class TestHeadComparison:
    def test_ranking_matches_known_profiles(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = head_comparison(synthetic_closure_events)
        by_rank = {row["head_id"]: row["rank_success_rate"] for row in result["table"]}
        assert by_rank["H01"] < by_rank["H02"] < by_rank["H03"]  # H01=100% best, H03=0% worst

    def test_busiest_and_quietest_head(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = head_comparison(synthetic_closure_events)
        assert result["busiest_head"] == {"head_id": "H01", "total_closures": 80}
        assert result["quietest_head"] == {"head_id": "H03", "total_closures": 50}

    def test_empty_events_returns_empty_table(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = head_comparison(synthetic_closure_events.iloc[0:0])
        assert result["table"] == []
        assert result["flagged_heads"] == []


# ---------------------------------------------------------------------------
# anomaly_detection
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    def test_threshold_method_detects_exactly_injected_outliers(
        self, event_block_factory: Callable[..., pd.DataFrame]
    ) -> None:
        baseline = event_block_factory("H53", "2026-05-01T00:00:00", 100, 1, 0, 2.0, "s.csv")
        outliers = event_block_factory(
            "H53", "2026-05-01T02:00:00", 5, 1, 0, [10.0, 10.5, 11.0, 0.01, 0.02], "s.csv", counter_start=200
        )
        events = compute_derived_metrics(add_status_fields(pd.concat([baseline, outliers], ignore_index=True)))

        result = anomaly_detection(events, method="threshold", threshold_range=(1.5, 2.5))

        assert result["total_anomalies"] == 5
        flagged_torques = sorted(a["torque_nm"] for a in result["anomalies"])
        assert flagged_torques == pytest.approx([0.01, 0.02, 10.0, 10.5, 11.0])

    def test_zscore_method_runs_and_returns_expected_keys(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = anomaly_detection(synthetic_closure_events, method="zscore")
        assert {"summary", "total_anomalies", "anomalies", "anomaly_count_per_head"} <= result.keys()
        assert result["total_anomalies"] >= 0

    def test_threshold_method_without_range_raises(self, synthetic_closure_events: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            anomaly_detection(synthetic_closure_events, method="threshold")

    def test_invalid_method_raises(self, synthetic_closure_events: pd.DataFrame) -> None:
        with pytest.raises(ValueError):
            anomaly_detection(synthetic_closure_events, method="not_a_method")


# ---------------------------------------------------------------------------
# failure_analysis
# ---------------------------------------------------------------------------


class TestFailureAnalysis:
    def test_consecutive_failure_burst_is_detected(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        # 10 successes, 3 consecutive failures, 10 more successes.
        status_sequence = [0] * 10 + [65, 65, 65] + [0] * 10
        events = event_block_factory("H54", "2026-06-01T00:00:00", len(status_sequence), 1, status_sequence, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))

        result = failure_analysis(events)

        assert len(result["consecutive_failure_bursts"]) == 1
        burst = result["consecutive_failure_bursts"][0]
        assert burst["head_id"] == "H54"
        assert burst["count"] == 3
        assert burst["failure_types"] == [65]

    def test_two_failures_in_a_row_is_not_a_burst(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        status_sequence = [0] * 5 + [65, 65] + [0] * 5  # only 2 in a row, min_run=3
        events = event_block_factory("H55", "2026-06-01T00:00:00", len(status_sequence), 1, status_sequence, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))

        result = failure_analysis(events)
        assert result["consecutive_failure_bursts"] == []

    def test_failure_distribution_by_status_code(self, synthetic_closure_events: pd.DataFrame) -> None:
        result = failure_analysis(synthetic_closure_events)
        # every injected failure in the fixture uses status 65
        assert result["failure_distribution_by_status_code"] == {65: 85}

    def test_no_failures_returns_empty_result(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        events = event_block_factory("H56", "2026-06-01T00:00:00", 10, 1, 0, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))
        result = failure_analysis(events)
        assert result["failure_distribution_by_status_code"] == {}

    def test_failure_rate_by_hour_of_day_flags_a_concentrated_hour(
        self, event_block_factory: Callable[..., pd.DataFrame]
    ) -> None:
        # One full day at 1-minute cadence; every closure in hour 03 fails, the
        # rest succeed -- a clear time-of-day effect the chi-square test must catch.
        status_sequence = [65 if (i // 60) % 24 == 3 else 0 for i in range(1440)]
        events = event_block_factory("H07", "2026-06-01T00:00:00", 1440, 1, status_sequence, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))

        result = failure_analysis(events)
        by_hour = result["failure_rate_by_hour_of_day"]

        assert len(by_hour["table"]) == 24
        hour_3 = next(row for row in by_hour["table"] if row["hour"] == 3)
        assert hour_3["n_events"] == 60 and hour_3["n_failures"] == 60
        assert hour_3["failure_rate_pct"] == 100.0

        assert by_hour["test"]["significant"] is True
        assert by_hour["test"]["peak_hour"] == 3
        assert "time of day" in result["summary"]


# ---------------------------------------------------------------------------
# capping_speed_analysis
# ---------------------------------------------------------------------------


class TestCappingSpeedAnalysis:
    def test_first_post_idle_speed_is_excluded_without_losing_its_closure(self) -> None:
        events = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-01-01T09:59:58",
                        "2026-01-01T12:00:02",
                        "2026-01-01T12:00:04",
                    ]
                ),
                "head_id": ["H01", "H01", "H01"],
                "status_code": [0, 0, 0],
                "inferred_closure_count": [1, 1, 1],
                "data_quality": ["single", "single", "single"],
                "time_since_last_closure": [2.0, 7204.0, 2.0],
                "capping_speed_pph": [1800.0, 0.5, 1800.0],
            }
        )
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T10:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T12:00:00"]),
                "duration_seconds": [7200.0],
            }
        )

        result = capping_speed_analysis(events, idle_periods=idle_periods)

        assert result["idle_affected_speed_samples_excluded"] == 1
        assert result["per_head_average_speed_pph"]["mean"] == pytest.approx(1800.0)
        noon = next(row for row in result["machine_wide_timeline"] if row["hour"] == "2026-01-01 12:00:00")
        assert noon["pieces_per_hour"] == pytest.approx(2.0)

    def test_post_idle_speed_is_kept_when_exclusion_is_disabled(self) -> None:
        events = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T09:59:58", "2026-01-01T12:00:02"]),
                "head_id": ["H01", "H01"],
                "status_code": [0, 0],
                "inferred_closure_count": [1, 1],
                "data_quality": ["single", "single"],
                "time_since_last_closure": [2.0, 7204.0],
                "capping_speed_pph": [1800.0, 0.5],
            }
        )
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T10:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T12:00:00"]),
                "duration_seconds": [7200.0],
            }
        )

        result = capping_speed_analysis(events, idle_periods=idle_periods, exclude_idle=False)

        assert result["idle_affected_speed_samples_excluded"] == 0
        assert result["per_head_average_speed_pph"]["mean"] == pytest.approx(900.25)

    def test_first_event_in_filter_is_kept_when_its_speed_does_not_cross_idle(self) -> None:
        events = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T12:00:04"]),
                "head_id": ["H01"],
                "status_code": [0],
                "inferred_closure_count": [1],
                "data_quality": ["single"],
                "time_since_last_closure": [2.0],
                "capping_speed_pph": [1800.0],
            }
        )
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T10:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T12:00:00"]),
                "duration_seconds": [7200.0],
            }
        )

        result = capping_speed_analysis(
            events,
            idle_periods=idle_periods,
            time_range=("2026-01-01T12:00:03", "2026-01-01T12:00:05"),
        )

        assert result["idle_affected_speed_samples_excluded"] == 0
        assert result["per_head_average_speed_pph"]["mean"] == pytest.approx(1800.0)


# ---------------------------------------------------------------------------
# idle_analysis
# ---------------------------------------------------------------------------


class TestIdleAnalysis:
    def test_known_utilization_rate(self, synthetic_idle_periods: pd.DataFrame) -> None:
        result = idle_analysis(
            synthetic_idle_periods, time_range=("2026-01-01T00:00:00", "2026-01-01T10:00:00")
        )
        assert result["utilization_rate"] == pytest.approx(0.7)
        assert result["idle_period_stats"]["count"] == 3
        assert result["idle_period_stats"]["total_idle_seconds"] == pytest.approx(10800.0)

    def test_partial_idle_overlap_is_clipped_to_requested_range(self) -> None:
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T00:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T02:00:00"]),
                "duration_seconds": [7200.0],
            }
        )

        result = idle_analysis(
            idle_periods,
            time_range=("2026-01-01T01:00:00", "2026-01-01T03:00:00"),
        )

        assert result["utilization_rate"] == pytest.approx(0.5)
        assert result["idle_period_stats"]["count"] == 1
        assert result["idle_period_stats"]["total_idle_seconds"] == pytest.approx(3600.0)
        assert result["hourly_idle_pattern"][1] == pytest.approx(3600.0)
        assert result["top_10_longest_idle_periods"] == [
            {
                "start_time": "2026-01-01 01:00:00",
                "end_time": "2026-01-01 02:00:00",
                "duration_seconds": 3600.0,
            }
        ]

    def test_idle_spanning_entire_requested_range_is_fully_counted(self) -> None:
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T00:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T04:00:00"]),
                "duration_seconds": [14400.0],
            }
        )

        result = idle_analysis(
            idle_periods,
            time_range=("2026-01-01T01:00:00", "2026-01-01T03:00:00"),
        )

        assert result["utilization_rate"] == pytest.approx(0.0)
        assert result["idle_period_stats"]["total_idle_seconds"] == pytest.approx(7200.0)

    def test_no_idle_overlap_means_full_utilization_for_requested_range(self) -> None:
        idle_periods = pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-01-01T00:00:00"]),
                "end_time": pd.to_datetime(["2026-01-01T01:00:00"]),
                "duration_seconds": [3600.0],
            }
        )

        result = idle_analysis(
            idle_periods,
            time_range=("2026-01-01T02:00:00", "2026-01-01T04:00:00"),
        )

        assert result["utilization_rate"] == pytest.approx(1.0)
        assert result["idle_period_stats"]["count"] == 0
        assert result["idle_period_stats"]["total_idle_seconds"] == pytest.approx(0.0)

    def test_empty_idle_periods(self) -> None:
        empty = pd.DataFrame(columns=["start_time", "end_time", "duration_seconds"])
        result = idle_analysis(empty)
        assert result["utilization_rate"] != result["utilization_rate"]  # NaN
        assert result["idle_period_stats"] == {}


# ---------------------------------------------------------------------------
# generate_kpi_dashboard
# ---------------------------------------------------------------------------


class TestKpiDashboard:
    def test_returns_all_expected_kpi_keys(
        self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame
    ) -> None:
        result = generate_kpi_dashboard(synthetic_closure_events, synthetic_idle_periods)
        expected_keys = {
            "overall_success_rate_pct",
            "mean_torque_nm",
            "torque_stability_std_across_heads",
            "machine_wide_throughput_pph",
            "per_head_average_speed_pph",
            "utilization_rate_pct",
            "worst_head",
            "best_head",
            "n_anomalies",
            "total_idle_hours",
        }
        assert expected_keys <= result["kpis"].keys()
        assert isinstance(result["summary"], str) and result["summary"]

    def test_kpi_labels_explain_success_speed_and_utilization_denominators(
        self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame
    ) -> None:
        result = generate_kpi_dashboard(synthetic_closure_events, synthetic_idle_periods)
        expected_window_h = (
            synthetic_closure_events["timestamp"].max() - synthetic_closure_events["timestamp"].min()
        ).total_seconds() / 3600.0

        assert result["kpis"]["observation_window_hours"] == pytest.approx(expected_window_h)
        assert result["kpis"]["production_hours_with_closures"] > 0
        assert "no-load excluded" in result["summary"]
        assert "hours with recorded closures" in result["summary"]
        assert "observation window" in result["summary"]

    def test_worst_and_best_head_match_known_profile(
        self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame
    ) -> None:
        result = generate_kpi_dashboard(synthetic_closure_events, synthetic_idle_periods)
        assert result["kpis"]["worst_head"]["head_id"] == "H03"
        assert result["kpis"]["best_head"]["head_id"] == "H01"


# ---------------------------------------------------------------------------
# Edge cases (shared across tools)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_dataframe_does_not_raise(self, synthetic_closure_events: pd.DataFrame) -> None:
        empty = synthetic_closure_events.iloc[0:0]
        assert dataset_summary(empty)["total_events"] == 0
        assert success_rate_analysis(empty)["table"] == []
        assert torque_statistics(empty)["table"] == []
        assert anomaly_detection(empty)["total_anomalies"] == 0
        assert failure_analysis(empty)["failure_distribution_by_status_code"] == {}

    def test_single_event(self, event_block_factory: Callable[..., pd.DataFrame]) -> None:
        events = event_block_factory("H57", "2026-07-01T00:00:00", 1, 1, 0, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))

        summary = dataset_summary(events)
        assert summary["total_events"] == 1

        rate = success_rate_analysis(events, group_by="overall")
        assert rate["table"][0]["success_rate_pct"] == pytest.approx(100.0)

    def test_all_same_status_no_variance_no_outliers_flagged(
        self, event_block_factory: Callable[..., pd.DataFrame]
    ) -> None:
        events = event_block_factory("H58", "2026-07-01T00:00:00", 20, 1, 0, 2.0, "s.csv")  # constant torque
        events = compute_derived_metrics(add_status_fields(events))

        stats = torque_statistics(events, filter_status="successful_only", group_by="overall")
        assert stats["table"][0]["std"] == 0.0

        anomalies = anomaly_detection(events, method="zscore")
        assert anomalies["total_anomalies"] == 0  # zero std -> nothing can be flagged
