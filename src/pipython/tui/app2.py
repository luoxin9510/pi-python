"""New-engine main loop — Python port of upstream pi's app assembly, wired
over the phase-3 engine (Task 7/8 ``TUI`` + Task 9-15 components) instead of
``prompt_toolkit``/``rich.Live`` (the legacy ``app.py``). Per
``.superpowers/sdd/task-16-brief.md`` and spec §6.

Runs *alongside* the legacy TUI (spec §8: "新引擎旁路开发，旧 TUI 最后一个任务
才删") — nothing here touches ``app.py``.

Component tree (spec §6)::

    Container (root)
    ├── transcript (Container) — appended per turn: user echo (Text) /
    │   streaming reply (Text, incrementally invalidated) → replaced in
    │   place at message_end with rendered Markdown / tool-call line (Text)
    │   / tool-error or agent-error (reddish Text)
    ├── loader slot — visible only while a turn is in flight
    └── editor (Editor) — always focused, always at the bottom

Four binding wiring obligations (task-16-brief.md; RED-asserted in
``tests/tui/test_app2.py``):

(a) ``term.drain_pending()`` bytes are fed into the ``StdinBuffer`` *before*
    ``loop.add_reader(fd, ...)`` is attached (see ``_run``).
(b) No ``loop.add_signal_handler(signal.SIGWINCH, ...)`` anywhere — resize
    goes through ``term.on_resize(tui.on_resize)`` only (see ``_run``).
(c) ``term.kitty_enabled`` threads into ``Editor.handle_input``'s
    ``parse_key(data, kitty=False)`` call sites (editor.py module docstring
    deviation 7). Resolved *without* modifying ``components/editor.py``
    (out of this task's file list — see ``_thread_kitty_flag`` below for the
    disclosed approach: a scoped monkeypatch of the module-level ``parse_key``
    name ``editor.py`` itself calls, restored on exit).
(d) Submit uses ``Editor.get_expanded_text()`` — this is already true for
    free: ``Editor._submit_value`` (editor.py) calls
    ``self.get_expanded_text().strip()`` *before* invoking ``on_submit``, so
    any ``on_submit`` callback here already only ever sees expanded text,
    never a folded paste marker.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import signal
import sys
from pathlib import Path
from typing import Iterator

from rich.console import Console

from pipython import (
    AgentEnd,
    AgentSession,
    AgentSessionConfig,
    ErrorEvent,
    MessageEnd,
    MessageStart,
    ModelClient,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
    create_agent_session,
)
from pipython.tui.completers import build_file_list
from pipython.tui.components import editor as _editor_module
from pipython.tui.components.autocomplete import CombinedProvider, CommandProvider, PathProvider
from pipython.tui.components.editor import Editor
from pipython.tui.components.loader import Loader
from pipython.tui.components.markdown import Markdown
from pipython.tui.components.text import Text
from pipython.tui.engine.stdin_buffer import StdinBuffer
from pipython.tui.engine.term_caps import TermCaps, detect_caps
from pipython.tui.engine.terminal import RealTerminal, TerminalIO
from pipython.tui.engine.tui import TUI, Container

from .commands import AppState, CommandContext, Sink, build_registry, dispatch
from .render import extract_text

__all__ = ["run_app2"]

_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_DIM = "\x1b[2m"

_ARG_TRUNC = 100
_ERR_TRUNC = 200


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# =============================================================================
# Obligation (c): thread term.kitty_enabled into editor.py's parse_key calls
# without modifying components/editor.py.
# =============================================================================


@contextlib.contextmanager
def _thread_kitty_flag(term: TerminalIO) -> Iterator[None]:
    """editor.py's ``handle_input`` (both the main branch and the
    character-jump branch) call the bare module-level name ``parse_key``
    (``from ..engine.keys import ... parse_key``) hardcoded to
    ``kitty=False`` (module docstring deviation 7 there, which explicitly
    flags Task 16 as "the natural checkpoint" to fix this). Since that name
    is resolved from ``editor.py``'s own module globals at call time,
    swapping ``pipython.tui.components.editor.parse_key`` for the duration
    of one ``run_app2`` invocation intercepts both call sites and substitutes
    the real negotiated ``term.kitty_enabled`` for the hardcoded literal —
    without touching ``editor.py``'s source (out of this task's file list;
    see task-16-report.md's GREEN section for why this "parse seam" approach
    was chosen over adding a new ``editor.kitty`` attribute). Restored on
    exit so no other concurrently-imported code observes the patch.
    """
    original = _editor_module.parse_key

    def _kitty_aware_parse_key(frame: str, kitty: bool = False):
        return original(frame, kitty=bool(getattr(term, "kitty_enabled", False)))

    _editor_module.parse_key = _kitty_aware_parse_key
    try:
        yield
    finally:
        _editor_module.parse_key = original


# =============================================================================
# Loader visibility slot — Loader itself (task-9) always renders its current
# frame unconditionally; this app owns the "only during a turn" toggle
# (spec §6: "loader（回合中）") via a tiny wrapper rather than editing
# components/loader.py.
# =============================================================================


class _LoaderSlot:
    def __init__(self, loader: Loader) -> None:
        self.loader = loader
        self.active = False

    def invalidate(self) -> None:
        self.loader.invalidate()

    def render(self, width: int) -> list[str]:
        return self.loader.render(width) if self.active else []


# =============================================================================
# Sink -> transcript Container adapter (spec §6: "斜杠命令输出改为追加 text 组件")
# =============================================================================


class _ComponentSink:
    def __init__(self, transcript: Container, tui: TUI) -> None:
        self._transcript = transcript
        self._tui = tui

    def emit_text(self, s: str, style: str = "") -> None:
        self._transcript.add_child(Text(s, style=style))
        self._tui.request_render()

    def emit_lines(self, lines: list[str]) -> None:
        for line in lines:
            self._transcript.add_child(Text(line))
        self._tui.request_render()


# =============================================================================
# Session/AppState construction — mirrors legacy app.py's `_build_app` holder
# pattern (issue #2: /clear must inherit the *current* model, not the
# startup one), narrowed to this contract's single injectable `client`
# (no client_factory — `client` is reused as-is across `/clear`-created
# sessions, matching AgentSessionConfig's own single-instance shape).
# =============================================================================


async def _build_state(model: str, cwd: Path, client: ModelClient | None) -> AppState:
    holder: list[AppState] = []

    async def make_session() -> AgentSession:
        current_model = holder[0].session.model if holder else model
        return await create_agent_session(
            AgentSessionConfig(model=current_model, cwd=cwd, client=client)
        )

    app_state = AppState(session=await make_session(), make_session=make_session)
    holder.append(app_state)
    return app_state


# =============================================================================
# run_app2
# =============================================================================


async def run_app2(
    *,
    model: str,
    cwd: Path,
    client: ModelClient | None = None,
    term: TerminalIO | None = None,
) -> None:
    """Spec §6's new-engine app loop. ``term`` is injectable (tests pass a
    ``RecordingTerm``-derived double, never a real terminal); when omitted,
    a real terminal is required (TTY hard requirement, spec §6) — a
    non-interactive ``stdin``/``stdout`` prints one line and returns rather
    than hanging or crashing."""
    owns_term = term is None
    real_term: RealTerminal | None = None
    if owns_term:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("pipython: the new TUI engine requires a real terminal (tty).")
            return
        real_term = RealTerminal()
        real_term.start()
        term = real_term
    try:
        await _run(model=model, cwd=cwd, client=client, term=term)
    finally:
        if real_term is not None:
            real_term.stop()


async def _run(*, model: str, cwd: Path, client: ModelClient | None, term: TerminalIO) -> None:
    app_state = await _build_state(model, cwd, client)
    registry = build_registry()

    tui = TUI(term)
    transcript = Container()
    loader = Loader(tui.request_render)
    loader_slot = _LoaderSlot(loader)
    editor = Editor(on_submit=lambda text: _on_submit(text))

    root = Container()
    root.add_child(transcript)
    root.add_child(loader_slot)
    root.add_child(editor)
    tui.set_root(root)
    tui.set_focus(editor)

    provider = CombinedProvider(
        [
            PathProvider(lambda: build_file_list(cwd)),
            CommandProvider({name: cmd.description for name, cmd in registry.items()}),
        ]
    )
    editor.set_autocomplete_provider(provider, tui)

    sink: Sink = _ComponentSink(transcript, tui)
    caps: TermCaps = detect_caps(dict(os.environ))

    # A throwaway, never-rendered-to console: `CommandContext.console` is a
    # required field, but every handler routes through `ctx.sink` here
    # (always non-None -> `isinstance(out, RichSink)` is always False), so
    # this console is structurally unreachable — kept only to satisfy the
    # dataclass, never printed to a real stream.
    cmd_ctx = CommandContext(console=Console(file=io.StringIO()), app=app_state, sink=sink)

    quit_event = asyncio.Event()
    turn_task: asyncio.Task[None] | None = None

    def _append(text: str, style: str = "") -> None:
        transcript.add_child(Text(text, style=style))
        tui.request_render()

    def _do_quit() -> None:
        _append(f"session: {app_state.session.store.path}", style=_DIM)
        quit_event.set()

    def _on_submit(text: str) -> None:
        nonlocal turn_task
        if not text:
            return
        editor.add_to_history(text)
        _append(text)
        if text.startswith("/"):
            asyncio.create_task(_run_command(text))
        elif turn_task is None or turn_task.done():
            turn_task = asyncio.create_task(_run_turn(text))

    async def _run_command(text: str) -> None:
        try:
            await dispatch(registry, cmd_ctx, text)
        except Exception as exc:  # handler bug must not crash the app loop
            _append(f"[command error] {type(exc).__name__}: {exc}", style=_RED)
            return
        if app_state.should_quit:
            _do_quit()

    async def _run_turn(text: str) -> None:
        loop = asyncio.get_running_loop()
        loader_slot.active = True
        loader.start()
        tui.request_render()

        this_task = asyncio.current_task()
        assert this_task is not None
        loop.add_signal_handler(signal.SIGINT, this_task.cancel)

        buf = ""
        slot: Text | None = None
        try:
            async for event in app_state.session.prompt(text):
                if isinstance(event, MessageStart):
                    buf = ""
                    slot = Text("")
                    transcript.add_child(slot)
                elif isinstance(event, TextDelta):
                    buf += event.text
                    if slot is not None:
                        slot.set_content(buf)
                        slot.invalidate()
                    tui.request_render()
                elif isinstance(event, MessageEnd):
                    full = extract_text(event.message)
                    if slot is not None and full.strip():
                        idx = transcript.children.index(slot)
                        transcript.children[idx] = Markdown(full, caps)
                    slot = None
                    tui.request_render()
                elif isinstance(event, ToolCallEvent):
                    args = _clip(
                        json.dumps(event.tool_call.arguments, ensure_ascii=False), _ARG_TRUNC
                    )
                    _append(f"[tool] {event.tool_call.name} {args}")
                elif isinstance(event, ToolResultEvent):
                    if event.result.is_error:
                        _append(_clip(event.result.content, _ERR_TRUNC), style=_RED)
                elif isinstance(event, ErrorEvent):
                    _append(event.message, style=_RED)
                elif isinstance(event, AgentEnd):
                    if event.reason != "done":
                        _append(f"[end] {event.reason}")
        except asyncio.CancelledError:
            _append("[interrupted]", style=_YELLOW)
        except Exception as exc:  # rendering/session-layer surprise must not crash the app loop
            _append(f"[error] {type(exc).__name__}: {exc}", style=_RED)
        finally:
            with contextlib.suppress(ValueError):
                loop.remove_signal_handler(signal.SIGINT)
            loader.stop()
            loader_slot.active = False
            tui.request_render()

    def _on_stdin_frame(frame: str) -> None:
        if frame == "\x03":  # Ctrl+C: editor.py's own handle_key no-ops for
            # this ("parent's job (exit/clear)") — app2 clears the buffer.
            editor.set_text("")
            tui.request_render()
            return
        if frame == "\x04" and editor.text == "":  # Ctrl+D, empty buffer: exit
            _do_quit()
            return
        # Editor (task-11/12/13 scope) holds no `tui`/render-request
        # reference of its own outside the autocomplete overlay path — a
        # plain keystroke mutates its buffer but never itself triggers a
        # repaint, so the app layer must request one after every frame.
        tui.handle_input(frame)
        tui.request_render()

    stdin_buffer = StdinBuffer(on_frame=_on_stdin_frame)

    with _thread_kitty_flag(term):
        # Obligation (b): resize goes through term.on_resize only — never
        # loop.add_signal_handler(signal.SIGWINCH, ...).
        on_resize = getattr(term, "on_resize", None)
        if callable(on_resize):
            on_resize(tui.on_resize)

        # Obligation (a): drain_pending() bytes MUST be fed before the live
        # reader attaches (engine/terminal.py's own binding requirement).
        drain_pending = getattr(term, "drain_pending", None)
        if callable(drain_pending):
            pending = drain_pending()
            if isinstance(pending, bytes) and pending:
                stdin_buffer.feed(pending)

        loop = asyncio.get_running_loop()
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            fd = None

        def _readable() -> None:
            assert fd is not None
            try:
                data = os.read(fd, 4096)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                data = b""
            if data:
                stdin_buffer.feed(data)

        if fd is not None:
            loop.add_reader(fd, _readable)

        tui.start()
        try:
            await quit_event.wait()
        finally:
            if fd is not None:
                with contextlib.suppress(ValueError, OSError):
                    loop.remove_reader(fd)
            with contextlib.suppress(ValueError):
                loop.remove_signal_handler(signal.SIGINT)
            if turn_task is not None and not turn_task.done():
                turn_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await turn_task
