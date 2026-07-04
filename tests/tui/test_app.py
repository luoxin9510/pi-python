"""Integration suite for the pipython TUI's main loop + commands Sink
dual-track, per ``.superpowers/sdd/task-16-brief.md`` and spec §6
(``docs/superpowers/specs/2026-07-04-phase3-pi-tui-port-design.md``).

This file was named ``test_app2.py`` through Tasks 16-17, targeting the
pi-tui engine module while it was developed *alongside* the legacy
prompt_toolkit/rich TUI under a disambiguating "2" suffix (spec §8). Task 18
(pi-tui engine becomes the only TUI) deleted the legacy engine outright,
dropped the "2" suffix from the module and its entry point, and renamed
this file into the vacated ``test_app.py`` slot — every reference below to
the module or its entry point uses the current (un-suffixed) names. This
file also carries forward, from
the retired ``test_app_helpers.py``/``test_render.py``: unit tests for
``load_fake_client``/``make_client`` (moved into this module verbatim) and
``extract_text`` (ditto), plus new integration-level tests closing gaps the
task-18 coverage table found — tool-call-line truncation, a successful tool
result's content never being echoed, ``ErrorEvent``/non-``"done"``
``AgentEnd`` rendering, and a slash-command handler exception not crashing
the app loop (see ``.superpowers/sdd/task-18-report.md`` for the full
before/after mapping).

Target surface: ``async run_app(*, model: str, cwd: Path, client:
ModelClient | None = None, term: TerminalIO | None = None) -> None`` in
``src/pipython/tui/app.py``.

This is the *first full assembly* of the phase-3 engine (Task 7/8 `TUI`
+ Task 9-15 components) with a real `pipython` `AgentSession`, driven
end-to-end through injected fakes: ``FakeClient`` (the only allowed LLM
stand-in, spec §7) for the model, and a `RecordingTerm`-derived double for
the terminal — "no real terminal throughout" per the brief.

======================================================================
Locked test-harness design decisions (read before touching this file)
======================================================================

1. **stdin injection seam: ``sys.stdin.fileno()``.** ``run_app`` has no
   dedicated "input source" parameter in its Produces signature — only
   ``term`` (the *output* boundary, matching ``engine.terminal.TerminalIO``).
   Consuming live keystrokes therefore still has to go through a real
   ``loop.add_reader(fd, ...)`` on *some* fd, and the only way these tests
   can inject scripted bytes without a real pty is to make that fd a plain
   OS pipe. This file's ``stdin_pipe`` fixture creates a real ``os.pipe()``
   and monkeypatches ``sys.stdin`` to a tiny stub whose ``fileno()`` returns
   the pipe's read end — **the same convention `engine/terminal.py`'s own
   ``RealTerminal._enter_raw_mode``/``_read_negotiation_reply`` already use**
   (``sys.stdin.fileno()``, guarded, never a hardcoded literal ``0``). Per
   this precedent, **`run_app` must resolve the stdin fd via
   `sys.stdin.fileno()`** (not a hardcoded ``0``) for these tests to be able
   to inject input at all. Bytes are written with a plain ``os.write()`` —
   a real pipe, not a mock — consistent with this repo's "real integration"
   testing convention (CLAUDE.md).

2. **The injected term double (`FakeRealTerm`) is richer than the bare
   `TerminalIO` Protocol** (`write`/`columns`/`rows`): it also carries
   `kitty_enabled`, `on_resize(cb)`, and `drain_pending()` — the same three
   extra members `RealTerminal` (`engine/terminal.py`) exposes beyond the
   Protocol. `run_app` must consult these (defensively — a plain
   `TerminalIO` that lacks them is still a legal `term=` value per the type
   hint) to satisfy obligations (a)/(b)/(c) below. `FakeRealTerm` subclasses
   the existing `engine.conftest.RecordingTerm` test double (Task 7's own
   fixture) rather than reimplementing its `write`/`screen()` diff-replay
   machinery.

3. **Four wiring obligations from the task ledger** (each has one or more
   dedicated tests below, cross-referenced by name):
   a. `RealTerminal.drain_pending()` bytes MUST be fed into the input
      pipeline *before* the live reader attaches —
      `test_pending_bytes_are_processed_before_and_ordered_ahead_of_live_input`.
   b. The app layer MUST NOT `loop.add_signal_handler(signal.SIGWINCH, ...)`
      — resize goes through `term.on_resize(tui.on_resize)` only —
      `test_sigwinch_not_registered_via_loop_and_on_resize_is_wired_to_a_render`.
   c. `RealTerminal.kitty_enabled` MUST thread into the editor's input path
      (editor.py deviation-7 checkpoint) —
      `test_kitty_enabled_true_drops_ambiguous_legacy_altleft_frame` /
      `test_kitty_enabled_false_falls_back_to_legacy_altleft`.
   d. Submit MUST use `Editor.get_expanded_text()` (paste markers expanded)
      — `test_submit_sends_full_expanded_paste_text_not_the_folded_marker`.

4. **Streaming interleaving: `SteppedFakeClient`.** Plain `FakeClient.stream()`
   has no real ``await`` suspension point, so driving it inside `run_app`'s
   turn-consuming loop would run the *entire* scripted turn in one
   uninterrupted scheduler burst — collapsing `TUI.request_render()`'s
   `call_soon` coalescing into a single final frame and making "streaming
   Text grows incrementally, then gets replaced by rendered markdown at
   message_end" unobservable from outside. `SteppedFakeClient` (below)
   inserts one real `await asyncio.sleep(0)` before each yielded event, so
   a concurrently-running poller can observe true mid-stream state.

5. **No canonical "red" / "dim" / "bold-green" ANSI convention exists yet**
   in this port for *this* component (task-9's `Text.style` is a raw
   pass-through string with no fixed palette, and this module was the first
   caller to pick an actual error color) — `_has_reddish_styling` below accepts any
   SGR spelling of "reddish foreground" (8-color red/bright-red or a
   truecolor triplet where the red channel dominates) rather than locking
   GREEN into one exact byte sequence invented by this test file.

6. **Bounded polling, no fixed sleeps.** `wait_until(predicate, timeout=...)`
   polls with short `asyncio.sleep` intervals and raises `AssertionError`
   with a clear message on timeout — this doubles as the test's actual
   assertion for several "did X eventually happen" checks (a `wait_until`
   that never observes the awaited condition simply times out and fails the
   test, exactly like any other regular assertion).

7. **Interrupt delivery — two distinct tests, task-16 fix round 1 (Critical
   finding 1).** A REAL terminal's Ctrl+C never reaches this app as a
   process signal at all: raw mode (`engine/terminal.py`) clears `ISIG` for
   the whole session, so Ctrl+C arrives only as the ordinary stdin byte
   `"\x03"`, indistinguishable at the OS level from any other keystroke.
   `test_ctrl_c_stdin_byte_mid_turn_cancels_and_shows_interrupted` drives
   *that* real path — sending `\x03` through `stdin_pipe`, exactly like
   every other scripted frame in this file — and is the primary test for
   "Ctrl+C interrupts a turn". A second, clearly-named test,
   `test_external_signal_sigint_mid_turn_cancels_and_shows_interrupted`,
   sends a real `os.kill(getpid(), SIGINT)` instead: this covers a genuine
   *external* signal (e.g. another process sending SIGINT), which
   `run_app` still supports via its own `loop.add_signal_handler(signal.
   SIGINT, ...)` registration in `_run_turn` (mirroring the legacy
   `app.py`'s exact same per-turn-registration pattern) — a real but
   secondary path, sent only after polling confirms a turn is genuinely in
   flight so that registration is guaranteed to already be active.

RED-phase failure mode: ``ModuleNotFoundError: No module named
'pipython.tui.app2'`` at collection — see task-16-report.md's RED section
for the captured output. No implementation is written by this task.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import sys
from typing import Callable

import pytest

from pipython import AssistantMessage, TextContent, ToolCallContent
from pipython.testing import FakeClient
from pipython.tui.app import extract_text, load_fake_client, make_client
from pipython.tui.components.loader import DEFAULT_FRAMES

# See module docstring note 2 / engine.conftest note in
# tests/tui/components/test_editor_autocomplete.py: this file sits directly
# in tests/tui/ (a sibling of tests/tui/engine/, which has no
# tests/tui/__init__.py ancestor), so pytest's rootdir insertion makes
# tests/tui/ itself the sys.path entry — `engine.conftest` (not the fully
# dotted `tests.tui.engine.conftest`) is what's reliably importable here.
from engine.conftest import RecordingTerm

from pipython.tui.app import run_app  # noqa: E402


# =============================================================================
# stdin injection (see module docstring note 1)
# =============================================================================


class _FakeStdin:
    """Minimal stub matching `engine/terminal.py`'s own established
    `sys.stdin` mocking convention: only `fileno()` needs to exist and
    return a real int."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd


