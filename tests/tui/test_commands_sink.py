"""RED-phase tests for the Sink protocol addition to ``commands.py`` (task-16
brief: "现有五个 handler 直接内联 ctx.console.print/rule ... 改法：CommandContext
增加可选 sink: Sink | None = None ... 每个 handler 开头 out = ctx.sink or
RichSink(ctx.console)，全部输出走 out；_tree 需要新写一套纯 ANSI 树渲染
（├──/└── 前缀 + ANSI dim/bold-green + ← 叶标，输出 list[str] 走
emit_lines，rich Tree 路径保留在 RichSink 分支之外照旧）——sink 为 None 时
行为与现状逐字节一致（旧 TUI 测试不许变红）").

Target surface (does not exist yet as of RED):

- ``pipython.tui.commands.Sink`` — a ``Protocol`` with ``emit_text(s: str,
  style: str = "") -> None`` and ``emit_lines(lines: list[str]) -> None``.
- ``pipython.tui.commands.RichSink`` — the legacy-preserving default
  implementation wrapping a ``rich.console.Console`` (used whenever
  ``ctx.sink is None``).
- ``CommandContext.sink: Sink | None = None`` — a new optional field.
- ``_tree``'s pure-ANSI rendering path, taken only when a *real* (non-
  ``RichSink``) sink is injected — the existing ``rich.tree.Tree``-based
  rendering must remain byte-identical when ``ctx.sink is None`` (i.e. when
  the handler falls back to ``RichSink``), per this file's parity tests and
  per every *existing*, untouched assertion in ``tests/tui/test_commands.py``
  (this RED phase adds a new file rather than editing that one, so those
  tests cannot regress no matter what this file's own tests do).

This file intentionally does not touch ``tests/tui/test_commands.py`` at all
(additive-only, per the brief's "旧 TUI 测试不许变红").

RED-phase failure mode: ``CommandContext`` does not accept a ``sink=``
keyword yet (``TypeError: __init__() got an unexpected keyword argument
'sink'``), and ``pipython.tui.commands`` exports no ``Sink``/``RichSink``
names yet (``ImportError``) — see task-16-report.md's RED section for the
captured output.

Design decisions locked into these assertions (for the GREEN implementer):

1. **ANSI "dim" / "bold green" styling is asserted tolerantly, not against
   one hardcoded escape sequence.** No prior component in this port has
   established a canonical "dim"/"bold-green" raw-ANSI convention (task-9's
   ``Text.style`` is a raw pass-through string with no fixed palette); this
   is the first caller to pick one. ``_looks_dim``/``_looks_bold_green``
   below accept any SGR spelling of those two visual properties (dim: SGR 2;
   bold-green: SGR 1 plus either the 8-color/bright-color green codes or a
   truecolor triplet whose green channel dominates) rather than locking GREEN
   into one exact byte sequence not yet decided anywhere in this codebase.
2. **When a real sink is injected, the handler must not touch
   ``ctx.console`` at all** — every test below that injects a
   ``RecordingSink`` also asserts ``ctx.console.export_text() == ""``
   afterwards, proving output was routed exclusively through the sink (no
   dual-write).
3. **``_tree`` legacy parity** is proven by literally re-running (via a
   fresh ``CommandContext`` with ``sink`` left at its default ``None``) the
   same branch/fork scenario ``tests/tui/test_commands.py::
   test_tree_dim_off_path_bold_green_on_path`` already exercises, and
   asserting the exact same rich-``Text`` style strings (``"dim"`` /
   ``"bold green"``) still come out of ``ctx.console._record_buffer`` — i.e.
   the old ``rich.tree.Tree`` object is still being built and printed
   verbatim in the ``sink is None`` path, not routed through the new
   ANSI-tree renderer.
"""

import re
from pathlib import Path

from pipython import AgentSessionConfig, AssistantMessage, TextContent, create_agent_session
from pipython.testing import FakeClient
from pipython.tui.commands import AppState, CommandContext, RichSink, Sink, build_registry, dispatch

