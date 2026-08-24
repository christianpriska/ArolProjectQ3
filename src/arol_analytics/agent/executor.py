# Tool executor: loads Layer-1 data once, maps router tool names to the real
# Layer-2 functions, runs them with the router's parameters, and never lets a
# bad tool call crash the agent -- exceptions become a structured error result.

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from arol_analytics.analytics import (
    anomaly_detection,
    capping_speed_analysis,
    dataset_summary,
    failure_analysis,
    generate_kpi_dashboard,
    head_comparison,
    idle_analysis,
    load_closure_events,
    load_idle_periods,
    success_rate_analysis,
    torque_statistics,
    torque_trend_analysis,
)
from arol_analytics.agent.router import ToolCall

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    tool: str
    parameters: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    elapsed_s: float


def _to_time_range(value: Any) -> tuple[Any, Any] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (value[0], value[1])
    raise ValueError(f"time_range must be a [start, end] pair, got {value!r}")


def _to_threshold_range(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    raise ValueError(f"threshold_range must be a [low, high] pair, got {value!r}")


class ToolExecutor:
    """Loads closure_events / idle_periods / quality_report once and dispatches tool calls against them."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        logger.info("loading Layer-1 data from %s", self.data_dir)
        self.events: pd.DataFrame = load_closure_events(self.data_dir)
        self.idle_periods: pd.DataFrame = load_idle_periods(self.data_dir)
        self.quality_report: dict[str, Any] | None = self._load_quality_report()
        self._dispatch: dict[str, Callable[..., dict[str, Any]]] = self._build_dispatch()

    def _load_quality_report(self) -> dict[str, Any] | None:
        path = self.data_dir / "data_quality_report.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def _build_dispatch(self) -> dict[str, Callable[..., dict[str, Any]]]:
        return {
            "dataset_summary": lambda **p: dataset_summary(self.events, quality_report=self.quality_report),
            "success_rate_analysis": lambda **p: success_rate_analysis(
                self.events,
                group_by=p.get("group_by", "overall"),
                head_filter=p.get("head_filter"),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "torque_statistics": lambda **p: torque_statistics(
                self.events,
                filter_status=p.get("filter_status", "successful_only"),
                group_by=p.get("group_by", "overall"),
                head_filter=p.get("head_filter"),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "torque_trend_analysis": lambda **p: torque_trend_analysis(
                self.events,
                head_filter=p.get("head_filter"),
                window_size=p.get("window_size", 1000),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "anomaly_detection": lambda **p: anomaly_detection(
                self.events,
                method=p.get("method", "zscore"),
                threshold_range=_to_threshold_range(p.get("threshold_range")),
                sensitivity=p.get("sensitivity", 3.0),
                head_filter=p.get("head_filter"),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "head_comparison": lambda **p: head_comparison(
                self.events,
                heads=p.get("heads"),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "failure_analysis": lambda **p: failure_analysis(
                self.events,
                head_filter=p.get("head_filter"),
                time_range=_to_time_range(p.get("time_range")),
            ),
            "capping_speed_analysis": lambda **p: capping_speed_analysis(
                self.events,
                idle_periods=self.idle_periods,
                head_filter=p.get("head_filter"),
                time_range=_to_time_range(p.get("time_range")),
                exclude_idle=p.get("exclude_idle", True),
            ),
            "idle_analysis": lambda **p: idle_analysis(
                self.idle_periods,
                time_range=_to_time_range(p.get("time_range")),
            ),
            "generate_kpi_dashboard": lambda **p: generate_kpi_dashboard(
                self.events,
                self.idle_periods,
                time_range=_to_time_range(p.get("time_range")),
            ),
        }

    def execute(self, call: ToolCall) -> ExecutionResult:
        fn = self._dispatch.get(call.tool)
        if fn is None:
            return ExecutionResult(tool=call.tool, parameters=call.parameters, result=None, error=f"no executable tool named {call.tool!r}", elapsed_s=0.0)

        start = time.monotonic()
        try:
            result = fn(**call.parameters)
            elapsed = time.monotonic() - start
            logger.info("executed %s(%s) in %.2fs", call.tool, call.parameters, elapsed)
            return ExecutionResult(tool=call.tool, parameters=call.parameters, result=result, error=None, elapsed_s=elapsed)
        except Exception as exc:  # noqa: BLE001 -- tool failures must never crash the agent
            elapsed = time.monotonic() - start
            logger.exception("tool %s failed", call.tool)
            return ExecutionResult(tool=call.tool, parameters=call.parameters, result=None, error=str(exc), elapsed_s=elapsed)

    def execute_all(self, calls: list[ToolCall]) -> list[ExecutionResult]:
        return [self.execute(c) for c in calls]