@pytest.fixture
def stdin_pipe(monkeypatch):
    """Real os.pipe() stood in for stdin; yields the write-end fd. See
    module docstring note 1 for why this is the injection seam."""
    r_fd, w_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", _FakeStdin(r_fd))
    try:
        yield w_fd
    finally:
        with contextlib.suppress(OSError):
            os.close(w_fd)
        with contextlib.suppress(OSError):
            os.close(r_fd)


def send(w_fd: int, data: bytes | str) -> None:
    os.write(w_fd, data.encode() if isinstance(data, str) else data)


# =============================================================================
# FakeRealTerm — RecordingTerm + the RealTerminal-only extras the app must use
# =============================================================================


class FakeRealTerm(RecordingTerm):
    """`RecordingTerm` (Task 7's own write/screen()-replay double) plus the
    three `RealTerminal`-only members (`kitty_enabled`, `on_resize`,
    `drain_pending`) the app needs for obligations (a)/(b)/(c). See module
    docstring note 2."""

    def __init__(self, *, kitty_enabled: bool = False, pending: bytes = b"") -> None:
        super().__init__()
        self.kitty_enabled = kitty_enabled
        self._pending = pending
        self.resize_cb: Callable[[], None] | None = None

    def on_resize(self, cb: Callable[[], None]) -> None:
        self.resize_cb = cb

    def drain_pending(self) -> bytes:
        pending, self._pending = self._pending, b""
        return pending