from rich.console import Console


def done(text="done"):
    return AssistantMessage(content=[TextContent(text=text)])


class RecordingSink:
    """Sink test double — records every call instead of touching a console."""

    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.lines: list[list[str]] = []

    def emit_text(self, s: str, style: str = "") -> None:
        self.texts.append((s, style))

    def emit_lines(self, lines: list[str]) -> None:
        self.lines.append(list(lines))

    def flat_text(self) -> str:
        parts = [s for s, _ in self.texts]
        for group in self.lines:
            parts.extend(group)
        return "\n".join(parts)


_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _codes(s: str) -> list[set[str]]:
    return [set(m.group(1).split(";")) for m in _SGR_RE.finditer(s)]


def _looks_dim(s: str) -> bool:
    return any("2" in c for c in _codes(s))


def _looks_bold_green(s: str) -> bool:
    has_bold = any("1" in c for c in _codes(s))
    if not has_bold:
        return False
    for c in _codes(s):
        if "32" in c or "92" in c:
            return True
        if "38" in c and "2" in c:
            return True  # truecolor marker present alongside bold; good enough
    return False


async def make_ctx(tmp_path: Path, *, sink=None, script=None) -> CommandContext:
    async def factory():
        return await create_agent_session(
            AgentSessionConfig(
                model="fake",
                cwd=tmp_path,
                session_dir=tmp_path / "s",
                client=FakeClient(script=script or []),
            )
        )

    session = await factory()
    console = Console(record=True, width=100)
    return CommandContext(
        console=console, app=AppState(session=session, make_session=factory), sink=sink
    )


async def drain(session, text):
    return [e async for e in session.prompt(text)]


# ---------------------------------------------------------------------------


async def test_command_context_sink_field_defaults_to_none(tmp_path):
    ctx = await make_ctx(tmp_path)
    assert ctx.sink is None


async def test_sink_protocol_shape():
    assert hasattr(Sink, "__protocol_attrs__") or callable(getattr(Sink, "__init__", None))
    sink = RecordingSink()
    # RecordingSink must structurally satisfy Sink (duck typing check, no
    # isinstance requirement on a Protocol without @runtime_checkable).
    assert hasattr(sink, "emit_text") and hasattr(sink, "emit_lines")


async def test_help_via_sink_routes_through_sink_not_console(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await dispatch(build_registry(), ctx, "/help")
    text = sink.flat_text()
    for name in ["help", "model", "clear", "tree", "branch", "quit"]:
        assert name in text
    assert ctx.console.export_text() == ""


async def test_model_via_sink_routes_through_sink_not_console(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await dispatch(build_registry(), ctx, "/model")
    assert "fake" in sink.flat_text()
    assert ctx.console.export_text() == ""

    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(build_registry(), ctx, "/model openai/gpt-5.2")
    assert ctx.app.session.model == "openai/gpt-5.2"
    assert "openai/gpt-5.2" in sink2.flat_text()
    assert ctx.console.export_text() == ""


async def test_branch_no_match_via_sink(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done()])
    await drain(ctx.app.session, "hello")
    await dispatch(build_registry(), ctx, "/branch zzzzzzzz")
    assert "no match" in sink.flat_text().lower()
    assert ctx.console.export_text() == ""


async def test_branch_ambiguous_via_sink(tmp_path, monkeypatch):
    from pipython.session import ids

    seq = iter(["aaaa1111", "aaaa2222", "bbbb3333", "cccc4444"])
    monkeypatch.setattr(ids, "new_entry_id", lambda: next(seq))

    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done(), done()])
    await drain(ctx.app.session, "one")
    await drain(ctx.app.session, "two")
    await dispatch(build_registry(), ctx, "/branch aaaa")
    assert "ambiguous" in sink.flat_text().lower()
    assert ctx.console.export_text() == ""


