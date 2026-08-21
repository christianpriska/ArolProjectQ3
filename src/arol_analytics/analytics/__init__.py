# Layer-2 baseline analytics tools -- deterministic functions the future agent will call.

from arol_analytics.analytics.anomaly import anomaly_detection
from arol_analytics.analytics.dashboard import generate_kpi_dashboard
from arol_analytics.analytics.heads import failure_analysis, head_comparison
from arol_analytics.analytics.io import load_closure_events, load_idle_periods
from arol_analytics.analytics.production import capping_speed_analysis, idle_analysis
from arol_analytics.analytics.summary import dataset_summary, success_rate_analysis
from arol_analytics.analytics.torque import torque_statistics, torque_trend_analysis

__all__ = [
    "load_closure_events",
    "load_idle_periods",
    "dataset_summary",
    "success_rate_analysis",
    "torque_statistics",
    "torque_trend_analysis",
    "anomaly_detection",
    "head_comparison",
    "failure_analysis",
    "capping_speed_analysis",
    "idle_analysis",
    "generate_kpi_dashboard",
]
