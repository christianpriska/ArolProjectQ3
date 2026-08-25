# Tool 6 (head_comparison) and Tool 7 (failure_analysis).

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kruskal, pearsonr

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration, real_closures, successful_closures
from arol_analytics.ingestion.schema import STATUS_LABELS

logger = logging.getLogger(__name__)

# cap per-head sample size fed into the Kruskal-Wallis test -- the test itself
# is O(n log n) over the concatenated data (tens of millions of rows across 36
# heads), and 50k/head is already far more than needed to detect a real effect
KRUSKAL_MAX_SAMPLE_PER_HEAD = 50_000
KRUSKAL_RANDOM_STATE = 0


def head_comparison(
    events: pd.DataFrame,
    heads: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Compare performance across heads: success rate, torque mean/std, total
    closures, and a failure breakdown by status code, one row per head.

    Also runs a Kruskal-Wallis test on successful-closure torque across heads
    (does torque differ significantly by head?) and flags heads that are
    statistical outliers (> 2 sigma from the group mean) on success rate, mean
    torque, or torque std.

    Returns a dict with `summary`, `table`, `flagged_heads`, `busiest_head`
    and `quietest_head` (by total_closures -- called out explicitly, not just
    left in `table`, since a large table gets truncated before an LLM sees
    it and the head with the most/fewest closures isn't necessarily among
    the first rows), `kruskal_wallis_torque_test`, `success_rate_correlation_matrix`
    (daily per-head success rate, correlated pairwise), `failure_breakdown_by_status_code`.
    """
    events = filter_events(events, heads, time_range)
    if events.empty:
        return {"summary": "No events match the given filters.", "table": [], "flagged_heads": []}

    real = real_closures(events)
    successful = successful_closures(events)

    with log_duration("head_comparison"):
        total = events.groupby("head_id", observed=True).size().rename("total_closures")
        real_agg = real.groupby("head_id", observed=True).agg(
            successful=("is_successful", "sum"),
            failed=("is_reject", "sum"),
        )
        real_agg["success_rate_pct"] = np.where(
            (real_agg["successful"] + real_agg["failed"]) > 0,
            real_agg["successful"] / (real_agg["successful"] + real_agg["failed"]) * 100.0,
            np.nan,
        )
        torque_agg = successful.groupby("head_id", observed=True)["torque_nm"].agg(mean_torque_nm="mean", std_torque_nm="std")

        table = total.to_frame().join(real_agg, how="left").join(torque_agg, how="left").reset_index()
        table["head_id"] = table["head_id"].astype(str)

        table["rank_success_rate"] = table["success_rate_pct"].rank(ascending=False, method="min")
        table["rank_mean_torque"] = table["mean_torque_nm"].rank(ascending=False, method="min")
        table["rank_torque_std"] = table["std_torque_nm"].rank(ascending=False, method="min")
        table["rank_total_closures"] = table["total_closures"].rank(ascending=False, method="min")
        table = table.sort_values("head_id").reset_index(drop=True)

        flagged = _flag_outlier_heads(table)
        kw_result = _kruskal_wallis_torque(successful)
        corr = _success_rate_correlation(real)
        failure_breakdown = _failure_breakdown(events)

    busiest = table.loc[table["total_closures"].idxmax()]
    quietest = table.loc[table["total_closures"].idxmin()]
    busiest_head = {"head_id": busiest["head_id"], "total_closures": int(busiest["total_closures"])}
    quietest_head = {"head_id": quietest["head_id"], "total_closures": int(quietest["total_closures"])}

    summary = (
        f"Compared {len(table)} heads. {len(flagged)} flagged as statistical outliers. "
        f"Most closures: {busiest_head['head_id']} ({busiest_head['total_closures']:,}); "
        f"fewest: {quietest_head['head_id']} ({quietest_head['total_closures']:,})."
    )
    if kw_result:
        verdict = "significant" if kw_result["significant"] else "not significant"
        summary += f" Kruskal-Wallis on torque across heads: p={kw_result['p_value']:.4g} ({verdict})."

    return {
        "summary": summary,
        "table": table.to_dict(orient="records"),
        "flagged_heads": flagged,
        "busiest_head": busiest_head,
        "quietest_head": quietest_head,
        "kruskal_wallis_torque_test": kw_result,
        "success_rate_correlation_matrix": corr,
        "failure_breakdown_by_status_code": failure_breakdown,
    }


def failure_analysis(
    events: pd.DataFrame,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Deep-dive into failure (reject) patterns: distribution by status code,
    daily failure-rate spikes, each head's dominant failure type, consecutive
    failure bursts (>=3 in a row for the same head), and whether heads tend to
    fail in the same hour as each other.

    Returns a dict with `summary`, `failure_distribution_by_status_code`,
    `daily_failure_rate_spikes`, `per_head_dominant_failure`,
    `consecutive_failure_bursts`, `failure_correlation_between_heads`.
    """
    events = filter_events(events, head_filter, time_range)
    real = real_closures(events)
    failures = real[real["is_reject"]]

    if failures.empty:
        return {"summary": "No failures found for the given filters.", "failure_distribution_by_status_code": {}}

    with log_duration("failure_analysis"):
        failure_distribution = {int(k): int(v) for k, v in failures["status_code"].value_counts().items()}

        spikes = _daily_failure_spikes(real)
        dominant = _dominant_failure_per_head(failures)
        bursts = _consecutive_failure_bursts(real)
        fail_corr = _failure_correlation(real)

    summary = (
        f"{len(failures):,} failures across {failures['head_id'].nunique()} heads. "
        f"{len(spikes)} day(s) with elevated failure rate. "
        f"{len(bursts)} consecutive-failure burst(s) (>=3 in a row) detected."
    )

    return {
        "summary": summary,
        "failure_distribution_by_status_code": failure_distribution,
        "daily_failure_rate_spikes": spikes,
        "per_head_dominant_failure": dominant,
        "consecutive_failure_bursts": bursts,
        "failure_correlation_between_heads": fail_corr,
    }


def torque_success_correlation(
    events: pd.DataFrame,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Tests whether heads with higher average torque also tend to have
    higher (or lower) success rates -- a per-head Pearson correlation between
    mean torque (successful closures) and success rate (real closures).

    Returns a dict with `summary`, `table` (one row per head: head_id,
    mean_torque_nm, success_rate_pct), `pearson_r`, `p_value`, `significant`.
    """
    events = filter_events(events, head_filter, time_range)
    if events.empty:
        return {"summary": "No events match the given filters.", "table": [], "pearson_r": None}

    real = real_closures(events)
    successful = successful_closures(events)

    real_agg = real.groupby("head_id", observed=True).agg(successful=("is_successful", "sum"), failed=("is_reject", "sum"))
    real_agg["success_rate_pct"] = np.where(
        (real_agg["successful"] + real_agg["failed"]) > 0,
        real_agg["successful"] / (real_agg["successful"] + real_agg["failed"]) * 100.0,
        np.nan,
    )
    torque_agg = successful.groupby("head_id", observed=True)["torque_nm"].mean().rename("mean_torque_nm")

    table = real_agg[["success_rate_pct"]].join(torque_agg, how="inner").dropna().reset_index()
    table["head_id"] = table["head_id"].astype(str)

    if len(table) < 3:
        return {
            "summary": "Not enough heads with valid data to compute a correlation.",
            "table": table.to_dict(orient="records"),
            "pearson_r": None,
        }

    with log_duration("torque_success_correlation"):
        r, pvalue = pearsonr(table["mean_torque_nm"], table["success_rate_pct"])

    significant = bool(pvalue < 0.05)
    strength = "weak" if abs(r) < 0.3 else "moderate" if abs(r) < 0.7 else "strong"
    direction = "positive" if r > 0 else "negative"
    summary = (
        f"Pearson correlation between mean torque and success rate across {len(table)} heads: r={r:.3f} "
        f"({strength} {direction}), p={pvalue:.4g} ({'significant' if significant else 'not significant'})."
    )

    return {
        "summary": summary,
        "table": table.sort_values("head_id").to_dict(orient="records"),
        "pearson_r": float(r),
        "p_value": float(pvalue),
        "significant": significant,
    }


def _flag_outlier_heads(table: pd.DataFrame) -> list[str]:
    flagged = []
    for metric, label in [("success_rate_pct", "success rate"), ("mean_torque_nm", "mean torque"), ("std_torque_nm", "torque variability")]:
        vals = table[metric].dropna()
        if len(vals) < 2:
            continue
        avg, std = vals.mean(), vals.std(ddof=0)
        if not std or std == 0:
            continue
        for _, row in table.iterrows():
            v = row[metric]
            if pd.isna(v) or abs(v - avg) <= 2 * std:
                continue
            direction = "higher" if v > avg else "lower"
            flagged.append(f"{row['head_id']} has significantly {direction} {label} ({v:.3f} vs group avg {avg:.3f})")
    return flagged


def _kruskal_wallis_torque(successful: pd.DataFrame) -> dict[str, Any] | None:
    rng = np.random.default_rng(KRUSKAL_RANDOM_STATE)
    groups = []
    for _, g in successful.groupby("head_id", observed=True):
        values = g["torque_nm"].dropna().to_numpy()
        if len(values) == 0:
            continue
        if len(values) > KRUSKAL_MAX_SAMPLE_PER_HEAD:
            values = rng.choice(values, size=KRUSKAL_MAX_SAMPLE_PER_HEAD, replace=False)
        groups.append(values)
    if len(groups) < 2:
        return None
    stat, pvalue = kruskal(*groups)
    return {
        "statistic": float(stat),
        "p_value": float(pvalue),
        "significant": bool(pvalue < 0.05),
        "note": f"subsampled to <= {KRUSKAL_MAX_SAMPLE_PER_HEAD:,} events/head for performance",
    }


def _success_rate_correlation(real: pd.DataFrame) -> dict[str, dict[str, float]]:
    if real.empty:
        return {}
    daily = real.assign(day=real["timestamp"].dt.floor("D")).groupby(["day", "head_id"], observed=True).agg(
        successful=("is_successful", "sum"), failed=("is_reject", "sum")
    )
    denom = daily["successful"] + daily["failed"]
    daily["rate"] = np.where(denom > 0, daily["successful"] / denom, np.nan)
    pivot = daily["rate"].unstack("head_id")
    if pivot.shape[1] < 2:
        return {}
    corr = pivot.corr().round(3)
    corr.index = corr.index.astype(str)
    corr.columns = corr.columns.astype(str)
    return corr.to_dict()


def _failure_breakdown(events: pd.DataFrame) -> list[dict[str, Any]]:
    failures = events[events["is_reject"]]
    if failures.empty:
        return []
    breakdown = failures.groupby(["head_id", "status_code"], observed=True).size().reset_index(name="count")
    breakdown["head_id"] = breakdown["head_id"].astype(str)
    breakdown["status_label"] = breakdown["status_code"].map(STATUS_LABELS)
    return breakdown.to_dict(orient="records")


def _daily_failure_spikes(real: pd.DataFrame) -> list[dict[str, Any]]:
    daily = real.assign(day=real["timestamp"].dt.floor("D")).groupby("day", observed=True).agg(
        failures=("is_reject", "sum"), total=("is_reject", "size")
    )
    daily["failure_rate_pct"] = daily["failures"] / daily["total"] * 100.0
    if len(daily) < 2:
        return []
    avg, std = daily["failure_rate_pct"].mean(), daily["failure_rate_pct"].std(ddof=0)
    if not std or std <= 0:
        return []
    spikes = daily[daily["failure_rate_pct"] > avg + 2 * std]
    return [
        {"date": str(idx.date()), "failure_rate_pct": float(row["failure_rate_pct"]), "n_failures": int(row["failures"])}
        for idx, row in spikes.iterrows()
    ]


def _dominant_failure_per_head(failures: pd.DataFrame) -> list[str]:
    profile = failures.groupby(["head_id", "status_code"], observed=True).size().rename("count").reset_index()
    dominant = profile.sort_values("count", ascending=False).groupby("head_id", observed=True).first()
    return [
        f"{h}: dominant failure {STATUS_LABELS.get(int(row['status_code']), row['status_code'])} ({int(row['count'])} events)"
        for h, row in dominant.iterrows()
    ]


def _consecutive_failure_bursts(real: pd.DataFrame, min_run: int = 3) -> list[dict[str, Any]]:
    bursts: list[dict[str, Any]] = []
    for h, g in real.sort_values("timestamp").groupby("head_id", observed=True):
        is_fail = g["is_reject"].to_numpy()
        if not is_fail.any():
            continue
        run_id = (g["is_reject"] != g["is_reject"].shift()).cumsum()
        run_df = pd.DataFrame({"run_id": run_id.to_numpy(), "is_fail": is_fail, "ts": g["timestamp"].to_numpy(), "status": g["status_code"].to_numpy()})
        for _, run in run_df.groupby("run_id"):
            if run["is_fail"].iloc[0] and len(run) >= min_run:
                bursts.append(
                    {
                        "head_id": str(h),
                        "start_time": str(run["ts"].iloc[0]),
                        "end_time": str(run["ts"].iloc[-1]),
                        "count": int(len(run)),
                        "failure_types": sorted({int(s) for s in run["status"]}),
                    }
                )
    return bursts


def _failure_correlation(real: pd.DataFrame) -> dict[str, dict[str, float]] | None:
    hourly = real.assign(hour=real["timestamp"].dt.floor("h")).groupby(["hour", "head_id"], observed=True)["is_reject"].sum()
    pivot = hourly.unstack("head_id", fill_value=0)
    if pivot.shape[1] < 2:
        return None
    corr = pivot.corr().round(3)
    corr.index = corr.index.astype(str)
    corr.columns = corr.columns.astype(str)
    return corr.to_dict()
