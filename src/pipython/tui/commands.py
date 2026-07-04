"""Slash-command registry + dispatch for the pipython TUI (spec §6).

All dynamic content is printed via ``rich.Text``, never f-string markup: help
descriptions may contain ``[litellm-id]``-shaped placeholders, tree labels
contain message excerpts, and unknown-command handling echoes back arbitrary
user input. rich's markup parser would silently swallow bracketed substrings
in any of these if we built them as markup strings, so we route them through
``rich.Text`` (which never parses markup) instead.

Task 16 addition — Sink dual-track (task-16-brief.md): every handler used to
print straight to ``ctx.console``. The new-engine app loop (``app2.py``) has
no ``rich.Console`` to print to (its transcript is a tree of ``Component``
objects) — so ``CommandContext`` grows an optional ``sink: Sink | None``, and
each handler now goes through ``out = ctx.sink or RichSink(ctx.console)``.
``RichSink`` is the *literal* old behavior (a thin wrapper that still prints
``rich.Text`` onto ``ctx.console``) — when ``ctx.sink`` is left at its
default ``None``, every handler's output is byte-identical to before this
change (verified by ``tests/tui/test_commands.py``, which is untouched).

``_tree`` is the one handler that can't be expressed as a handful of
``out.emit_text(...)`` calls either way: its rich path builds a real
``rich.tree.Tree`` object (dim/bold-green styled, ``←`` leaf marker) and
prints *that* — no ``Sink`` method takes a ``Tree``. So ``_tree`` branches
explicitly: sink is ``None``/``RichSink`` → build and print the same
``rich.tree.Tree`` as before (parity pinned by
``tests/tui/test_commands_sink.py::test_tree_via_none_sink_still_uses_rich_tree_unchanged``);
a real (non-``RichSink``) sink → a new pure-ANSI tree renderer
(``_render_ansi_tree_lines``: ``├──``/``└──`` connectors, raw ANSI
dim/bold-green SGR, ``←`` leaf marker) emitted as a list of lines via
``out.emit_lines(...)``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from rich.console import Console
from rich.text import Text
from rich.tree import Tree

from pipython import (
    AgentSession,
    MessageEntry,
    ModelChangeEntry,
    SessionHeader,
    current_path,
    entry_id,
    entry_parent_id,
    entry_type,
)

from .render import summarize_message_dict


@dataclass
class AppState:
    session: AgentSession
    make_session: Callable[[], Awaitable[AgentSession]]
    should_quit: bool = False


class Sink(Protocol):
    """Output boundary for slash-command handlers (task-16-brief.md): the
    new-engine app loop implements this over its component tree (appending
    ``Text``/lines to the transcript ``Container``); ``RichSink`` (below)
    implements it over a ``rich.Console`` for the legacy path."""

    def emit_text(self, s: str, style: str = "") -> None: ...

    def emit_lines(self, lines: list[str]) -> None: ...


class RichSink:
    """Default ``Sink``: prints straight to a ``rich.Console`` via
    ``rich.Text`` (never markup — see module docstring). This is the exact
    implementation ``ctx.sink is None`` falls back to
    (``RichSink(ctx.console)``), so it *is* the pre-task-16 behavior, not a
    reimplementation of it — parity is structural, not coincidental."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def emit_text(self, s: str, style: str = "") -> None:
        self.console.print(Text(s, style=style))

    def emit_lines(self, lines: list[str]) -> None:
        for line in lines:
            self.console.print(Text(line))


@dataclass
class CommandContext:
    console: Console
    app: AppState
    sink: Sink | None = None


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    handler: Callable[[CommandContext, str], Awaitable[None]]


def _label(e) -> str:
    eid = (entry_id(e) or "????????")[:8]
    if isinstance(e, MessageEntry):
        return f"{eid} {e.message.get('role', '?')}: {summarize_message_dict(e.message)}"
    if isinstance(e, ModelChangeEntry):
        return f"{eid} model_change → {e.model_id}"
    return f"{eid} {entry_type(e) or '?'}"


# =============================================================================
# Pure-ANSI tree renderer (task-16): the ``_tree`` handler's real-sink path.
# No canonical dim/bold-green ANSI convention existed anywhere in this port
# before this task (task-9's ``Text.style`` is a raw pass-through string with
# no fixed palette) — these are this module's own pick, plain SGR 2 (dim) and
# SGR 1+32 (bold green), matching what ``tests/tui/test_commands_sink.py``'s
# ``_looks_dim``/``_looks_bold_green`` tolerantly accept.
# =============================================================================

_ANSI_DIM = "\x1b[2m"
_ANSI_BOLD_GREEN = "\x1b[1;32m"
_ANSI_RESET = "\x1b[0m"


