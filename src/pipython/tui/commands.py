"""Slash-command registry + dispatch for the pipython TUI (spec §6).

Task 18 (pi-tui engine becomes the only TUI): the legacy prompt_toolkit/rich
stack (``app.py``, ``keys.py``, ``render.py``) and its console-based
``RichSink`` fallback are retired along with it — ``rich``/``prompt_toolkit``/
``rapidfuzz`` are dropped from ``pyproject.toml`` entirely (spec's Task 18
deletion gate), so ``RichSink`` (which wrapped ``rich.console.Console``)
cannot be kept even as an unused fallback: importing ``rich`` at module load
time would crash as soon as the dependency is gone.

**API break (disclosed per task-18-brief.md's instruction to surface this):**
``CommandContext`` no longer carries a ``console: rich.console.Console``
field, and ``sink`` is no longer optional — every caller must supply a real
``Sink`` (the pi-tui engine's ``app.py`` always did, via ``_ComponentSink``;
it was only the *removed* legacy ``app.py`` that had no such object to pass
and relied on the ``None`` → ``RichSink(console)`` fallback). Every handler
below now writes through ``ctx.sink`` unconditionally.

``_tree``'s rendering is now unconditionally the pure-ANSI tree introduced in
task-16 for the sink path (``├──``/``└──`` connectors, raw ANSI
dim/bold-green SGR, ``←`` leaf marker) — this was previously a branch taken
only for a "real" (non-``RichSink``) sink; with ``RichSink`` gone it is
simply how ``_tree`` renders, unconditionally. Equivalence for the retired
``rich.tree.Tree`` rendering (dim/bold-green styling, issue #4) is pinned by
``tests/tui/test_commands.py::test_tree_dim_off_path_bold_green_on_path_via_sink``
(carried over verbatim from task-16's sink-parity suite) — see
``.superpowers/sdd/task-18-report.md``'s coverage table.

All dynamic content is printed via ``sink.emit_text``/``emit_lines``, never
f-string-interpolated into a markup string — this predates and is unrelated
to the ``rich`` removal (it was already true of every sink-based handler);
kept as plain formatted strings here since there is no markup parser left in
this module to guard against.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

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

_SUMMARY_TRUNC = 50


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize_message_dict(d: dict) -> str:
    """Moved here verbatim from the retired ``render.py`` (Task 18) — the
    only remaining caller is ``_label`` below. Rules: a plain string
    ``content`` is truncated; a list ``content`` prefers its first ``text``
    block, falling back to a ``[tool: <name>]`` marker for a ``toolCall``
    block if no text block exists; anything else falls back to the
    message's ``role``."""
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


@dataclass
class AppState:
    session: AgentSession
    make_session: Callable[[], Awaitable[AgentSession]]
    should_quit: bool = False


class Sink(Protocol):
    """Output boundary for slash-command handlers (task-16-brief.md): the
    pi-tui engine's app loop (``app.py``) implements this over its component
    tree (appending ``Text``/lines to the transcript ``Container``) via
    ``_ComponentSink`` — the sole production implementation since Task 18
    retired the legacy ``RichSink``/console fallback."""

    def emit_text(self, s: str, style: str = "") -> None: ...

    def emit_lines(self, lines: list[str]) -> None: ...


@dataclass
class CommandContext:
    app: AppState
    sink: Sink


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
# Pure-ANSI tree renderer (task-16): now ``_tree``'s only rendering path.
# No canonical dim/bold-green ANSI convention existed anywhere in this port
# before task-16 (task-9's ``Text.style`` is a raw pass-through string with
# no fixed palette) — these are this module's own pick, plain SGR 2 (dim) and
# SGR 1+32 (bold green), matching what ``tests/tui/test_commands.py``'s
# ``_looks_dim``/``_looks_bold_green`` tolerantly accept.
# =============================================================================

_ANSI_DIM = "\x1b[2m"
_ANSI_BOLD_GREEN = "\x1b[1;32m"
_ANSI_RESET = "\x1b[0m"


def _render_ansi_tree_lines(store) -> list[str]:
    """``├──``/``└──``-connector tree, one line per entry, styled dim
    (off the current path) or bold-green (on it), with the leaf entry
    suffixed ``" ←"``."""
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
    for cmd in sorted(build_registry().values(), key=lambda c: c.name):
        ctx.sink.emit_text(f"/{cmd.name:<8} {cmd.description}")


async def _model(ctx: CommandContext, arg: str) -> None:
    if arg:
        ctx.app.session.set_model(arg)
        ctx.sink.emit_text(f"model → {arg}")
    else:
        ctx.sink.emit_text(f"model: {ctx.app.session.model}")


async def _clear(ctx: CommandContext, _: str) -> None:
    ctx.app.session = await ctx.app.make_session()
    ctx.sink.emit_text("new session")


async def _tree(ctx: CommandContext, _: str) -> None:
    store = ctx.app.session.store
    ctx.sink.emit_lines(_render_ansi_tree_lines(store))


async def _branch(ctx: CommandContext, arg: str) -> None:
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
        ctx.sink.emit_text(f"branched to {match[:8]}")
    elif not matches:
        ctx.sink.emit_text("no match", style="red")
    else:
        ctx.sink.emit_text(f"ambiguous prefix ({len(matches)} matches)", style="red")


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
        ctx.sink.emit_text(f"unknown command /{name} — try /help", style="red")
        return
    await cmd.handler(ctx, arg.strip())
