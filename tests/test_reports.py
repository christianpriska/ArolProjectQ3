# Report-template tests. Run with: PYTHONPATH=src pytest tests/test_reports.py -v

from __future__ import annotations

import pandas as pd
import pytest

from arol_analytics.reports import REPORT_TYPES, render_anomaly_report, render_head_comparison_report, render_kpi_dashboard_report


class TestKpiDashboardReport:
    def test_renders_expected_sections(self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame) -> None:
        report = render_kpi_dashboard_report(synthetic_closure_events, synthetic_idle_periods)
        assert report.startswith("# AROL Capping Machine — KPI Dashboard")
        for heading in ("## Key Performance Indicators", "## Head Performance Summary", "## Notable Findings", "## Data Scope"):
            assert heading in report

    def test_includes_every_head_in_the_ranking_table(self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame) -> None:
        report = render_kpi_dashboard_report(synthetic_closure_events, synthetic_idle_periods)
        for head in ("H01", "H02", "H03"):
            assert head in report

    def test_known_success_rate_appears_in_report(self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame) -> None:
        # H01 is 100% successful by construction (see conftest.synthetic_closure_events)
        report = render_kpi_dashboard_report(synthetic_closure_events, synthetic_idle_periods)
        assert "100.00%" in report or "100.0000%" in report


class TestAnomalyReport:
    def test_renders_expected_sections(self, synthetic_closure_events: pd.DataFrame) -> None:
        report = render_anomaly_report(synthetic_closure_events)
        assert report.startswith("# AROL Capping Machine — Anomaly & Failure Report")
        for heading in ("## Anomaly Detection (z-score method)", "## Failure Analysis", "## Monitoring Recommendations"):
            assert heading in report

    def test_no_failures_still_renders_a_valid_report(self, event_block_factory) -> None:
        from arol_analytics.ingestion.normalize import add_status_fields, compute_derived_metrics

        events = event_block_factory("H60", "2026-08-01T00:00:00", 10, 1, 0, 2.0, "s.csv")
        events = compute_derived_metrics(add_status_fields(events))
        report = render_anomaly_report(events)
        assert "# AROL Capping Machine — Anomaly & Failure Report" in report
        assert "_None detected._" in report


class TestHeadComparisonReport:
    def test_renders_expected_sections(self, synthetic_closure_events: pd.DataFrame) -> None:
        report = render_head_comparison_report(synthetic_closure_events)
        assert report.startswith("# AROL Capping Machine — Head Comparison Report")
        for heading in ("## Full 3-Head Ranking", "## Statistical Test Results", "## Torque Variability Analysis", "## Busiest / Quietest Heads"):
            assert heading in report

    def test_empty_events_does_not_raise(self, synthetic_closure_events: pd.DataFrame) -> None:
        report = render_head_comparison_report(synthetic_closure_events.iloc[0:0])
        assert "# AROL Capping Machine — Head Comparison Report" in report
        assert "No data available" in report


class TestReportRegistry:
    def test_registry_has_all_three_report_types(self) -> None:
        assert set(REPORT_TYPES) == {"kpi_dashboard", "anomaly", "head_comparison"}

    def test_registry_render_functions_match_module_exports(
        self, synthetic_closure_events: pd.DataFrame, synthetic_idle_periods: pd.DataFrame
    ) -> None:
        for spec in REPORT_TYPES.values():
            output = spec.render(synthetic_closure_events, synthetic_idle_periods)
            assert isinstance(output, str) and output

    @pytest.mark.parametrize("name", sorted(REPORT_TYPES))
    def test_each_report_type_writes_a_distinct_filename(self, name: str) -> None:
        filenames = {spec.filename for spec in REPORT_TYPES.values()}
        assert len(filenames) == len(REPORT_TYPES)  # no collisions
        assert REPORT_TYPES[name].filename.endswith(".md")