def full_ops_text(term: RecordingTerm) -> str:
    """Every write() ever issued, concatenated in order — unlike
    `screen()` (a fixed 24-row *current* window that can overwrite/clip
    older rows once content exceeds the row count), this never loses
    history, so it's the right thing to grep for "did X ever appear"."""
    return "".join(term.ops)


def screen_text(term: RecordingTerm) -> str:
    return "\n".join(term.screen())


def _editor_row_index(term: RecordingTerm) -> int:
    """Index of the editor's own content row in the current screen. The
    editor is always focused (module docstring: "editor ... always
    focused, always at the bottom"), so its rendered row is the one and
    only row carrying the reverse-video cursor marker (``\\x1b[7m``,
    editor.py's own cursor-rendering escape, not used anywhere else in this
    port -- confirmed unique). Locating it this way (rather than "the last
    non-blank row") matters because the editor renders inside a bordered
    box: the row *below* its content is a horizontal-rule border, itself
    non-blank. Used to tell "the editor's own draft" apart from "a
    persisted transcript line" when both could otherwise contain the same
    substring (see the mid-turn-submit test below)."""
    rows = term.screen()
    idxs = [i for i, r in enumerate(rows) if "\x1b[7m" in r]
    assert idxs, "expected exactly one row carrying the cursor marker"
    return idxs[-1]


_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _visible_text(row: str) -> str:
    """Strip ANSI CSI sequences (SGR styling, cursor-position escapes) from
    a rendered row so plain substring checks aren't defeated by e.g. the
    reverse-video cursor marker landing *inside* a word (editor.py embeds
    it at the cursor's exact grapheme position, which can split a literal
    substring like "first" into "\\x1b[7mf\\x1b[0mirst" when the cursor sits
    at column 0)."""
    return _CSI_RE.sub("", row)


# =============================================================================
# SteppedFakeClient (see module docstring note 4)
# =============================================================================


class SteppedFakeClient(FakeClient):
    """FakeClient variant that inserts a real (wall-clock, `call_later`-
    backed) pause before each streamed event.

    Plain `FakeClient.stream()` has no genuine suspension point at all, and
    a bare `await asyncio.sleep(0)` merely reschedules via `call_soon` — a
    same-tick hop that a real event loop can drain, alongside several other
    already-queued `call_soon` callbacks (like `TUI.request_render()`'s own
    coalesced render), *far* faster than even the shortest realistic
    `asyncio.sleep()` polling granularity can observe (verified empirically:
    a `sleep(0)`-only version of this class made a two-chunk streaming test
    observe both chunks already merged on the very first poll, every time).
    A real timed sleep forces genuine wall-clock separation between
    successive events, so a concurrently-running bounded poll (`wait_until`,
    interval 0.01s) reliably samples the true intermediate state in between.
    """

    _STEP_DELAY_S = 0.05

    async def stream(self, *, model, system, messages, tool_schemas):
        async for ev in super().stream(
            model=model, system=system, messages=messages, tool_schemas=tool_schemas
        ):
            await asyncio.sleep(self._STEP_DELAY_S)
            yield ev


def done(text: str = "done") -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)])


# =============================================================================
# Generic async test helpers
# =============================================================================


async def wait_until(
    predicate: Callable[[], bool], *, timeout: float = 2.0, interval: float = 0.01
):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last_exc: Exception | None = None
    while loop.time() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # predicate may probe state that's not ready yet
            last_exc = exc
        await asyncio.sleep(interval)
    if predicate():
        return
    extra = f" (last predicate error: {last_exc!r})" if last_exc else ""
    raise AssertionError(f"condition not met within {timeout}s{extra}")


@contextlib.asynccontextmanager
async def running_app(**kwargs):
    """Runs run_app as a background task; always cancels + drains it on
    exit regardless of whether the test already drove a clean exit
    (cancelling an already-finished task is a no-op)."""
    task = asyncio.create_task(run_app(**kwargs))
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _has_reddish_styling(text: str) -> bool:
    """See module docstring note 5 — tolerant of any SGR spelling of "red
    foreground", not one hardcoded escape sequence."""
    for m in _SGR_RE.finditer(text):
        codes = m.group(1).split(";")
        if "31" in codes or "91" in codes:
            return True
        if "38" in codes and "2" in codes:
            try:
                idx = codes.index("2")
                r, g, b = (int(codes[idx + 1]), int(codes[idx + 2]), int(codes[idx + 3]))
            except (ValueError, IndexError):
                continue
            if r > 120 and r > g + 40 and r > b + 40:
                return True
    return False


def _has_ansi_styling(text: str) -> bool:
    return bool(_SGR_RE.search(text))


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _isolate_session_dir(monkeypatch, tmp_path):
    """Matches tests/tui/test_commands.py's own precedent for keeping
    session files out of the real ~/.pi-python/sessions during tests."""
    monkeypatch.setattr("pipython.session_facade.DEFAULT_SESSION_DIR", tmp_path / "sessions")


