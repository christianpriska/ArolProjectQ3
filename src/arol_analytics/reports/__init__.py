# Report templates: renders Layer-2 analytics output into polished, human-
# readable Markdown reports. Three report types today; REPORT_TYPES is the
# registry the CLI (`python -m arol_analytics.reports`) and any other caller
# use to discover them by name.

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from arol_analytics.reports.anomaly_report import render_anomaly_report
from arol_analytics.reports.head_comparison_report import render_head_comparison_report
from arol_analytics.reports.kpi_dashboard import render_kpi_dashboard_report

__all__ = [
    "render_kpi_dashboard_report",
    "render_anomaly_report",
    "render_head_comparison_report",
    "REPORT_TYPES",
    "ReportSpec",
]


@dataclass(frozen=True)
class ReportSpec:
    name: str
    filename: str
    description: str
    render: Callable[[pd.DataFrame, pd.DataFrame], str]
    needs_idle_periods: bool = False


def _kpi_dashboard(events: pd.DataFrame, idle_periods: pd.DataFrame) -> str:
    return render_kpi_dashboard_report(events, idle_periods)


def _anomaly(events: pd.DataFrame, idle_periods: pd.DataFrame) -> str:
    return render_anomaly_report(events)


def _head_comparison(events: pd.DataFrame, idle_periods: pd.DataFrame) -> str:
    return render_head_comparison_report(events)


REPORT_TYPES: dict[str, ReportSpec] = {
    "kpi_dashboard": ReportSpec(
        name="kpi_dashboard",
        filename="kpi_dashboard.md",
        description="KPI summary + full per-head performance table.",
        render=_kpi_dashboard,
        needs_idle_periods=True,
    ),
    "anomaly": ReportSpec(
        name="anomaly",
        filename="anomaly_report.md",
        description="Anomaly detection + failure breakdown, bursts, and monitoring recommendations.",
        render=_anomaly,
    ),
    "head_comparison": ReportSpec(
        name="head_comparison",
        filename="head_comparison_report.md",
        description="Full per-head ranking, statistical test results, and torque variability analysis.",
        render=_head_comparison,
    ),
}
