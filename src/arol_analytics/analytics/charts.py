# Tool 14: visualize -- renders a fixed set of chart types as PNG bytes
# (matplotlib, Agg backend, headless -- no display needed). Colors are reused
# verbatim from the project's validated categorical/status palette (see the
# dataviz skill's references/palette.md), not re-derived here.
#
# Every chart function returns `images: list[bytes]` (never a single bare
# PNG) -- most chart_types produce exactly one image, but "kpi_dashboard"
# composes several independent full-size charts rather than cramming
# multiple plots into one crowded multi-panel figure (a single combined
# image is harder to read and impossible to view one-at-a-time).

from __future__ import annotations

import io
import logging
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from arol_analytics.analytics._common import TimeRange, filter_events, log_duration, real_closures, successful_closures
from arol_analytics.analytics.production import idle_analysis
from arol_analytics.analytics.summary import success_rate_analysis

logger = logging.getLogger(__name__)

VALID_CHART_TYPES = {
    "torque_over_time",
    "torque_histogram",
    "success_rate_per_head",
    "failures_over_time",
    "production_over_time",
    "utilization",
    "kpi_dashboard",
}

BG = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3, fixed order -- never reassigned by rank
STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"


def render_chart(
    events: pd.DataFrame,
    idle_periods: pd.DataFrame | None,
    chart_type: str,
    head_filter: list[str] | None = None,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Renders one of a fixed set of chart types as one or more PNG images
    over the same filtered data the text tools use.

    chart_type: "torque_over_time" (line, daily mean torque -- broken out per
    head when head_filter names <=3 heads, otherwise the overall aggregate),
    "torque_histogram" (successful closures), "success_rate_per_head" (bar of
    each head's *deviation from the group average* -- real success rates
    cluster too tightly for the raw percentage to show any visible
    difference on a 0-100 axis), "failures_over_time" (daily failure count,
    statistically elevated days highlighted), "production_over_time" (daily
    closure volume), "utilization" (productive vs. idle time), or
    "kpi_dashboard" (all of the above four, as separate images -- not one
    cramped multi-panel figure).

    Returns a dict with `summary`, `chart_type`, `images` (list of PNG
    bytes -- empty if there was no data to plot), and `series` (the
    underlying numeric data, for a text/ASCII fallback where a displayed
    image isn't possible).
    """
    if chart_type not in VALID_CHART_TYPES:
        raise ValueError(f"chart_type must be one of {sorted(VALID_CHART_TYPES)}, got {chart_type!r}")

    filtered = filter_events(events, head_filter, time_range)
    if filtered.empty:
        return {"summary": "No events match the given filters.", "chart_type": chart_type, "images": [], "series": []}

    with log_duration(f"render_chart({chart_type})"):
        if chart_type == "torque_over_time":
            return _chart_torque_over_time(filtered, head_filter)
        if chart_type == "torque_histogram":
            return _chart_torque_histogram(filtered)
        if chart_type == "success_rate_per_head":
            return _chart_success_rate_per_head(filtered)
        if chart_type == "failures_over_time":
            return _chart_failures_over_time(filtered)
        if chart_type == "production_over_time":
            return _chart_production_over_time(filtered)
        if chart_type == "utilization":
            return _chart_utilization(idle_periods, time_range)
        return _chart_kpi_dashboard(filtered, idle_periods, time_range)


def _new_figure(figsize: tuple[float, float] = (8, 4.5)) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    return fig, ax


def _fig_to_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _empty(chart_type: str, message: str) -> dict[str, Any]:
    return {"summary": message, "chart_type": chart_type, "images": [], "series": []}


def _chart_torque_over_time(events: pd.DataFrame, head_filter: list[str] | None) -> dict[str, Any]:
    successful = successful_closures(events)
    if successful.empty:
        return _empty("torque_over_time", "No successful closures to plot.")

    heads = sorted(successful["head_id"].astype(str).unique().tolist())
    per_head = head_filter is not None and len(heads) <= 3

    fig, ax = _new_figure()
    series_out: list[dict[str, Any]] = []

    if per_head:
        for i, h in enumerate(heads):
            daily = successful[successful["head_id"] == h].set_index("timestamp")["torque_nm"].resample("D").mean().dropna()
            ax.plot(daily.index, daily.values, color=SERIES[i % len(SERIES)], linewidth=2, solid_capstyle="round", label=h)
            series_out.append({"head_id": h, "points": [{"date": str(d.date()), "mean_torque_nm": float(v)} for d, v in daily.items()]})
        ax.legend(frameon=False, labelcolor=INK_SECONDARY, fontsize=9)
        title = f"Mean daily torque -- {', '.join(heads)}"
    else:
        daily = successful.set_index("timestamp")["torque_nm"].resample("D").mean().dropna()
        ax.plot(daily.index, daily.values, color=SERIES[0], linewidth=2, solid_capstyle="round")
        series_out.append({"head_id": "overall", "points": [{"date": str(d.date()), "mean_torque_nm": float(v)} for d, v in daily.items()]})
        title = "Mean daily torque -- all heads (aggregate)"

    ax.set_title(title, color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    ax.set_ylabel("Torque (Nm)", color=INK_SECONDARY, fontsize=10)
    fig.autofmt_xdate()

    summary = f"Torque-over-time chart rendered for {'heads ' + ', '.join(heads) if per_head else 'all heads (aggregate)'}."
    return {"summary": summary, "chart_type": "torque_over_time", "images": [_fig_to_png(fig)], "series": series_out}


def _histogram_range(values: pd.Series) -> tuple[float, float]:
    """Torque is extremely tightly clustered (std on the order of 0.01-0.03
    Nm) with rare far outliers -- an auto-ranged histogram puts 99.9% of the
    mass in one bin. Zoom to the 0.5-99.5th percentile band so the actual
    distribution shape is visible; outliers are still counted in the stats,
    just outside the plotted range."""
    lo, hi = float(values.quantile(0.005)), float(values.quantile(0.995))
    return (lo, hi) if lo < hi else (float(values.min()), float(values.max()))


def _chart_torque_histogram(events: pd.DataFrame) -> dict[str, Any]:
    torque = successful_closures(events)["torque_nm"].dropna()
    if torque.empty:
        return _empty("torque_histogram", "No successful closures to plot.")

    fig, ax = _new_figure()
    counts, bin_edges, _ = ax.hist(torque, bins=40, range=_histogram_range(torque), color=SERIES[0], edgecolor=BG, linewidth=0.5)
    ax.set_title("Torque distribution -- successful closures", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    ax.set_xlabel("Torque (Nm)", color=INK_SECONDARY, fontsize=10)
    ax.set_ylabel("Count", color=INK_SECONDARY, fontsize=10)

    series_out = [{"bin_start": float(bin_edges[i]), "bin_end": float(bin_edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))]
    summary = (
        f"Torque histogram over {len(torque):,} successful closures: mean {torque.mean():.3f} Nm, std {torque.std():.3f} Nm "
        "(x-axis zoomed to the 0.5-99.5th percentile band; extreme outliers are counted in the stats but fall outside the plotted range)."
    )
    return {"summary": summary, "chart_type": "torque_histogram", "images": [_fig_to_png(fig)], "series": series_out}


def _chart_success_rate_per_head(events: pd.DataFrame) -> dict[str, Any]:
    result = success_rate_analysis(events, group_by="per_head")
    table = result.get("table", [])
    if not table:
        return _empty("success_rate_per_head", result.get("summary", "No data."))

    table_sorted = sorted(table, key=lambda r: r["group"])
    heads = [r["group"] for r in table_sorted]
    rates = [r["success_rate_pct"] for r in table_sorted]
    flagged = set(result.get("flagged_groups", []))
    best_head = max(table, key=lambda r: r["success_rate_pct"])["group"]

    # Real success rates on this kind of process cluster in a tiny band (e.g.
    # 99.98-100%) -- a bar chart of the raw percentage on a 0-100 axis makes
    # every bar look identical (the actual signal is a fraction of a pixel).
    # Plotting the deviation from the average instead keeps a meaningful
    # zero (= "at the group average") and makes the real spread the full
    # height of the plot, without truncating an absolute-magnitude axis
    # (which would misrepresent bar length for a magnitude encoding).
    avg_rate = sum(rates) / len(rates)
    deviations = [r - avg_rate for r in rates]

    colors = [STATUS_CRITICAL if h in flagged else STATUS_GOOD if h == best_head else SERIES[0] for h in heads]

    fig, ax = _new_figure(figsize=(10, 4.5))
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.bar(heads, deviations, color=colors, width=0.7)
    ax.set_title(f"Success rate per head -- deviation from average ({avg_rate:.3f}%)", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    ax.set_ylabel("Percentage points vs. average", color=INK_SECONDARY, fontsize=10)
    ax.tick_params(axis="x", rotation=90, labelsize=7)

    legend_handles = [Line2D([0], [0], color=STATUS_GOOD, lw=6, label="Best")]
    if flagged:
        legend_handles.append(Line2D([0], [0], color=STATUS_CRITICAL, lw=6, label="Flagged (>2σ below avg)"))
    ax.legend(handles=legend_handles, frameon=False, labelcolor=INK_SECONDARY, fontsize=8, loc="lower right")

    series_out = [{"head_id": h, "success_rate_pct": r, "deviation_from_avg_pct": d} for h, r, d in zip(heads, rates, deviations)]
    summary = (
        f"Success rate per head chart rendered for {len(heads)} heads (average {avg_rate:.3f}%; "
        "y-axis shows deviation from that average, not the raw percentage, since real rates cluster too "
        "tightly for a 0-100 scale to show any visible difference)."
    )
    return {"summary": summary, "chart_type": "success_rate_per_head", "images": [_fig_to_png(fig)], "series": series_out}


def _chart_failures_over_time(events: pd.DataFrame) -> dict[str, Any]:
    real = real_closures(events)
    if real.empty:
        return _empty("failures_over_time", "No data to plot.")

    daily = real.assign(day=real["timestamp"].dt.floor("D")).groupby("day", observed=True)["is_reject"].sum()
    if daily.empty:
        return _empty("failures_over_time", "No failures in range.")

    avg, std = daily.mean(), daily.std(ddof=0)
    spike_mask = (daily > avg + 2 * std) if std and std > 0 else pd.Series(False, index=daily.index)
    colors = [STATUS_CRITICAL if spike_mask.loc[d] else SERIES[0] for d in daily.index]

    fig, ax = _new_figure()
    ax.bar(daily.index, daily.values, color=colors, width=0.8)
    ax.set_title("Failed closures per day", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    ax.set_ylabel("Failures", color=INK_SECONDARY, fontsize=10)
    fig.autofmt_xdate()
    if spike_mask.any():
        ax.legend(handles=[Line2D([0], [0], color=STATUS_CRITICAL, lw=6, label="Elevated (>2σ)")], frameon=False, labelcolor=INK_SECONDARY, fontsize=8)

    series_out = [{"date": str(d.date()), "failures": int(v), "elevated": bool(spike_mask.loc[d])} for d, v in daily.items()]
    summary = f"Failures-over-time chart rendered: {int(daily.sum()):,} total failures across {len(daily)} day(s), {int(spike_mask.sum())} elevated."
    return {"summary": summary, "chart_type": "failures_over_time", "images": [_fig_to_png(fig)], "series": series_out}


def _chart_production_over_time(events: pd.DataFrame) -> dict[str, Any]:
    production = real_closures(events).dropna(subset=["capping_speed_pph"])
    daily = production.set_index("timestamp")["inferred_closure_count"].resample("D").sum() if not production.empty else pd.Series(dtype=float)
    daily = daily[daily > 0]
    if daily.empty:
        return _empty("production_over_time", "No production data to plot.")

    fig, ax = _new_figure()
    ax.plot(daily.index, daily.values, color=SERIES[0], linewidth=2, solid_capstyle="round")
    ax.set_title("Daily production volume", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)
    ax.set_ylabel("Inferred closures / day", color=INK_SECONDARY, fontsize=10)
    fig.autofmt_xdate()

    series_out = [{"date": str(d.date()), "closures": int(v)} for d, v in daily.items()]
    summary = f"Daily production volume chart rendered over {len(daily)} day(s), mean {daily.mean():,.0f} closures/day."
    return {"summary": summary, "chart_type": "production_over_time", "images": [_fig_to_png(fig)], "series": series_out}


def _chart_utilization(idle_periods: pd.DataFrame | None, time_range: TimeRange | None) -> dict[str, Any]:
    if idle_periods is None or idle_periods.empty:
        return _empty("utilization", "No idle-period data to plot.")

    util = idle_analysis(idle_periods, time_range=time_range).get("utilization_rate")
    if util is None or util != util:
        return _empty("utilization", "No utilization data to plot.")

    fig, ax = plt.subplots(figsize=(5, 5), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.pie([util, 1 - util], colors=[SERIES[0], GRID], startangle=90, wedgeprops={"width": 0.4})
    ax.set_title(f"Utilization: {util * 100:.1f}%", color=INK_PRIMARY, fontsize=12, loc="left", pad=10)

    summary = f"Utilization chart rendered: {util * 100:.1f}% productive time (rest idle)."
    return {"summary": summary, "chart_type": "utilization", "images": [_fig_to_png(fig)], "series": [{"utilization_pct": util * 100}]}


def _chart_kpi_dashboard(events: pd.DataFrame, idle_periods: pd.DataFrame | None, time_range: TimeRange | None) -> dict[str, Any]:
    """Composes the KPI overview from the other chart functions -- separate,
    full-size images, not one crowded multi-panel figure."""
    parts = [
        _chart_success_rate_per_head(events),
        _chart_torque_histogram(events),
        _chart_production_over_time(events),
        _chart_utilization(idle_periods, time_range),
    ]
    images = [img for part in parts for img in part["images"]]
    summary = "KPI dashboard (" + str(len(images)) + " charts): " + " | ".join(p["summary"] for p in parts if p["images"])
    return {"summary": summary, "chart_type": "kpi_dashboard", "images": images, "series": []}