# =============================================================================
# 1. Basic echo + submit
# =============================================================================


async def test_user_input_echoed_after_submit(tmp_path, stdin_pipe):
    client = FakeClient(script=[done("ok")])
    term = FakeRealTerm()
    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "hello there")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "hello there" in full_ops_text(term))
        await wait_until(lambda: "ok" in full_ops_text(term))


# =============================================================================
# 2. Two-turn script: streaming grows -> markdown replaces -> tool line
# =============================================================================


async def test_two_turn_script_streams_grows_then_markdown_then_tool_line(tmp_path, stdin_pipe):
    script = [
        AssistantMessage(content=[TextContent(text="Hello "), TextContent(text="**world**")]),
        AssistantMessage(
            content=[ToolCallContent(id="1", name="ls", arguments={})],
        ),
        done("all set"),
    ]
    client = SteppedFakeClient(script=script)
    (tmp_path / "marker_file.txt").write_text("x")
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        # -- turn 1: streaming growth then markdown replace --
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "Hello" in full_ops_text(term))
        # Mid-stream: the second chunk ("**world**") must not be visible yet
        # -- proves growth is genuinely incremental, not a single final write.
        assert "world" not in full_ops_text(term)

        await wait_until(lambda: "world" in full_ops_text(term))
        # Still mid-stream at this exact point (message_end/ClientMessageEnd
        # hasn't been let through yet): the *raw* markdown source is what's
        # visible, not yet the rendered form.
        assert "**world**" in full_ops_text(term)

        # message_end must replace the raw markdown source with rendered
        # ANSI (bold, SGR 1) -- checked against the *current* screen (not
        # the cumulative `ops` log, which never loses the earlier raw write
        # even after it's erased on-screen; see full_ops_text()/screen_text()
        # docstrings above).
        await wait_until(lambda: "\x1b[1m" in screen_text(term))
        assert "**world**" not in screen_text(term)

        # -- turn 2: a real tool call (ls) renders a tool line --
        send(stdin_pipe, "list files")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "all set" in full_ops_text(term))
        assert "ls" in full_ops_text(term)


# =============================================================================
# 3. Loader visible during a turn, gone afterwards
# =============================================================================


async def test_loader_visible_during_turn_and_gone_after(tmp_path, stdin_pipe):
    loader_chars = set(DEFAULT_FRAMES)
    client = SteppedFakeClient(
        script=[AssistantMessage(content=[TextContent(text="hi"), TextContent(text=" there")])]
    )
    term = FakeRealTerm()

    def has_loader() -> bool:
        return any(ch in screen_text(term) for ch in loader_chars)

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        assert not has_loader()
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(has_loader)
        await wait_until(lambda: "there" in full_ops_text(term))
        await wait_until(lambda: not has_loader())


# =============================================================================
# 4. Tool-result error renders a reddish line ("deny/error" red line)
# =============================================================================


async def test_tool_result_error_renders_reddish_line(tmp_path, stdin_pipe):
    script = [
        AssistantMessage(
            content=[ToolCallContent(id="1", name="totally_bogus_tool_xyz", arguments={})]
        ),
        done("recovered"),
    ]
    client = FakeClient(script=script)
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "do the thing")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "totally_bogus_tool_xyz" in full_ops_text(term))
        await wait_until(lambda: "recovered" in full_ops_text(term))

        ops = list(term.ops)
        error_ops = [op for op in ops if "totally_bogus_tool_xyz" in op or "Unknown tool" in op]
        assert error_ops, "expected an op containing the tool-error text"
        assert any(_has_reddish_styling(op) for op in error_ops)


# =============================================================================
# 5. Ctrl+C / SIGINT mid-turn -> cancel -> "[interrupted]"
#
# Critical finding 1 (task-16 fix round 1): a REAL terminal's Ctrl+C never
# arrives as a process signal (raw mode clears ISIG for the whole session,
# engine/terminal.py) -- only as the ordinary stdin byte "\x03". The primary
# test below drives *that* real path. A second, clearly-named test covers
# the secondary path: a genuine external SIGINT (e.g. `kill -INT <pid>` from
# another process), which run_app still supports via
# `loop.add_signal_handler(signal.SIGINT, ...)` in `_run_turn`.
# =============================================================================


async def test_ctrl_c_stdin_byte_mid_turn_cancels_and_shows_interrupted(tmp_path, stdin_pipe):
    """The real production path: Ctrl+C reaches `_on_stdin_frame` as the
    stdin byte `"\\x03"`, exactly like any other scripted frame in this
    file -- never as a signal. Must cancel the in-flight turn task the same
    way `test_external_signal_sigint_mid_turn_cancels_and_shows_interrupted`
    (below) verifies for a genuine external signal."""
    client = SteppedFakeClient(
        script=[
            AssistantMessage(content=[TextContent(text="partial "), TextContent(text="more text")])
        ]
    )
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term) as task:
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "partial" in full_ops_text(term))

        send(stdin_pipe, b"\x03")  # real-terminal Ctrl+C: a stdin byte, not a signal

        await wait_until(lambda: "[interrupted]" in full_ops_text(term))
        assert not task.done()  # app keeps running after an interrupted turn


