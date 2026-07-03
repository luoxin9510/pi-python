"""Slash-command registry + dispatch for the pipython TUI (spec §6).

All dynamic content is printed via ``rich.Text``, never f-string markup: help
descriptions may contain ``[litellm-id]``-shaped placeholders, tree labels
contain message excerpts, and unknown-command handling echoes back arbitrary
user input. rich's markup parser would silently swallow bracketed substrings
in any of these if we built them as markup strings, so we route them through
``rich.Text`` (which never parses markup) instead.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rich.console import Console
from rich.text import Text
from rich.tree import Tree

from pipython import (
    AgentSession,
    MessageEntry,
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


@dataclass
class CommandContext:
    console: Console
    app: AppState


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    handler: Callable[[CommandContext, str], Awaitable[None]]


def _label(e) -> str:
    eid = (entry_id(e) or "????????")[:8]
    if isinstance(e, MessageEntry):
        return f"{eid} {e.message.get('role', '?')}: {summarize_message_dict(e.message)}"
    return f"{eid} {entry_type(e) or '?'}"


async def _help(ctx: CommandContext, _: str) -> None:
    for cmd in sorted(build_registry().values(), key=lambda c: c.name):
        # Text：描述含 [litellm-id] 这类方括号，markup 拼接会被吞（复审实测）
        ctx.console.print(Text(f"/{cmd.name:<8} {cmd.description}"))


async def _model(ctx: CommandContext, arg: str) -> None:
    if arg:
        ctx.app.session.set_model(arg)
        ctx.console.print(Text(f"model → {arg}"))
    else:
        ctx.console.print(Text(f"model: {ctx.app.session.model}"))


async def _clear(ctx: CommandContext, _: str) -> None:
    ctx.app.session = await ctx.app.make_session()
    ctx.console.rule("new session")


async def _tree(ctx: CommandContext, _: str) -> None:
    store = ctx.app.session.store
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
    ctx.console.print(tree)


async def _branch(ctx: CommandContext, arg: str) -> None:
    prefix = arg.strip()
    store = ctx.app.session.store
    ids = (entry_id(e) for e in store.entries)
    matches = [eid for eid in ids if eid and eid.startswith(prefix)] if prefix else []
    if len(matches) == 1:
        match = matches[0]
        ctx.app.session.branch(match)
        ctx.console.print(f"branched to {match[:8]}")
    elif not matches:
        ctx.console.print("[red]no match[/red]")
    else:
        ctx.console.print(f"[red]ambiguous prefix ({len(matches)} matches)[/red]")


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
        ctx.console.print(Text(f"unknown command /{name} — try /help", style="red"))
        return
    await cmd.handler(ctx, arg.strip())
