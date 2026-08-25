# Inline keyboard layouts for guided-mode menu navigation. Built with
# python-telegram-bot's InlineKeyboardMarkup/InlineKeyboardButton purely as a
# convenient (label, callback_data) data container -- terminal_sim.py reads
# `.inline_keyboard` to render numbered choices; nothing here talks to
# Telegram's API. Callback-data convention (kept short by habit):
#
#   m:<menu>            -- open a submenu (handled by menu navigation)
#   r:<tool>:<preset>    -- run a canned tool call directly
#   c:<flow>:head        -- enter the custom-flow head picker for <flow>
#   c:<flow>:time         -- enter the custom-flow time-range picker for <flow>
#   h:<flow>:<HEAD|all>   -- head picked inside a custom flow
#   t:<flow>:<preset>     -- time-range picked inside a custom flow (runs the tool)
#   more                  -- show the stashed full-table text from the last result
#   ask                   -- switch to free-question mode
#   noop                  -- disabled placeholder button (e.g. pagination labels)
#
# See registry.py for what consumes each of these, and terminal_sim.py for
# how they're dispatched.

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from arol_analytics.bot.config import HEADS
from arol_analytics.bot.time_presets import TimePreset


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=cb) for text, cb in row] for row in rows])


def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("📊 KPI Dashboard", "r:kpi:main")],
            [("✅ Success Rate Analysis", "m:success")],
            [("🔧 Torque Analysis", "m:torque")],
            [("⚠️ Anomaly Detection", "m:anomaly")],
            [("🔍 Head Comparison", "m:cmp")],
            [("❌ Failure Analysis", "m:failure")],
            [("🏭 Production & Speed", "m:speed")],
            [("💤 Idle & Utilization", "m:idle")],
            [("📋 Dataset Info", "m:info")],
            [("📈 Visualizations", "m:viz")],
            [("🤖 Free Question", "ask")],
            [("ℹ️ Help / About", "m:help")],
        ]
    )


def back(target: str = "m:main") -> list[tuple[str, str]]:
    return [("↩️ Back to Menu", target)]


def success_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Overall", "r:success:overall")],
            [("Per Head", "r:success:per_head")],
            [("Daily Breakdown", "r:success:daily")],
            [("Custom (head/time)", "c:success:head")],
            back(),
        ]
    )


def torque_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Torque Statistics (successful)", "r:torque:stats")],
            [("Torque Distribution (all real)", "r:torque:dist")],
            [("Torque Trend / Drift", "r:torque:trend")],
            [("Successful vs Failed Torque", "r:torque:outcome")],
            [("Custom (head/time)", "c:torque:head")],
            back(),
        ]
    )


def anomaly_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Z-Score Method", "r:anomaly:zscore")],
            [("IQR Method", "r:anomaly:iqr")],
            [("Custom Threshold", "c:threshold:minmax")],
            [("Show Anomaly Summary", "r:anomaly:summary")],
            back(),
        ]
    )


def head_cmp_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("All Heads Overview", "r:cmp:all")],
            [("Compare Two Heads", "c:cmp2:first")],
            [("Flagged Heads Only", "r:cmp:flagged")],
            [("Torque-Success Correlation", "r:cmp:correlation")],
            back(),
        ]
    )


def failure_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Overall Failure Breakdown", "r:failure:overall")],
            [("Failure Bursts", "r:failure:bursts")],
            [("Per-Head Failure Profile", "r:failure:perhead")],
            [("List Failed Events", "r:failure:list")],
            [("Custom (head/time)", "c:failure:head")],
            back(),
        ]
    )


def speed_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Capping Speed Summary", "r:speed:summary")],
            [("Speed Over Time", "r:speed:overtime")],
            back(),
        ]
    )


def idle_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Utilization Summary", "r:idle:util")],
            [("Idle Period Statistics", "r:idle:periods")],
            [("Daily Idle Pattern", "r:idle:daily")],
            back(),
        ]
    )


def info_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Dataset Summary", "r:info:summary")],
            [("Data Quality Report", "r:info:quality")],
            back(),
        ]
    )


def viz_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("Torque Over Time", "r:viz:torque_over_time")],
            [("Torque Histogram", "r:viz:torque_histogram")],
            [("Success Rate per Head", "r:viz:success_rate_per_head")],
            [("Failures Over Time", "r:viz:failures_over_time")],
            [("Production Over Time", "r:viz:production_over_time")],
            [("Utilization", "r:viz:utilization")],
            [("KPI Dashboard (all of the above)", "r:viz:kpi_dashboard")],
            back(),
        ]
    )


def head_picker(flow: str, exclude: str | None = None, allow_all: bool = True) -> InlineKeyboardMarkup:
    """Grid of H01..H36, 6 per row, plus an 'All Heads' option unless disabled
    (e.g. when picking two specific heads to compare)."""
    choices = [h for h in HEADS if h != exclude]
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for h in choices:
        row.append((h, f"h:{flow}:{h}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if allow_all and exclude is None:
        rows.append([("All Heads", f"h:{flow}:all")])
    rows.append(back())
    return _kb(rows)


def time_picker(flow: str, presets: list[TimePreset]) -> InlineKeyboardMarkup:
    rows = [[(p.label, f"t:{flow}:{p.key}")] for p in presets]
    rows.append(back())
    return _kb(rows)


def result_keyboard(has_more: bool, menu_target: str = "m:main") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if has_more:
        rows.append([("📋 Show Full Table", "more")])
    rows.append(back(menu_target))
    return _kb(rows)


def simple_back(menu_target: str = "m:main") -> InlineKeyboardMarkup:
    return _kb([back(menu_target)])