async def test_external_signal_sigint_mid_turn_cancels_and_shows_interrupted(tmp_path, stdin_pipe):
    """Secondary path (task-16 fix round 1 rename -- this test used to be
    named `test_sigint_mid_turn_cancels_and_shows_interrupted` and was the
    *only* interrupt test, incorrectly standing in for real-terminal Ctrl+C,
    which does not actually deliver SIGINT at all; see the stdin-byte test
    above for that real path). A genuine external signal -- e.g. another
    process sending SIGINT -- is still wired through
    `loop.add_signal_handler(signal.SIGINT, ...)` in `_run_turn` and must
    still cancel an in-flight turn."""
    client = SteppedFakeClient(
        script=[
            AssistantMessage(content=[TextContent(text="partial "), TextContent(text="more text")])
        ]
    )
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term) as task:
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "partial" in full_ops_text(term))

        os.kill(os.getpid(), signal.SIGINT)

        await wait_until(lambda: "[interrupted]" in full_ops_text(term))
        assert not task.done()  # app keeps running after an interrupted turn


# =============================================================================
# 6. Ctrl+C clears the editor buffer (Editor itself no-ops on ctrl+c --
#    editor.py handle_key: "Ctrl+C: parent's job (exit/clear)" -- the app must
#    do the clearing itself)
# =============================================================================


async def test_ctrl_c_clears_editor_buffer_without_submitting(tmp_path, stdin_pipe):
    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "some unsent draft")
        await wait_until(lambda: "some unsent draft" in screen_text(term))

        send(stdin_pipe, b"\x03")  # Ctrl+C
        await wait_until(lambda: "some unsent draft" not in screen_text(term))

        assert not client.calls  # never submitted to the model


# =============================================================================
# 7. Ctrl+D on an empty buffer exits with a session-path banner; on a
#    non-empty buffer it must NOT quit (editor's own binding: ctrl+d ->
#    deleteCharForward) -- the app only special-cases the *empty* case.
# =============================================================================


async def test_ctrl_d_empty_buffer_exits_with_session_banner(tmp_path, stdin_pipe):
    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term) as task:
        send(stdin_pipe, b"\x04")  # Ctrl+D, buffer already empty
        await wait_until(lambda: task.done(), timeout=3.0)

        session_dir = tmp_path / "sessions"
        jsonl_files = list(session_dir.rglob("*.jsonl"))
        assert jsonl_files, "expected run_app to have created a session file"
        banner_needle = jsonl_files[0].stem
        assert "session" in full_ops_text(term).lower()
        assert banner_needle in full_ops_text(term)


async def test_ctrl_d_nonempty_buffer_does_not_quit(tmp_path, stdin_pipe):
    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term) as task:
        send(stdin_pipe, "draft")
        await wait_until(lambda: "draft" in screen_text(term))

        send(stdin_pipe, b"\x04")  # Ctrl+D with a non-empty buffer
        await asyncio.sleep(0.2)  # give a (buggy) quit path a chance to fire
        assert not task.done()


# =============================================================================
# 8/9. Slash commands render via the new Sink-based component path
# =============================================================================


async def test_slash_help_renders_command_names(tmp_path, stdin_pipe):
    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "/help")
        send(stdin_pipe, "\r")
        text = None

        def has_all_commands() -> bool:
            nonlocal text
            text = full_ops_text(term)
            return all(
                name in text for name in ["help", "model", "clear", "tree", "branch", "quit"]
            )

        await wait_until(has_all_commands)


async def test_slash_tree_renders_ansi_tree(tmp_path, stdin_pipe):
    client = FakeClient(script=[done("first reply")])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "first question")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "first reply" in full_ops_text(term))

        send(stdin_pipe, "/tree")
        send(stdin_pipe, "\r")
        await wait_until(
            lambda: (
                ("├──" in full_ops_text(term) or "└──" in full_ops_text(term))
                and "←" in full_ops_text(term)
            )
        )


async def test_unknown_slash_command_shows_help_hint(tmp_path, stdin_pipe):
    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "/bogus")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "/help" in full_ops_text(term))


# =============================================================================
# Important finding 2 (task-16 fix round 1): slash commands serialize with
# turns -- a command submitted while a turn is in flight must be ignored (not
# queued, not raced), matching phase 2's own ignore-while-busy single-flight
# semantics for plain-text turns. `/clear` is the sharpest probe: it swaps
# `app_state.session` outright, which -- if allowed mid-turn -- would pull
# the rug out from under the still-iterating `session.prompt()` generator
# `_run_turn` is consuming.
# =============================================================================