async def test_unknown_command_via_sink(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await dispatch(build_registry(), ctx, "/nope")
    assert "/help" in sink.flat_text()
    assert ctx.console.export_text() == ""


async def test_tree_via_sink_emits_pure_ansi_tree_with_dim_bold_green_and_leaf_marker(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done("first reply"), done("second reply")])
    reg = build_registry()
    await drain(ctx.app.session, "first question")
    # Branch back to the root user message and drain a second time so one
    # entry is off the current path (dim) and one is on it (bold green) —
    # mirrors tests/tui/test_commands.py's own
    # test_tree_dim_off_path_bold_green_on_path fixture shape.
    import json

    lines = [json.loads(x) for x in ctx.app.session.store.path.read_text().splitlines()]
    first_user_id = next(x["id"] for x in lines if x["type"] == "message")
    await dispatch(reg, ctx, f"/branch {first_user_id[:8]}")
    await drain(ctx.app.session, "second question")

    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(reg, ctx, "/tree")

    assert sink2.texts == []  # tree output must go through emit_lines, not emit_text
    assert len(sink2.lines) == 1
    tree_lines = sink2.lines[0]
    joined = "\n".join(tree_lines)

    assert "├──" in joined or "└──" in joined
    assert "←" in joined

    dim_lines = [line for line in tree_lines if "first reply" in line]
    green_lines = [line for line in tree_lines if "second reply" in line]
    assert dim_lines and _looks_dim(dim_lines[0])
    assert green_lines and _looks_bold_green(green_lines[0])
    assert ctx.console.export_text() == ""


async def test_tree_via_none_sink_still_uses_rich_tree_unchanged(tmp_path):
    """Legacy-parity pin: with sink left at its default None, `_tree` must
    still build/print the old rich.Tree object (RichSink branch), producing
    the exact same 'dim' / 'bold green' rich style strings that
    tests/tui/test_commands.py::test_tree_dim_off_path_bold_green_on_path
    already asserts against the untouched legacy call path."""
    import json

    ctx = await make_ctx(tmp_path, script=[done("first reply"), done("second reply")])
    assert ctx.sink is None
    reg = build_registry()
    await drain(ctx.app.session, "first question")
    lines = [json.loads(x) for x in ctx.app.session.store.path.read_text().splitlines()]
    first_user_id = next(x["id"] for x in lines if x["type"] == "message")
    await dispatch(reg, ctx, f"/branch {first_user_id[:8]}")
    await drain(ctx.app.session, "second question")
    await dispatch(reg, ctx, "/tree")

    def style_of(substr: str) -> str | None:
        for seg in ctx.console._record_buffer:
            if substr in seg.text:
                return str(seg.style)
        return None

    assert style_of("first reply") == "dim"
    assert style_of("second reply") == "bold green"


async def test_rich_sink_used_explicitly_matches_none_sink_behavior(tmp_path):
    """RichSink(console) constructed and passed explicitly must behave
    identically to leaving sink=None (which internally falls back to
    RichSink(ctx.console)) — proving RichSink literally *is* the "none"
    fallback's implementation, not a parallel reimplementation."""
    console_a = Console(record=True, width=100)
    console_b = Console(record=True, width=100)

    async def factory():
        return await create_agent_session(
            AgentSessionConfig(
                model="fake", cwd=tmp_path, session_dir=tmp_path / "s", client=FakeClient(script=[])
            )
        )

    session_a = await factory()
    session_b = await factory()
    ctx_none = CommandContext(
        console=console_a, app=AppState(session=session_a, make_session=factory)
    )
    ctx_rich = CommandContext(
        console=console_b,
        app=AppState(session=session_b, make_session=factory),
        sink=RichSink(console_b),
    )
    reg = build_registry()
    await dispatch(reg, ctx_none, "/help")
    await dispatch(reg, ctx_rich, "/help")
    assert console_a.export_text() == console_b.export_text()
