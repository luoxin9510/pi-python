"""Tests for the slash-command registry + dispatch (``pipython.tui.commands``).

Task 18 (pi-tui engine becomes the only TUI): this file was
``test_commands_sink.py`` through task-16/17 — an *additive* RED-phase
suite for the ``Sink`` protocol, deliberately kept separate from the
then-still-alive legacy ``test_commands.py`` (console/``RichSink``-based)
so neither file's changes could regress the other. Task 18 deleted the
legacy TUI (and its ``RichSink``/``ctx.console`` fallback — ``rich`` is
dropped from ``pyproject.toml`` entirely, so ``RichSink`` cannot even be
kept unused) and renamed this file into the vacated ``test_commands.py``
slot, since the sink-based path is now simply *the* path, not "the new
one". Two consequences for the tests below, relative to the task-16/17
version of this file:

1. ``CommandContext`` no longer has a ``console`` field — every test
   constructs a ``CommandContext(app=..., sink=...)`` directly, and no test
   asserts ``ctx.console.export_text() == ""`` anymore (there is no
   ``console`` to assert against).
2. The two RichSink-legacy-parity tests that used to live here
   (``test_tree_via_none_sink_still_uses_rich_tree_unchanged``,
   ``test_rich_sink_used_explicitly_matches_none_sink_behavior``) are
   deleted along with ``RichSink`` itself — there is no more "None sink
   falls back to rich" behavior to pin.

Every test from the retired legacy ``test_commands.py`` whose regression
coverage had no sink-based equivalent yet has been ported forward here
(see ``.superpowers/sdd/task-18-report.md``'s coverage table for the full
before/after mapping): ``test_clear_swaps_session``,
``test_clear_inherits_current_model`` (issue #2 — now driven through
``pipython.tui.app._build_state``, the pi-tui engine's own holder-pattern
session factory, since the regression lives in that closure, not in
``commands.py``), ``test_quit_sets_flag``,
``test_tree_shows_model_change_target``, a successful (non-ambiguous,
non-"no match") ``/branch`` via sink, and — the hard-gate item explicitly
named in task-18-brief.md — ``test_branch_header_prefix_reports_no_match``
(session-header ids must never be treated as a valid branch target).
``test_summarize_message_dict_rules`` is ported from the retired
``test_render.py`` (``summarize_message_dict`` moved into this module
verbatim, per this module's own docstring).

Design decisions retained from the task-16 RED suite (still true):

1. **ANSI "dim" / "bold green" styling is asserted tolerantly, not against
   one hardcoded escape sequence** (``_looks_dim``/``_looks_bold_green``
   below) — no canonical convention is fixed anywhere else in this port.
2. **``_tree`` legacy parity (issue #4)** —
   ``test_tree_dim_off_path_bold_green_on_path_via_sink`` below is this
   port's equivalent of the retired ``test_commands.py``'s own
   ``test_tree_dim_off_path_bold_green_on_path``: dim off the current
   path, bold-green on it, both via the pure-ANSI tree renderer that is
   now ``_tree``'s only rendering path.
"""

import json
import re
from pathlib import Path

from pipython import (
    AgentSessionConfig,
    AssistantMessage,
    TextContent,
    create_agent_session,
    entry_id,
)
from pipython.testing import FakeClient
from pipython.tui.app import _build_state
from pipython.tui.commands import (
    AppState,
    CommandContext,
    Sink,
    build_registry,
    dispatch,
    summarize_message_dict,
)


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
    return CommandContext(
        app=AppState(session=session, make_session=factory), sink=sink or RecordingSink()
    )


async def drain(session, text):
    return [e async for e in session.prompt(text)]


# ---------------------------------------------------------------------------


async def test_command_context_requires_a_sink(tmp_path):
    # API break (Task 18, disclosed in commands.py's module docstring):
    # `sink` used to default to `None` (falling back to `RichSink`); with
    # `RichSink` gone, it is now a plain required field.
    async def factory():
        return await create_agent_session(
            AgentSessionConfig(model="fake", cwd=tmp_path, client=FakeClient(script=[]))
        )

    session = await factory()
    app_state = AppState(session=session, make_session=factory)
    try:
        CommandContext(app=app_state)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("CommandContext() must require sink now that RichSink is gone")


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