async def test_slash_clear_mid_turn_does_not_swap_session_under_running_turn(tmp_path, stdin_pipe):
    client = SteppedFakeClient(
        script=[
            AssistantMessage(content=[TextContent(text="partial "), TextContent(text="more text")])
        ]
    )
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "partial" in full_ops_text(term))

        send(stdin_pipe, "/clear")
        send(stdin_pipe, "\r")
        await asyncio.sleep(0.2)  # give a (buggy) immediate-dispatch path a chance to fire
        assert "new session" not in full_ops_text(term), (
            "/clear must be ignored while a turn is running, not dispatched immediately"
        )

        # The running turn must be completely undisturbed by the ignored command.
        await wait_until(lambda: "more text" in full_ops_text(term))

        session_dir = tmp_path / "sessions"
        jsonl_files = list(session_dir.rglob("*.jsonl"))
        assert len(jsonl_files) == 1, "no session swap should have happened"


# =============================================================================
# Task 16 fix round 2 (re-review): a mid-turn submit must not masquerade as
# accepted. Pre-fix, `_on_submit` echoed the text into the transcript and
# pushed it into editor history BEFORE the single-flight busy check -- even
# though `Editor._submit_value` (editor.py) had already cleared the buffer on
# Enter. The text therefore looked "accepted" (echoed, in history) but never
# reached the model, and the draft itself was gone. Fixed: the echo +
# add_to_history now happen only when not busy; when busy, the exact
# submitted text is restored into the editor via `editor.set_text(text)`
# (cursor lands at the end, `set_text`'s own default) instead of being
# dropped. Full upstream queueing (`restoreQueuedMessagesToEditor`) is a
# phase-4 parity item, not built here -- this is a minimal correctness fix.
# =============================================================================


async def test_submit_mid_turn_restores_draft_and_leaves_history_untouched(tmp_path, stdin_pipe):
    client = SteppedFakeClient(
        script=[
            AssistantMessage(content=[TextContent(text="partial "), TextContent(text="more text")]),
            done("second reply"),
        ]
    )
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "first turn")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "partial" in full_ops_text(term))

        # Attempt a second submit while the first turn is still in flight.
        send(stdin_pipe, "lost message")
        send(stdin_pipe, "\r")

        # The exact text must be restored verbatim into the editor buffer.
        await wait_until(
            lambda: "lost message" in _visible_text(term.screen()[_editor_row_index(term)])
        )
        # It must NOT have been echoed as a separate transcript line -- only
        # the editor's own row shows it, nothing above it does.
        editor_idx = _editor_row_index(term)
        assert "lost message" not in _visible_text("\n".join(term.screen()[:editor_idx]))

        # It must NOT have entered history either: Home (cursor -> column 0)
        # then Up (history recall) on the now-restored single-line draft must
        # surface the *real* previous submission ("first turn"), never the
        # dropped mid-turn text.
        send(stdin_pipe, "\x1b[H")
        send(stdin_pipe, "\x1b[A")
        await wait_until(
            lambda: "first turn" in _visible_text(term.screen()[_editor_row_index(term)])
        )
        assert "lost message" not in _visible_text(term.screen()[_editor_row_index(term)])

        # Down arrow restores the exact draft captured when Up was pressed,
        # proving the history probe itself didn't mutate/lose it either.
        send(stdin_pipe, "\x1b[B")
        await wait_until(
            lambda: "lost message" in _visible_text(term.screen()[_editor_row_index(term)])
        )

        # The running turn itself is completely undisturbed by any of this.
        await wait_until(lambda: "more text" in full_ops_text(term))
        # Wait for the turn to actually finish (loader gone), not just for
        # its last text delta to have arrived -- otherwise the busy gate
        # could still be up when we resubmit next, turning this into
        # another (silently swallowed) restore instead of a real resubmit.
        await wait_until(lambda: not any(ch in screen_text(term) for ch in DEFAULT_FRAMES))

        # Once idle, submitting again (the very draft that was restored)
        # works normally: echoed into the transcript, sent to the model.
        send(stdin_pipe, "\r")
        await wait_until(lambda: len(client.calls) >= 2)
        assert client.calls[-1][-1].content == "lost message"
        await wait_until(lambda: "second reply" in full_ops_text(term))
        final_editor_idx = _editor_row_index(term)
        assert "lost message" in _visible_text("\n".join(term.screen()[:final_editor_idx]))


# =============================================================================
# Obligation (a): drain_pending() fed before / ordered ahead of live input
# =============================================================================


async def test_pending_bytes_are_processed_before_and_ordered_ahead_of_live_input(
    tmp_path, stdin_pipe
):
    client = FakeClient(script=[])
    term = FakeRealTerm(pending=b"AB")

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        # Written as early as possible, before any await in this test body
        # yields control -- a real race against a wrongly-ordered
        # implementation that attaches the live reader before draining
        # pending bytes.
        send(stdin_pipe, "CD")
        await wait_until(lambda: "ABCD" in screen_text(term), timeout=3.0)


# =============================================================================
# Obligation (b): no loop.add_signal_handler(SIGWINCH, ...); on_resize wired
# =============================================================================


