# Smoke test for src/arol_analytics/analytics: loads a small sample of real
# closure_events.parquet, calls every tool, and checks the return shape.
# Run as: PYTHONPATH=src python tests/test_analytics.py
# (or plain `python tests/test_analytics.py` -- it adds src/ to sys.path itself)

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402

from arol_analytics.analytics import (  # noqa: E402
    anomaly_detection,
    capping_speed_analysis,
    dataset_summary,
    failure_analysis,
    generate_kpi_dashboard,
    head_comparison,
    idle_analysis,
    success_rate_analysis,
    torque_statistics,
    torque_trend_analysis,
)

CLOSURE_EVENTS_PATH = REPO_ROOT / "data" / "processed" / "closure_events.parquet"
IDLE_PERIODS_PATH = REPO_ROOT / "data" / "processed" / "idle_periods.parquet"
SAMPLE_SIZE = 100_000


def load_sample(path: Path, n: int = SAMPLE_SIZE) -> pd.DataFrame:
    """Read only the first ~n rows of a Parquet file without loading the whole file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    batches = []
    got = 0
    for batch in pf.iter_batches(batch_size=n):
        batches.append(batch)
        got += batch.num_rows
        if got >= n:
            break
    table = pa.Table.from_batches(batches)
    df = table.to_pandas().head(n)
    if "inferred_closure_count" not in df and "accepted_closure_count" in df:
        df = df.rename(columns={"accepted_closure_count": "inferred_closure_count"})
    for col in ("head_id", "status_label", "classification", "source_file"):
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


def check(name: str, result: dict, required_keys: set[str]) -> None:
    missing = required_keys - result.keys()
    assert not missing, f"{name}: missing keys {missing}"
    assert isinstance(result["summary"], str) and result["summary"], f"{name}: summary must be a non-empty string"
    print(f"[OK] {name}: {result['summary'][:160]}")


def main() -> None:
    if not CLOSURE_EVENTS_PATH.exists():
        print(f"SKIP: {CLOSURE_EVENTS_PATH} not found -- run the ingestion pipeline first.")
        return

    events = load_sample(CLOSURE_EVENTS_PATH)
    idle_periods = pd.read_parquet(IDLE_PERIODS_PATH) if IDLE_PERIODS_PATH.exists() else pd.DataFrame(
        columns=["start_time", "end_time", "duration_seconds"]
    )
    print(f"loaded sample: {len(events)} closure events, {len(idle_periods)} idle periods\n")

    check("dataset_summary", dataset_summary(events), {"summary", "total_events", "n_heads", "heads", "time_range"})

    check(
        "success_rate_analysis(overall)",
        success_rate_analysis(events, group_by="overall"),
        {"summary", "group_by", "table", "flagged_groups"},
    )
    check(
        "success_rate_analysis(per_head)",
        success_rate_analysis(events, group_by="per_head"),
        {"summary", "group_by", "table", "flagged_groups"},
    )

    check(
        "torque_statistics(successful_only, overall)",
        torque_statistics(events, filter_status="successful_only", group_by="overall"),
        {"summary", "table", "warning"},
    )
    check(
        "torque_statistics(all, per_head)",
        torque_statistics(events, filter_status="all", group_by="per_head"),
        {"summary", "table", "warning"},
    )

    check(
        "torque_trend_analysis",
        torque_trend_analysis(events, window_size=200),
        {"summary", "per_head_trend", "changepoints", "plot_series"},
    )

    check(
        "anomaly_detection(zscore)",
        anomaly_detection(events, method="zscore"),
        {"summary", "total_anomalies", "anomalies", "anomaly_count_per_head"},
    )
    check(
        "anomaly_detection(threshold)",
        anomaly_detection(events, method="threshold", threshold_range=(0.5, 4.0)),
        {"summary", "total_anomalies", "anomalies"},
    )

    check(
        "head_comparison",
        head_comparison(events),
        {"summary", "table", "flagged_heads", "kruskal_wallis_torque_test"},
    )

    check(
        "failure_analysis",
        failure_analysis(events),
        {"summary", "failure_distribution_by_status_code"},
    )

    check(
        "capping_speed_analysis",
        capping_speed_analysis(events, idle_periods=idle_periods),
        {"summary", "machine_wide_throughput_pph", "machine_wide_timeline", "per_head_average_speed_pph", "gap_affected_hours"},
    )

    if not idle_periods.empty:
        check("idle_analysis", idle_analysis(idle_periods), {"summary", "utilization_rate", "idle_period_stats"})
    else:
        print("[SKIP] idle_analysis: no idle periods in idle_periods.parquet")

    check(
        "generate_kpi_dashboard",
        generate_kpi_dashboard(events, idle_periods),
        {"summary", "kpis"},
    )

    # edge case: empty dataframe should not raise
    empty = events.iloc[0:0]
    empty_result = dataset_summary(empty)
    assert empty_result["total_events"] == 0
    print("[OK] dataset_summary handles empty DataFrame")

    # edge case: single-head filter
    one_head = events["head_id"].iloc[0]
    single = success_rate_analysis(events, group_by="per_head", head_filter=[one_head])
    assert len(single["table"]) <= 1
    print(f"[OK] success_rate_analysis handles single-head filter ({one_head})")

    print("\nAll analytics tool checks passed.")


if __name__ == "__main__":
    main()
