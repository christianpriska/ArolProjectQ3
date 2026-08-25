# Terminal chat interface: guided menu (Mode 1, direct Layer-2 tool calls --
# no LLM) plus free-text natural-language questions routed through the
# Layer-3 AROLAgent (Mode 2). No external account or network service needed
# -- run as `PYTHONPATH=src python -m arol_analytics.bot [data_dir]`.
# Numbered choices stand in for tapping an inline button; the (label,
# callback_data) menu structure comes from keyboards.py/registry.py, reusing
# python-telegram-bot's InlineKeyboardMarkup purely as a convenient data
# container -- no telegram.ext, no polling, no bot token anywhere.

from __future__ import annotations

import argparse
import html
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardMarkup

from arol_analytics.agent import llm
from arol_analytics.agent.agent import AROLAgent
from arol_analytics.agent.router import ToolCall
from arol_analytics.bot import config, formatters, keyboards, registry
from arol_analytics.bot.registry import RunAction
from arol_analytics.bot.time_presets import build_time_presets, presets_by_key

CHARTS_DIR = Path("charts")

COLOR = sys.stdout.isatty()
DIM = "\033[2m" if COLOR else ""
BOLD = "\033[1m" if COLOR else ""
ITALIC = "\033[3m" if COLOR else ""
CYAN = "\033[36m" if COLOR else ""
RESET = "\033[0m" if COLOR else ""

_TAG_SUBS = [
    (re.compile(r"<b>(.*?)</b>", re.S), f"{BOLD}\\1{RESET}" if COLOR else "\\1"),
    (re.compile(r"<i>(.*?)</i>", re.S), f"{ITALIC}\\1{RESET}" if COLOR else "\\1"),
    (re.compile(r"</?pre>"), ""),
]


def html_to_terminal(text: str) -> str:
    """Telegram-HTML -> plain terminal text: convert the tags our formatters
    actually emit (<b>, <i>, <pre>) and unescape entities."""
    for pattern, repl in _TAG_SUBS:
        text = pattern.sub(repl, text)
    return html.unescape(text)


def print_bot_message(text: str) -> None:
    rule = f"{DIM}{'─' * 44}{RESET}"
    print(f"\n{CYAN}{BOLD}🤖 AROL Bot{RESET}")
    print(rule)
    print(html_to_terminal(text))
    print(rule)