async def test_sigwinch_not_registered_via_loop_and_on_resize_is_wired_to_a_render(
    tmp_path, stdin_pipe, monkeypatch
):
    registered_signals: list[int] = []
    # `asyncio.AbstractEventLoop.add_signal_handler` is *not* the method
    # actually invoked at runtime: the concrete loop class in use (e.g.
    # `asyncio.unix_events._UnixSelectorEventLoop` on POSIX) defines its own
    # `add_signal_handler` that shadows the abstract base entirely (verified
    # directly: `_UnixSelectorEventLoop.__dict__` has its own entry) --
    # patching the abstract base is silently a no-op. Patch the *actual*
    # running loop's concrete class instead.
    loop_cls = type(asyncio.get_running_loop())
    orig_add_signal_handler = loop_cls.add_signal_handler

    def spy_add_signal_handler(self, signum, callback, *a, **kw):
        registered_signals.append(signum)
        return orig_add_signal_handler(self, signum, callback, *a, **kw)

    monkeypatch.setattr(loop_cls, "add_signal_handler", spy_add_signal_handler)

    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        await wait_until(lambda: len(term.ops) > 0)  # initial render happened
        assert signal.SIGWINCH not in registered_signals

        assert term.resize_cb is not None, "term.on_resize was never called"
        before = len(term.ops)
        term.resize_cb()
        await wait_until(lambda: len(term.ops) > before)


# =============================================================================
# Obligation (c): RealTerminal.kitty_enabled threads into the editor's input
# path (editor.py deviation-7 checkpoint) -- an ambiguous legacy 2-byte
# ESC+letter frame ("\x1bB", the pre-kitty Alt+Left encoding) must be
# dropped when the terminal actually negotiated Kitty, and must still work
# as the legacy fallback when it didn't.
# =============================================================================


async def test_kitty_enabled_true_drops_ambiguous_legacy_altleft_frame(tmp_path, stdin_pipe):
    client = FakeClient(script=[done()])
    term = FakeRealTerm(kitty_enabled=True)

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "foo bar")
        await wait_until(lambda: "foo bar" in screen_text(term))

        send(stdin_pipe, b"\x1bB")  # ambiguous legacy alt+left encoding
        await asyncio.sleep(0.05)  # let stdin_buffer's framing settle
        send(stdin_pipe, "X")
        send(stdin_pipe, "\r")

        await wait_until(lambda: bool(client.calls))
        submitted = client.calls[-1][-1].content
        assert submitted == "foo barX"


async def test_kitty_enabled_false_falls_back_to_legacy_altleft(tmp_path, stdin_pipe):
    client = FakeClient(script=[done()])
    term = FakeRealTerm(kitty_enabled=False)

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "foo bar")
        await wait_until(lambda: "foo bar" in screen_text(term))

        send(stdin_pipe, b"\x1bB")  # legacy alt+left, should fire when not kitty
        await asyncio.sleep(0.05)
        send(stdin_pipe, "X")
        send(stdin_pipe, "\r")

        await wait_until(lambda: bool(client.calls))
        submitted = client.calls[-1][-1].content
        assert submitted == "foo Xbar"


# =============================================================================
# Obligation (d): submit uses get_expanded_text() -- a folded large paste
# marker must expand back to its full original content before reaching
# session.prompt()/the model, never the "[paste #N ... ]" marker literal.
# =============================================================================


async def test_submit_sends_full_expanded_paste_text_not_the_folded_marker(tmp_path, stdin_pipe):
    client = FakeClient(script=[done()])
    term = FakeRealTerm()
    big_paste = "y" * 1500  # > 1000 chars -> editor.py folds this into a marker

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "\x1b[200~" + big_paste + "\x1b[201~")
        await wait_until(lambda: "1500 chars" in screen_text(term))
        # The raw pasted content must not itself be sitting on screen (it's
        # folded into the short marker) -- a loose sanity check that this
        # really did fold rather than insert verbatim.
        assert big_paste not in screen_text(term)

        send(stdin_pipe, "\r")
        await wait_until(lambda: bool(client.calls))
        submitted = client.calls[-1][-1].content
        assert submitted == big_paste


# =============================================================================
# Task 18 gap closures — see .superpowers/sdd/task-18-report.md's coverage
# table. These port forward regression coverage from the retired
# test_app_helpers.py/test_render.py (pure-function tests: load_fake_client,
# make_client, extract_text) plus close gaps the coverage table found with
# no prior equivalent against this engine: tool-call-line truncation, a
# successful tool result's content never being echoed, ErrorEvent/non-"done"
# AgentEnd rendering, and a slash-command handler exception not crashing the
# app loop.
# =============================================================================


def test_load_fake_client_roundtrip(tmp_path):
    # Ported from the retired test_app_helpers.py — load_fake_client moved
    # into pipython.tui.app verbatim (see that module's docstring).
    script = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    f = tmp_path / "s.json"
    f.write_text(json.dumps(script))
    client = load_fake_client(str(f))
    assert isinstance(client, FakeClient) and len(client._script) == 1


