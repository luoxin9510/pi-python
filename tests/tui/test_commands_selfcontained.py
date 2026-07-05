"""Tests for the phase-4 self-contained slash commands (/hotkeys /new /copy
/session /changelog) plus the ``_format_key`` helper — ``commands.py``.

Handler tests use a REAL ``AppState``/``create_agent_session``/``FakeClient``
(no duck-typed fakes — ``CommandContext.app`` is typed as the concrete
``AppState``, so a duck-typed stand-in would fail pyright's
``reportArgumentType``, per this module's task brief). Entries are appended
via the real ``store.append`` (real JSONL on disk), hand-built to exercise
branch-aware traversal (``current_path``) rather than physical entry order.

Assertions go through a locally-constructed ``sink = RecordingSink()``
(concrete type) rather than ``ctx.sink.flat_text()`` — ``CommandContext.sink``
is typed as the ``Sink`` Protocol, which has no ``flat_text``, so reading it
off ``ctx.sink`` directly would pyright-error. This mirrors
``test_commands.py``'s own convention.
"""

from pipython import (
    AgentSessionConfig,
    MessageEntry,
    create_agent_session,
)
from pipython.session import ids
from pipython.testing import FakeClient
from pipython.tui import commands
from pipython.tui.commands import (
    AppState,
    CommandContext,
    _changelog,
    _copy,
    _format_key,
    _hotkeys,
    _new,
    _session,
    build_registry,
)


class RecordingSink:
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


async def make_ctx(tmp_path, *, sink=None, script=None) -> CommandContext:
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


def _append(store, eid, parent, message) -> None:
    """Append a hand-built entry to the REAL store (writes real JSONL; sets leaf_id=eid)."""
    store.append(MessageEntry(id=eid, parent_id=parent, timestamp=ids.iso_now(), message=message))


def _asst_msg(text=None, *, tool=False, usage=None) -> dict:
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "toolCall", "id": "c", "name": "ls", "arguments": {}})
    msg = {"role": "assistant", "content": content}
    if usage is not None:
        msg["usage"] = usage
    return msg


# --- _format_key (pure) ---


def test_format_key_capitalizes_and_joins():
    assert _format_key("ctrl+b") == "Ctrl+B"
    assert _format_key(["left", "ctrl+b"]) == "Left / Ctrl+B"
    assert _format_key("enter") == "Enter"


def test_format_key_camelcase_preserved():
    # .capitalize() would wrongly yield "Pageup"; must keep interior caps
    assert _format_key("pageUp") == "PageUp"


def test_format_key_macos_option(monkeypatch):
    monkeypatch.setattr(commands.sys, "platform", "darwin")
    assert _format_key("alt+b") == "Option+B"


def test_format_key_non_macos_alt(monkeypatch):
    monkeypatch.setattr(commands.sys, "platform", "linux")
    assert _format_key("alt+b") == "Alt+B"


# --- /hotkeys ---
# NOTE: assert via a LOCAL `sink = RecordingSink()` (concrete type), never
# `ctx.sink.flat_text()` — CommandContext.sink is typed as the Sink Protocol,
# which has no flat_text, so pyright errors on ctx.sink.flat_text(). This
# mirrors test_commands.py's convention.


async def test_hotkeys_lists_key_help(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _hotkeys(ctx, "")
    joined = sink.flat_text()
    assert "Navigation" in joined
    assert "History" in joined  # history nav is implemented (editor cursorUp/Down)
    assert "Completion" in joined  # autocomplete is implemented (tui.select.*)
    assert "Ctrl+B" in joined or "Left" in joined  # formatted cursor keys
    assert "Ctrl+O" in joined  # app.tools.expand in-table
    assert "Ctrl+C" in joined and "Ctrl+D" in joined  # hardcoded app-level bytes


# --- /new ---


async def test_new_swaps_session(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    old = ctx.app.session
    await _new(ctx, "")
    assert ctx.app.session is not old
    assert "new session" in sink.flat_text()


# --- /copy ---


async def test_copy_takes_last_assistant_text_on_path(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first answer"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second answer"))
    got = {}
    monkeypatch.setattr(
        commands, "copy_to_clipboard", lambda t: got.setdefault("text", t) or "pbcopy"
    )
    await _copy(ctx, "")
    assert got["text"] == "second answer"
    assert "Copied" in sink.flat_text()


async def test_copy_is_branch_aware(tmp_path, monkeypatch):
    # a2 ("second") is physically last but OFF the current path; leaf → a1 ("first").
    ctx = await make_ctx(tmp_path)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first answer"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second answer"))
    store.leaf_id = "a1"  # branch back — current path is now [u1, a1]
    got = {}
    monkeypatch.setattr(
        commands, "copy_to_clipboard", lambda t: got.setdefault("text", t) or "pbcopy"
    )
    await _copy(ctx, "")
    assert got["text"] == "first answer"  # on-path, NOT physical-last "second answer"


async def test_copy_no_assistant_message(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    _append(ctx.app.session.store, "u1", None, {"role": "user", "content": "hi"})
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert "No agent messages" in sink.flat_text()


async def test_copy_pure_toolcall_is_no_message(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "x"})
    _append(store, "a1", "u1", _asst_msg(text=None, tool=True))  # toolCall only, no text
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert "No agent messages" in sink.flat_text()


# --- /session ---


async def test_session_stats(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(
        store,
        "a1",
        "u1",
        _asst_msg("hi", tool=True, usage={"inputTokens": 100, "outputTokens": 20, "cost": 0.01}),
    )
    _append(store, "u2", "a1", {"role": "user", "content": "again"})
    _append(
        store,
        "a2",
        "u2",
        _asst_msg("ok", usage={"inputTokens": 50, "outputTokens": 10, "cost": 0.005}),
    )
    await _session(ctx, "")
    joined = sink.flat_text()
    assert "2 user, 2 assistant" in joined
    assert "Tool calls: 1" in joined
    assert "↑150 ↓30" in joined
    assert "$0.0150" in joined
    assert "fake" in joined  # model line


async def test_session_counts_toolresult(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("run", tool=True))
    _append(store, "t1", "a1", {"role": "toolResult", "content": "output"})
    await _session(ctx, "")
    assert "1 tool result" in sink.flat_text()


async def test_session_is_branch_aware(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second"))
    store.leaf_id = "a1"  # off-path: u2/a2 excluded; current path [u1, a1]
    await _session(ctx, "")
    assert "1 user, 1 assistant" in sink.flat_text()


async def test_session_empty(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _session(ctx, "")
    assert "0 user, 0 assistant, 0 tool result" in sink.flat_text()  # empty → all zero


# --- /changelog ---


async def test_changelog_shows_version_and_repo(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _changelog(ctx, "")
    joined = sink.flat_text()
    from pipython import __version__

    assert __version__ in joined
    assert "github.com/luoxin9510/pi-python" in joined


# --- registry ---


def test_registry_has_11_commands():
    reg = build_registry()
    for name in (
        "help",
        "model",
        "clear",
        "tree",
        "branch",
        "quit",
        "hotkeys",
        "new",
        "copy",
        "session",
        "changelog",
    ):
        assert name in reg
    assert len(reg) == 11
