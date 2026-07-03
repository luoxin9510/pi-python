"""Event stream → rich console renderer (TurnRenderer) + summary helpers.

All dynamic content is printed via ``rich.Text``, never f-string markup: tool
arguments and message text routinely contain ``[a-z]``/``list[int]``-shaped
substrings that rich's markup parser would silently swallow if we built the
string with markup enabled (confirmed by review testing). ``rich.Text`` never
parses markup, so it is safe for arbitrary content.
"""

import json

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from pipython import (
    AgentEnd,
    AssistantMessage,
    MessageEnd,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)

_TAIL_LINES = 8
_ARG_TRUNC = 100
_ERR_TRUNC = 200
_SUMMARY_TRUNC = 50


def extract_text(message: AssistantMessage) -> str:
    return "".join(c.text for c in message.content if c.type == "text")


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize_message_dict(d: dict) -> str:
    content = d.get("content")
    if isinstance(content, str):
        return _clip(content, _SUMMARY_TRUNC)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return _clip(block.get("text", ""), _SUMMARY_TRUNC)
        for block in content:
            if isinstance(block, dict) and block.get("type") == "toolCall":
                return f"[tool: {block.get('name', '?')}]"
    return _clip(str(d.get("role", "?")), _SUMMARY_TRUNC)


class TurnRenderer:
    """Renders one agent-loop event stream onto a rich Console.

    On a real terminal (``console.is_terminal``), a transient ``rich.Live``
    tail preview (<=8 lines, spinner "thinking…") tracks accumulating
    text_delta events; it is stopped and the full message is re-rendered as
    Markdown on message_end. On a non-tty console the Live path is skipped
    entirely — deltas accumulate silently in a buffer and only the final
    Markdown render is printed (degradation branch, exercised by the unit
    tests via ``force_terminal=False``; the Live path is covered by the tmux
    e2e in Task 6).
    """

    def __init__(self, console: Console):
        self.console = console
        self._buf: list[str] = []
        self._live: Live | None = None
        if console.is_terminal:
            self._live = Live(
                Spinner("dots", text="thinking…"),
                console=console,
                refresh_per_second=12,
                transient=True,
            )
            self._live.__enter__()

    def _tail(self) -> Text:
        lines = "".join(self._buf).splitlines()[-_TAIL_LINES:]
        return Text("\n".join(lines))

    async def handle(self, event) -> None:
        if isinstance(event, TextDelta):
            self._buf.append(event.text)
            if self._live:
                self._live.update(self._tail())
        elif isinstance(event, MessageEnd):
            self._stop_live()
            text = extract_text(event.message)
            if text.strip():
                self.console.print(Markdown(text))
            self._buf.clear()
            self._restart_live()
        elif isinstance(event, ToolCallEvent):
            args = _clip(json.dumps(event.tool_call.arguments, ensure_ascii=False), _ARG_TRUNC)
            # 动态内容一律走 Text（不解析 markup）——工具参数常含 [a-z]/list[int]
            # 这类方括号，f-string 拼 markup 会被 rich 吞内容（审核实测复现）
            self.console.print(Text(f"[tool] {event.tool_call.name} {args}", style="cyan"))
        elif isinstance(event, ToolResultEvent):
            if event.result.is_error:
                self.console.print(Text(_clip(event.result.content, _ERR_TRUNC), style="red"))
        elif isinstance(event, AgentEnd):
            if event.reason != "done":
                self.console.print(Text(f"[end] {event.reason}", style="yellow"))

    def _stop_live(self) -> None:
        if self._live:
            self._live.__exit__(None, None, None)
            self._live = None

    def _restart_live(self) -> None:  # 多轮 turn 之间恢复预览
        if self.console.is_terminal:
            self._live = Live(
                Spinner("dots", text="thinking…"),
                console=self.console,
                refresh_per_second=12,
                transient=True,
            )
            self._live.__enter__()

    def finish(self) -> None:
        """Turn 结束或被取消时必须调用（try/finally），清理 Live。"""
        self._stop_live()
        self._buf.clear()