def test_make_client_env_switch(tmp_path, monkeypatch):
    # Ported from the retired test_app_helpers.py — make_client moved into
    # pipython.tui.app verbatim; this is the CLI's PI_PYTHON_FAKE_SCRIPT
    # wiring, exercised end-to-end by every e2e tmux test's env= kwarg.
    f = tmp_path / "s.json"
    f.write_text("[]")
    monkeypatch.setenv("PI_PYTHON_FAKE_SCRIPT", str(f))
    assert isinstance(make_client("any/model"), FakeClient)
    monkeypatch.delenv("PI_PYTHON_FAKE_SCRIPT")
    assert make_client("any/model") is None


def test_extract_text_joins_blocks_skipping_tool_calls():
    # Ported from the retired test_render.py's test_extract_text_joins_blocks
    # — extract_text moved into pipython.tui.app verbatim.
    msg = AssistantMessage(
        content=[
            TextContent(text="a"),
            ToolCallContent(id="t1", name="bash", arguments={"command": "ls"}),
            TextContent(text="b"),
        ]
    )
    assert extract_text(msg) == "ab"


async def test_tool_call_line_args_truncated(tmp_path, stdin_pipe):
    # Gap closure: the retired test_render.py's test_tool_call_line_truncated
    # asserted long tool-call arguments get clipped in the "[tool] <name>
    # <args>" line (_ARG_TRUNC in app.py) — no prior test against this
    # engine pinned that truncation actually happens.
    long_cmd = "x" * 500
    script = [
        AssistantMessage(
            content=[ToolCallContent(id="1", name="bash", arguments={"command": long_cmd})]
        ),
        done("finished"),
    ]
    client = FakeClient(script=script)
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "[tool] bash" in full_ops_text(term))
        assert long_cmd not in full_ops_text(term), (
            "tool-call arguments must be truncated, never echoed in full"
        )
        await wait_until(lambda: "finished" in full_ops_text(term))


async def test_tool_result_success_content_not_echoed(tmp_path, stdin_pipe):
    # Gap closure: the retired test_render.py's
    # test_tool_result_only_errors_printed asserted a *successful* tool
    # result's content is never printed (only errors are, via
    # test_tool_result_error_renders_reddish_line above) — no prior test
    # against this engine pinned the "success is silent" half of that rule.
    (tmp_path / "success_marker_9f3a.txt").write_text("x")
    script = [
        AssistantMessage(content=[ToolCallContent(id="1", name="ls", arguments={})]),
        done("all good"),
    ]
    client = FakeClient(script=script)
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "all good" in full_ops_text(term))
        assert "success_marker_9f3a.txt" not in full_ops_text(term), (
            "a successful tool result's content must never be echoed"
        )


async def test_error_event_and_agent_end_error_reason_rendered(tmp_path, stdin_pipe):
    # Gap closure: the retired test_render.py's test_error_event_rendered_in_red
    # / test_agent_end_non_done_notice covered ErrorEvent (reddish text) and
    # AgentEnd(reason != "done") ("[end] <reason>") — no prior test against
    # this engine exercised either. Driven through the *real* failure path
    # rather than a hand-built event: a script with exactly one entry (a
    # tool call) makes the agent loop for a second model turn once the tool
    # result comes back, but the FakeClient's script is now exhausted, so
    # `client.stream()` raises AssertionError — agent.py's own `except
    # Exception` branch (spec §4.3) converts that into ErrorEvent +
    # AgentEnd(reason="error") rather than letting it escape naked. The
    # "[end] <reason>" format string is reason-agnostic, so this also stands
    # in for the "max_turns" case the retired test used (not practically
    # triggerable here: run_app's AgentSessionConfig always uses the default
    # max_turns=50, with no override in run_app's own signature).
    script = [AssistantMessage(content=[ToolCallContent(id="1", name="ls", arguments={})])]
    client = FakeClient(script=script)
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "go")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "script exhausted" in full_ops_text(term))
        assert _has_reddish_styling(full_ops_text(term))
        await wait_until(lambda: "[end] error" in full_ops_text(term))


async def test_command_handler_exception_does_not_crash_app_loop(tmp_path, stdin_pipe, monkeypatch):
    # Gap closure: the retired test_commands.py's
    # test_command_handler_exception_does_not_crash_run_app pinned that a
    # handler bug (e.g. /branch hitting a header id, per commands.py's own
    # comment) can't take down the whole app loop — no prior test against
    # this engine's _run_command exercised that defensive path.
    from pipython.tui import app as app_module
    from pipython.tui.commands import Command
    from pipython.tui.commands import build_registry as real_build_registry

    async def boom(_ctx, _arg):
        raise RuntimeError("boom-handler")

    registry = real_build_registry()
    registry["boom"] = Command("boom", "raises for testing", boom)
    monkeypatch.setattr(app_module, "build_registry", lambda: registry)

    client = FakeClient(script=[])
    term = FakeRealTerm()

    async with running_app(model="fake/model", cwd=tmp_path, client=client, term=term):
        send(stdin_pipe, "/boom")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "boom-handler" in full_ops_text(term))

        # The app loop must still be genuinely alive afterwards -- not just
        # "the test process didn't crash" -- so drive one more real command
        # through the same tui/editor/dispatch machinery.
        send(stdin_pipe, "/help")
        send(stdin_pipe, "\r")
        await wait_until(lambda: "quit" in full_ops_text(term))