def flatten_buttons(markup: InlineKeyboardMarkup) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns (flat [(label, callback_data), ...], printable row lines)."""
    flat: list[tuple[str, str]] = []
    lines: list[str] = []
    idx = 1
    for row in markup.inline_keyboard:
        parts = []
        for btn in row:
            parts.append(f"{DIM}[{idx}]{RESET} {btn.text}")
            flat.append((btn.text, btn.callback_data))
            idx += 1
        lines.append("  " + "   ".join(parts))
    return flat, lines


class TerminalSession:
    """Mirrors the per-chat state Telegram's bot_data/user_data/chat_data hold."""

    def __init__(self, agent: AROLAgent) -> None:
        self.agent = agent
        self.executor = agent.executor
        events = self.executor.events
        self.time_presets = build_time_presets(events["timestamp"].min(), events["timestamp"].max())
        self.start_time = time.monotonic()
        self.stats = {"guided": 0, "free": 0}

        self.buttons: list[tuple[str, str]] = []
        self.awaiting: str | None = None
        self.pending_head_filter: list[str] | None = None
        self.cmp2_head1: str | None = None
        self.last_full_text: str | None = None
        self.last_menu_target: str = "m:main"

    # -- rendering ----------------------------------------------------------

    def show(self, text: str, markup: InlineKeyboardMarkup) -> None:
        print_bot_message(text)
        self.buttons, lines = flatten_buttons(markup)
        for line in lines:
            print(line)

    def show_menu(self, key: str) -> None:
        text, keyboard_fn = registry.MENUS[key]
        self.show(text, keyboard_fn())

    # -- guided-mode tool execution -------------------------------------

    def run_action(self, action: RunAction, extra: dict[str, Any] | None = None) -> None:
        params = {**action.params, **(extra or {})}
        print(f"{DIM}⏳ running {action.tool}({params})...{RESET}")
        start = time.monotonic()
        result = self.executor.execute(ToolCall(tool=action.tool, parameters=params))
        elapsed = time.monotonic() - start
        logging.info("guided tool=%s params=%s elapsed=%.2fs error=%s", action.tool, params, elapsed, result.error)
        self.stats["guided"] += 1

        if result.error:
            self.last_full_text = None
            self.show(formatters.fmt_tool_error(action.tool, result.error), keyboards.result_keyboard(False, action.menu_target))
            return

        if action.is_chart:
            self.last_full_text = None
            self.last_menu_target = action.menu_target
            self.show(self._save_chart(result.result), keyboards.simple_back(action.menu_target))
            return

        try:
            text, full = action.formatter(result.result)
        except Exception:  # noqa: BLE001 -- a formatting bug must not crash the session
            logging.exception("formatter failed for tool=%s", action.tool)
            text, full = f"✅ {action.tool} completed, but the result couldn't be formatted.", None

        self.last_full_text = full
        self.last_menu_target = action.menu_target
        self.show(text, keyboards.result_keyboard(bool(full), action.menu_target))

    def _save_chart(self, result: dict[str, Any]) -> str:
        """A plain terminal can't render an image inline -- save each chart
        to disk and, on macOS, open it in the default viewer automatically
        so it actually shows up without an extra manual step."""
        images: list[bytes] = result.get("images") or []
        summary = result.get("summary", "")
        if not images:
            return summary or "No data to plot."

        CHARTS_DIR.mkdir(exist_ok=True)
        chart_type = result.get("chart_type", "chart")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths: list[Path] = []
        for i, img in enumerate(images):
            suffix = f"_{i + 1}" if len(images) > 1 else ""
            path = CHARTS_DIR / f"{chart_type}{suffix}_{stamp}.png"
            path.write_bytes(img)
            paths.append(path.resolve())

        if sys.platform == "darwin":
            try:
                subprocess.run(["open", *(str(p) for p in paths)], check=False)
            except OSError:
                pass  # best-effort -- the file is saved either way

        paths_text = "\n".join(f"🖼️  {p}" for p in paths)
        return f"{summary}\n\n{paths_text}"

    # -- callback_data dispatch ------------------------------------------

    def dispatch(self, data: str) -> bool:
        """Returns False if the session should exit (never happens here -- kept for symmetry)."""
        if data == "noop":
            return True

        if data == "ask":
            self.show("🤖 Type your question about the AROL capping data below.", keyboards.simple_back())
            return True

        if data == "more":
            if not self.last_full_text:
                self.show("Nothing to expand.", keyboards.simple_back(self.last_menu_target))
                return True
            print_bot_message(f"<pre>{html.escape(self.last_full_text)}</pre>")
            self.show("↩️", keyboards.simple_back(self.last_menu_target))
            return True

        if data.startswith("m:"):
            self.show_menu(data.split(":", 1)[1])
            return True

        if data.startswith("r:"):
            action = registry.RUN_ACTIONS.get(data.split(":", 1)[1])
            if action is None:
                self.show("Unknown action.", keyboards.simple_back())
                return True
            self.run_action(action)
            return True

        if data == "c:threshold:minmax":
            self.awaiting = "anomaly_threshold"
            self.show("Type the torque threshold range as <b>min,max</b> (e.g. 0.5,4.0).", keyboards.simple_back("m:anomaly"))
            return True

        if data == "c:cmp2:first":
            self.show("Pick the first head to compare:", keyboards.head_picker("cmp2", exclude=None, allow_all=False))
            return True

        if data.startswith("c:"):
            _, flow, _step = data.split(":", 2)
            if flow not in registry.FLOW_ACTIONS:
                self.show("Unknown flow.", keyboards.simple_back())
                return True
            self.show(f"Pick a head for {flow}, or 'All Heads':", keyboards.head_picker(flow))
            return True

        if data.startswith("h:"):
            self._handle_head_pick(data)
            return True

        if data.startswith("t:"):
            self._handle_time_pick(data)
            return True

        self.show(f"Unhandled action: {data}", keyboards.simple_back())
        return True

    def _handle_head_pick(self, data: str) -> None:
        _, flow, value = data.split(":", 2)

        if flow == "cmp2":
            self.cmp2_head1 = value
            self.show(f"First head: {value}. Now pick the second head:", keyboards.head_picker("cmp2b", exclude=value))
            return

        if flow == "cmp2b":
            if self.cmp2_head1 is None:
                self.show("Session expired -- start over from the menu.", keyboards.simple_back("m:cmp"))
                return
            head1, self.cmp2_head1 = self.cmp2_head1, None
            self.run_action(registry.RUN_ACTIONS["cmp:all"], {"heads": [head1, value]})
            return

        if flow in registry.FLOW_ACTIONS:
            self.pending_head_filter = None if value == "all" else [value]
            self.show(f"Head: {value}. Now pick a time range:", keyboards.time_picker(flow, self.time_presets))
            return

        self.show(f"Unhandled head-pick flow: {flow}", keyboards.simple_back())

    def _handle_time_pick(self, data: str) -> None:
        _, flow, preset_key = data.split(":", 2)
        action = registry.FLOW_ACTIONS.get(flow)
        if action is None:
            self.show("Unknown flow.", keyboards.simple_back())
            return

        preset = presets_by_key(self.time_presets).get(preset_key)
        extra: dict[str, Any] = {"head_filter": self.pending_head_filter}
        self.pending_head_filter = None
        if preset and preset.time_range:
            extra["time_range"] = list(preset.time_range)
        self.run_action(action, extra)

    # -- free text (custom-flow text input, and Mode 2 fallback) ------------

    def handle_text(self, text: str) -> None:
        if self.awaiting == "anomaly_threshold":
            self.awaiting = None
            parts = [p.strip() for p in text.replace("to", ",").split(",") if p.strip()]
            try:
                lo, hi = float(parts[0]), float(parts[1])
            except (ValueError, IndexError):
                self.show("Couldn't parse that as 'min,max' (e.g. 0.5,4.0). Try again, or use /menu.", keyboards.simple_back("m:anomaly"))
                return
            self.run_action(
                RunAction("anomaly_detection", {"method": "threshold"}, formatters.fmt_anomaly_detail, "m:anomaly"),
                {"threshold_range": [lo, hi]},
            )
            return

        self.handle_free_question(text)

    def handle_free_question(self, question: str) -> None:
        print(f"{DIM}⏳ thinking...{RESET}")
        try:
            response = self.agent.query(question)
        except Exception:  # noqa: BLE001 -- network/LLM failures must not crash the session
            logging.exception("free-form query failed for %r", question)
            response = None
        self.stats["free"] += 1

        if response is None:
            self.show("I couldn't process that question. Try using the menu (/menu) or rephrase your question.", keyboards.simple_back())
            return

        logging.info(
            "free tools=%s used_llm=%s elapsed=%.2fs", [c["tool"] for c in response.tool_calls], response.used_llm, response.execution_time
        )
        text = formatters.fmt_agent_response(response.answer, response.used_llm, response.execution_time, response.errors)
        chart_result = next((v for v in response.raw_data.values() if isinstance(v, dict) and v.get("images")), None)
        if chart_result is not None:
            text += "\n\n" + self._save_chart(chart_result)
        self.show(text, keyboards.simple_back())

    # -- commands -------------------------------------------------------

    def status_text(self) -> str:
        uptime_s = time.monotonic() - self.start_time
        llm_up = llm.is_ollama_available()
        return "\n".join(
            [
                "🩺 <b>System Status</b>",
                "",
                f"📦 Data loaded: {len(self.executor.events):,} closure events, {self.executor.events['head_id'].nunique()} heads",
                f"🤖 LLM backend: {'ONLINE (' + self.agent.model + ')' if llm_up else 'OFFLINE (keyword-fallback mode)'}",
                f"⏱️ Uptime: {uptime_s / 3600:.2f}h",
                f"📊 Requests served: {self.stats['guided']} guided, {self.stats['free']} free-form",
            ]
        )

    def handle_command(self, raw: str) -> None:
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lstrip("/").lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("start", "menu"):
            self.show_menu("main")
        elif cmd == "kpi":
            self.run_action(registry.RUN_ACTIONS["kpi:main"])
        elif cmd == "heads":
            self.run_action(registry.RUN_ACTIONS["cmp:all"])
        elif cmd == "help":
            self.show(registry.HELP_TEXT, keyboards.simple_back())
        elif cmd == "examples":
            self.show(registry.EXAMPLES_TEXT, keyboards.simple_back())
        elif cmd == "status":
            self.show(self.status_text(), keyboards.simple_back())
        elif cmd == "ask":
            if arg:
                self.handle_free_question(arg)
            else:
                self.show('🤖 Type your question, e.g. "What is the average torque?"', keyboards.simple_back())
        else:
            self.show(f"Unknown command /{cmd}. Try /help.", keyboards.simple_back())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Terminal simulator of the AROL Telegram bot -- no token, no network.")
    parser.add_argument("data_dir", nargs="?", default=config.DATA_DIR, help="Directory with the Layer-1 Parquet output.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    print(f"Loading data from {args.data_dir} ...")
    agent = AROLAgent(args.data_dir, model=config.LLM_MODEL)
    print(f"Ready. LLM routing: {'ON (' + agent.model + ')' if agent.llm_available else 'OFF (keyword fallback mode)'}")
    print(f"{BOLD}AROL Analytics -- Telegram-style terminal simulator{RESET} (type /exit to quit)")

    session = TerminalSession(agent)
    session.show_menu("main")

    while True:
        try:
            raw = input(f"\n{BOLD}You>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw.lower() in ("/exit", "exit", "quit"):
            break

        if raw.startswith("/"):
            session.handle_command(raw)
            continue

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(session.buttons):
                label, callback_data = session.buttons[idx - 1]
                print(f"{DIM}→ {label}{RESET}")
                session.dispatch(callback_data)
                continue
            print(f"{DIM}No button #{idx} on screen.{RESET}")
            continue

        session.handle_text(raw)

    return 0


if __name__ == "__main__":
    sys.exit(main())