async def test_model_via_sink_routes_through_sink_not_console(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await dispatch(build_registry(), ctx, "/model")
    assert "fake" in sink.flat_text()

    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(build_registry(), ctx, "/model openai/gpt-5.2")
    assert ctx.app.session.model == "openai/gpt-5.2"
    assert "openai/gpt-5.2" in sink2.flat_text()


async def test_clear_swaps_session(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    old = ctx.app.session
    await dispatch(build_registry(), ctx, "/clear")
    assert ctx.app.session is not old
    assert ctx.app.session.store.path != old.store.path
    assert "new session" in sink.flat_text()


async def test_clear_inherits_current_model(tmp_path, monkeypatch):
    # issue #2: /clear used to close over the *startup* model, so a /model
    # switch followed by /clear would silently revert to the startup model.
    # Driven through pipython.tui.app._build_state — the pi-tui engine's own
    # holder-pattern session factory (formerly app2.py's _build_state) —
    # since the fix lives in that closure, not in commands.py itself.
    monkeypatch.setattr("pipython.session_facade.DEFAULT_SESSION_DIR", tmp_path / "sessions")
    app_state = await _build_state("fake/model", tmp_path, FakeClient(script=[]))
    ctx = CommandContext(app=app_state, sink=RecordingSink())
    reg = build_registry()
    await dispatch(reg, ctx, "/model other/model")
    await dispatch(reg, ctx, "/clear")
    assert ctx.app.session.model == "other/model"


async def test_quit_sets_flag(tmp_path):
    ctx = await make_ctx(tmp_path)
    await dispatch(build_registry(), ctx, "/quit")
    assert ctx.app.should_quit is True


async def test_tree_shows_model_change_target(tmp_path):
    ctx = await make_ctx(tmp_path)
    reg = build_registry()
    await dispatch(reg, ctx, "/model somemodel/xyz")
    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(reg, ctx, "/tree")
    assert "model_change → xyz" in sink2.flat_text()


async def test_branch_prefix_match_via_sink(tmp_path):
    ctx = await make_ctx(tmp_path, script=[done()])
    await drain(ctx.app.session, "hello")
    lines = [json.loads(x) for x in ctx.app.session.store.path.read_text().splitlines()]
    first_id = next(x["id"] for x in lines if x["type"] == "message")
    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(build_registry(), ctx, f"/branch {first_id[:4]}")
    assert ctx.app.session.store.leaf_id == first_id
    assert f"branched to {first_id[:8]}" in sink2.flat_text()


async def test_branch_no_match_via_sink(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done()])
    await drain(ctx.app.session, "hello")
    await dispatch(build_registry(), ctx, "/branch zzzzzzzz")
    assert "no match" in sink.flat_text().lower()


async def test_branch_header_prefix_reports_no_match(tmp_path):
    # Hard-gate item (task-18-brief.md: "/branch 头防护"): a session header
    # id is a legal string a prefix can uniquely match, but it must never be
    # accepted as a branch target — branching onto it points leaf_id at an
    # entry current_path excludes, and every subsequent /tree or prompt()
    # call ValueErrors (the regression this test pins; see commands.py's
    # _branch docstring comment).
    ctx = await make_ctx(tmp_path, script=[done()])
    await drain(ctx.app.session, "hello")
    header_id = entry_id(ctx.app.session.store.entries[0])
    assert header_id is not None
    leaf_before = ctx.app.session.store.leaf_id
    sink2 = RecordingSink()
    ctx.sink = sink2
    await dispatch(build_registry(), ctx, f"/branch {header_id[:8]}")
    assert "no match" in sink2.flat_text().lower()
    assert ctx.app.session.store.leaf_id == leaf_before


async def test_branch_ambiguous_via_sink(tmp_path, monkeypatch):
    from pipython.session import ids

    seq = iter(["aaaa1111", "aaaa2222", "bbbb3333", "cccc4444"])
    monkeypatch.setattr(ids, "new_entry_id", lambda: next(seq))

    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done(), done()])
    await drain(ctx.app.session, "one")
    await drain(ctx.app.session, "two")
    leaf_before = ctx.app.session.store.leaf_id
    await dispatch(build_registry(), ctx, "/branch aaaa")
    assert "ambiguous" in sink.flat_text().lower()
    assert ctx.app.session.store.leaf_id == leaf_before


async def test_unknown_command_via_sink(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await dispatch(build_registry(), ctx, "/nope")
    assert "/help" in sink.flat_text()


async def test_tree_dim_off_path_bold_green_on_path_via_sink(tmp_path):
    # issue #4's equivalence pin: dim off the current path, bold-green on
    # it — this port's equivalent of the retired legacy test_commands.py's
    # test_tree_dim_off_path_bold_green_on_path, now against the pure-ANSI
    # tree renderer that is _tree's only rendering path.
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink, script=[done("first reply"), done("second reply")])
    reg = build_registry()
    await drain(ctx.app.session, "first question")
    # Branch back to the root user message and drain a second time so one
    # entry is off the current path (dim) and one is on it (bold green).
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
    assert "first question" in joined  # user message summary appears in the tree

    dim_lines = [line for line in tree_lines if "first reply" in line]
    green_lines = [line for line in tree_lines if "second reply" in line]
    assert dim_lines and _looks_dim(dim_lines[0])
    assert green_lines and _looks_bold_green(green_lines[0])


def test_summarize_message_dict_rules():
    # Ported from the retired test_render.py — summarize_message_dict moved
    # into this module verbatim (see module docstring).
    assert summarize_message_dict({"role": "user", "content": "x" * 80}).endswith("…")
    assert (
        summarize_message_dict(
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}
        )
        == "hello"
    )
    assert (
        summarize_message_dict(
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "1", "name": "edit", "arguments": {}}],
            }
        )
        == "[tool: edit]"
    )