def _render_ansi_tree_lines(store) -> list[str]:
    """``├──``/``└──``-connector tree, one line per entry, styled dim
    (off the current path) or bold-green (on it), with the leaf entry
    suffixed ``" ←"`` — the pure-ANSI counterpart of the ``rich.tree.Tree``
    the ``RichSink``/``sink=None`` path below still builds verbatim."""
    entries = [e for e in store.entries if entry_id(e) and not isinstance(e, SessionHeader)]
    on_path = {entry_id(e) for e in current_path(store.entries, store.leaf_id)}
    children: dict[str | None, list] = {}
    for e in entries:
        children.setdefault(entry_parent_id(e), []).append(e)

    lines = ["session"]

    def walk(parent_id: str | None, prefix: str) -> None:
        kids = children.get(parent_id, [])
        for i, e in enumerate(kids):
            eid = entry_id(e)
            is_last = i == len(kids) - 1
            connector = "└── " if is_last else "├── "
            label = _label(e)
            if eid == store.leaf_id:
                label += " ←"
            style = _ANSI_BOLD_GREEN if eid in on_path else _ANSI_DIM
            lines.append(f"{prefix}{connector}{style}{label}{_ANSI_RESET}")
            walk(eid, prefix + ("    " if is_last else "│   "))

    walk(None, "")
    return lines


async def _help(ctx: CommandContext, _: str) -> None:
    out = ctx.sink or RichSink(ctx.console)
    for cmd in sorted(build_registry().values(), key=lambda c: c.name):
        # Text：描述含 [litellm-id] 这类方括号，markup 拼接会被吞（复审实测）
        out.emit_text(f"/{cmd.name:<8} {cmd.description}")


async def _model(ctx: CommandContext, arg: str) -> None:
    out = ctx.sink or RichSink(ctx.console)
    if arg:
        ctx.app.session.set_model(arg)
        out.emit_text(f"model → {arg}")
    else:
        out.emit_text(f"model: {ctx.app.session.model}")


async def _clear(ctx: CommandContext, _: str) -> None:
    ctx.app.session = await ctx.app.make_session()
    out = ctx.sink or RichSink(ctx.console)
    if isinstance(out, RichSink):
        # console.rule() has no Sink equivalent (Sink is text/lines-only) —
        # keep the exact legacy visual for the rich path.
        out.console.rule("new session")
    else:
        out.emit_text("new session")


async def _tree(ctx: CommandContext, _: str) -> None:
    store = ctx.app.session.store
    out = ctx.sink or RichSink(ctx.console)

    if isinstance(out, RichSink):
        # 过滤 header：leaf 初始为 None，首条消息 parentId 也是 None，不滤则 header
        # 会被渲染成根级兄弟节点（审核发现）
        entries = [e for e in store.entries if entry_id(e) and not isinstance(e, SessionHeader)]
        on_path = {entry_id(e) for e in current_path(store.entries, store.leaf_id)}
        children: dict[str | None, list] = {}
        for e in entries:
            children.setdefault(entry_parent_id(e), []).append(e)
        tree = Tree("session")

        def attach(node, parent_id):
            for e in children.get(parent_id, []):
                eid = entry_id(e)
                label = _label(e)
                if eid == store.leaf_id:
                    label += " ←"
                style = "bold green" if eid in on_path else "dim"
                # Text 不解析 markup——消息摘要常含方括号（审核实测会被吞）
                attach(node.add(Text(label, style=style)), eid)

        attach(tree, None)
        out.console.print(tree)
        return

    out.emit_lines(_render_ansi_tree_lines(store))


async def _branch(ctx: CommandContext, arg: str) -> None:
    out = ctx.sink or RichSink(ctx.console)
    prefix = arg.strip()
    store = ctx.app.session.store
    # 排除 header：header.id 也是合法字符串，前缀能唯一命中它，但它不在
    # current_path 的候选集里——branch 到它会让 leaf_id 指向一个 current_path
    # 会剔除的条目，后续 /tree 与每次 prompt 都 ValueError 崩溃（复审发现）。
    ids = (entry_id(e) for e in store.entries if not isinstance(e, SessionHeader))
    matches = [eid for eid in ids if eid and eid.startswith(prefix)] if prefix else []
    if len(matches) == 1:
        match = matches[0]
        ctx.app.session.branch(match)
        out.emit_text(f"branched to {match[:8]}")
    elif not matches:
        out.emit_text("no match", style="red")
    else:
        out.emit_text(f"ambiguous prefix ({len(matches)} matches)", style="red")


async def _quit(ctx: CommandContext, _: str) -> None:
    ctx.app.should_quit = True


def build_registry() -> dict[str, Command]:
    cmds = [
        Command("help", "列出全部命令", _help),
        Command("model", "查看/切换模型：/model [litellm-id]", _model),
        Command("clear", "开新会话", _clear),
        Command("tree", "查看会话树", _tree),
        Command("branch", "回到历史节点分叉：/branch <id前缀>", _branch),
        Command("quit", "退出", _quit),
    ]
    return {c.name: c for c in cmds}


async def dispatch(registry: dict[str, Command], ctx: CommandContext, line: str) -> None:
    name, _, arg = line[1:].partition(" ")
    cmd = registry.get(name)
    if cmd is None:
        out = ctx.sink or RichSink(ctx.console)
        out.emit_text(f"unknown command /{name} — try /help", style="red")
        return
    await cmd.handler(ctx, arg.strip())
