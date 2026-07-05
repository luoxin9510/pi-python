"""pipython TUI main loop — Python port of upstream pi's app assembly, wired
over the phase-3 engine (Task 7/8 ``TUI`` + Task 9-15 components). Per
``.superpowers/sdd/task-16-brief.md`` and spec §6.

Task 18 (pi-tui engine becomes the only TUI): this module was ``app2.py``
through Tasks 16-17, developed *alongside* the legacy ``prompt_toolkit``/
``rich.Live`` TUI (spec §8: "新引擎旁路开发，旧 TUI 最后一个任务才删") without
touching that file. Task 18 deleted the legacy ``app.py``/``keys.py``/
``render.py`` outright and renamed this module into the vacated ``app.py``
slot — ``run_app2`` is now plain ``run_app``, and ``--engine`` is gone from
the CLI (``pipython/tui/__init__.py``): this is simply *the* TUI now, not "the
new one". ``load_fake_client``/``make_client`` (the ``PI_PYTHON_FAKE_SCRIPT``
test-only escape hatch, spec §7) and ``extract_text`` (message → plain text)
moved here verbatim from the retired ``app.py``/``render.py`` respectively —
they had no other home once those files were deleted.

Component tree (spec §6)::

    Container (root)
    ├── transcript (Container) — appended per turn: user echo (Text) /
    │   streaming reply (Text, incrementally invalidated) → replaced in
    │   place at message_end with rendered Markdown / tool-call line (Text)
    │   / tool-error or agent-error (reddish Text)
    ├── loader slot — visible only while a turn is in flight
    └── editor (Editor) — always focused, always at the bottom

Four binding wiring obligations (task-16-brief.md; RED-asserted in
``tests/tui/test_app.py``):

(a) ``term.drain_pending()`` bytes are fed into the ``StdinBuffer`` *before*
    ``loop.add_reader(fd, ...)`` is attached (see ``_run``).
(b) No ``loop.add_signal_handler(signal.SIGWINCH, ...)`` anywhere — resize
    goes through ``term.on_resize(tui.on_resize)`` only (see ``_run``).
(c) ``term.kitty_enabled`` threads into ``Editor.handle_input``'s
    ``parse_key`` call sites (editor.py module docstring deviation 7).
    Task 16 fix round 1: previously resolved via a scoped monkeypatch of the
    module-level ``parse_key`` name ``editor.py`` calls (``editor.py`` was
    out of this task's original file list); now resolved properly by
    injection — ``editor.py`` gained a public ``kitty_enabled: bool = False``
    attribute its own ``handle_input`` reads, and this module sets it once,
    right after constructing the ``Editor`` (see ``_run``), instead of
    monkeypatching anything.
(d) Submit uses ``Editor.get_expanded_text()`` — this is already true for
    free: ``Editor._submit_value`` (editor.py) calls
    ``self.get_expanded_text().strip()`` *before* invoking ``on_submit``, so
    any ``on_submit`` callback here already only ever sees expanded text,
    never a folded paste marker.

Task 16 fix round 1 — additional findings addressed here (see
``.superpowers/sdd/task-16-report.md``'s "Fix round 1" section for the full
review write-up):

- **Real-terminal Ctrl+C.** Raw mode (``engine/terminal.py``) clears
  ``ISIG`` for the whole session, so a real terminal's Ctrl+C never arrives
  as a process signal — only as the stdin byte ``"\\x03"``. ``_on_stdin_frame``
  now cancels the in-flight ``turn_task`` on that byte when one is running
  (routing through the existing ``asyncio.CancelledError`` → ``"[interrupted]"``
  path in ``_run_turn``), and only falls back to clearing the editor's draft
  buffer when no turn is running. ``loop.add_signal_handler(signal.SIGINT,
  ...)`` (in ``_run_turn``) is kept as a secondary path for a real *external*
  signal (e.g. another process sending ``SIGINT``), not the primary one.
- **Render-on-input (upstream parity).** ``TUI.handle_input`` itself now
  requests a render after dispatching to the focused component (tui.ts:
  827-834) — the per-frame ``tui.request_render()`` workaround this module
  used to need after every ``tui.handle_input(frame)`` call is gone.
- **Slash commands serialize with turns.** ``_on_submit`` now gates ``"/"``
  dispatch behind the exact same ``turn_task is None or turn_task.done()``
  single-flight check plain-text turns already used — a slash command
  submitted while a turn is in flight is ignored (not queued), matching
  phase 2's own busy semantics, instead of racing a second command against
  the running turn (e.g. ``/clear`` swapping ``app_state.session`` out from
  under an in-flight ``session.prompt()`` iteration).

Task 16 fix round 2 — re-review finding addressed here (see
``.superpowers/sdd/task-16-report.md``'s "Fix round 2" section for the full
write-up):

- **Mid-turn submit no longer masquerades as accepted.** ``_on_submit`` used
  to echo the text into the transcript and call ``editor.add_to_history``
  *before* the busy gate, even though ``Editor._submit_value`` had already
  cleared the buffer on Enter — a submit made while a turn was running
  therefore looked accepted (echoed, recorded in history) but never reached
  the model, and the draft was gone. The busy branch now restores the text
  into the editor instead (``editor.set_text(text)``, cursor at the end),
  and the echo/``add_to_history`` calls only run once the gate is clear.
  Full upstream queueing (``restoreQueuedMessagesToEditor``) is a phase-4
  parity item, not built here — this is a minimal correctness fix.

Task 19 acceptance follow-up (maintainer side-by-side finding #2, pulled
forward from phase-4 — see ``.superpowers/sdd/progress.md``'s "Task 19 验收
追加发现 2" entry and ``components/tool_execution.py``'s module docstring):
``ToolCallEvent``/``ToolResultEvent`` now build/resolve a styled
``ToolExecution`` component (keyed by ``tool_call.id`` in
``tool_components``) instead of a plain ``Text`` line, and Ctrl+O
(``"\\x0f"``) is intercepted in ``_on_stdin_frame`` — the same layer that
already special-cases Ctrl+C/Ctrl+D — toggling a global ``tools_expanded``
flag applied to every live component (upstream's
``toggleToolOutputExpansion``, ``interactive-mode.ts:3636``). This is an
app-level concern, not an editor one, so it is *not* routed through
``engine/keybindings.py``'s ``DEFAULT_EDITOR_BINDINGS`` table (which maps
editor-internal actions only). The separate red-foreground line previously
shown for a tool-result error is gone — the component's own error-tinted
background is now the sole error indicator, matching upstream.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path

from pipython import (
    AgentEnd,
    AgentSession,
    AgentSessionConfig,
    AssistantMessage,
    ErrorEvent,
    MessageEnd,
    MessageStart,
    ModelClient,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
    create_agent_session,
)
from pipython.testing import FakeClient
from pipython.tui.completers import build_file_list
from pipython.tui.components.autocomplete import CombinedProvider, CommandProvider, PathProvider
from pipython.tui.components.editor import Editor
from pipython.tui.components.loader import Loader
from pipython.tui.components.markdown import Markdown
from pipython.tui.components.text import Text
from pipython.tui.components.tool_execution import ToolExecution
from pipython.tui.engine.stdin_buffer import StdinBuffer
from pipython.tui.engine.term_caps import TermCaps, detect_caps
from pipython.tui.engine.terminal import RealTerminal, TerminalIO
from pipython.tui.engine.tui import TUI, Container

from .commands import AppState, CommandContext, Sink, build_registry, dispatch

__all__ = ["run_app", "make_client", "load_fake_client", "extract_text"]

_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_DIM = "\x1b[2m"


def extract_text(message: AssistantMessage) -> str:
    """Join every ``text``-type content block, skipping tool calls — moved
    here verbatim from the retired ``render.py`` (Task 18); the only caller
    is this module's own ``_run_turn``, which needs the full rendered text
    of a completed assistant message for the Markdown re-render at
    ``MessageEnd``."""
    return "".join(c.text for c in message.content if c.type == "text")


def load_fake_client(path: str) -> FakeClient:
    """Moved here verbatim from the retired legacy ``app.py`` (Task 18) —
    the ``PI_PYTHON_FAKE_SCRIPT`` env-var wiring below (``make_client``) is
    this module's only caller, and the CLI (``tui/__init__.py``) needs it
    importable from wherever the sole remaining engine lives."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FakeClient(script=[AssistantMessage.model_validate(d) for d in data])


def make_client(model: str) -> ModelClient | None:
    """Moved here verbatim from the retired legacy ``app.py`` (Task 18):
    ``PI_PYTHON_FAKE_SCRIPT`` -> ``FakeClient`` wiring (test-only escape
    hatch, spec §7), used by the CLI (``tui/__init__.py``) so ``pipython``
    honors the same env var it always did, regardless of which engine is
    running."""
    fake = os.environ.get("PI_PYTHON_FAKE_SCRIPT")
    if fake:
        return load_fake_client(fake)
    return None


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
# run_app
# =============================================================================


async def run_app(
    *,
    model: str,
    cwd: Path,
    client: ModelClient | None = None,
    term: TerminalIO | None = None,
) -> None:
    """Spec §6's app loop (renamed from ``run_app2`` in Task 18, once this
    became the only engine). ``term`` is injectable (tests pass a
    ``RecordingTerm``-derived double, never a real terminal); when omitted,
    a real terminal is required (TTY hard requirement, spec §6) — a
    non-interactive ``stdin``/``stdout`` prints one line and returns rather
    than hanging or crashing."""
    owns_term = term is None
    real_term: RealTerminal | None = None
    if owns_term:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("pipython: the TUI requires a real terminal (tty).")
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
    # Obligation (c): thread the negotiated Kitty capability into the
    # editor's parse_key calls (editor.py module docstring deviation 7) via
    # the public attribute it exposes for exactly this — set once, right
    # after construction. Safe to read now (not stale) because
    # RealTerminal.start() negotiates Kitty synchronously, before run_app
    # ever reaches this point (see run_app's own call to real_term.start()
    # above); a bare TerminalIO that doesn't carry kitty_enabled at all
    # (legal per the type hint) degrades to the attribute's own False
    # default via getattr.
    editor.kitty_enabled = bool(getattr(term, "kitty_enabled", False))

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

    # Task 18: `CommandContext.console`/`RichSink` are gone (rich dropped
    # from pyproject entirely) — `sink` is now the context's only output
    # boundary, and it is always this real `_ComponentSink`.
    cmd_ctx = CommandContext(app=app_state, sink=sink)

    quit_event = asyncio.Event()
    turn_task: asyncio.Task[None] | None = None

    # Ctrl+O ("app.tools.expand", interactive-mode.ts:2513/3636): a single
    # global expand/collapse flag applied to every ToolExecution component
    # ever created this session (upstream's toggleToolOutputExpansion —
    # keyed by tool_call.id so a ToolResultEvent can find the component its
    # ToolCallEvent already created and pushed into the transcript).
    tools_expanded = False
    tool_components: dict[str, ToolExecution] = {}

    def _append(text: str, style: str = "", *, wrap: bool = True) -> None:
        transcript.add_child(Text(text, style=style, wrap=wrap))
        tui.request_render()

    def _do_quit() -> None:
        # wrap=False (components/text.py deviation 5): the session path is an
        # unbreakable token after "session: " -- word-wrapping this banner can
        # land the wrap point exactly on that space on a narrow real pty,
        # splitting "session:" and the path across two captured rows with no
        # rejoinable space (breaks `pane.wait_for(r"session: ")` — see
        # .superpowers/sdd/task-17-report.md). Matches phase-2 app.py's
        # deliberate `soft_wrap=True` for this exact line: let the terminal
        # soft-wrap natively instead of hard-wrapping at a word boundary.
        _append(f"session: {app_state.session.store.path}", style=_DIM, wrap=False)
        quit_event.set()

    def _on_submit(text: str) -> None:
        nonlocal turn_task
        if not text:
            return
        # Important finding 2 (task-16 fix round 1): slash commands
        # serialize with turns under the exact same single-flight gate
        # plain-text turns already used — a command submitted while a turn
        # is in flight is ignored (not queued), matching phase 2's
        # ignore-while-busy semantics, rather than racing a second command
        # (e.g. `/clear` swapping app_state.session) against the running
        # turn's still-iterating `session.prompt()` generator.
        busy = turn_task is not None and not turn_task.done()
        if busy:
            # Fix round 2 (task-16 re-review): the echo + add_to_history
            # calls used to happen BEFORE this busy check, even though
            # `Editor._submit_value` had already cleared the buffer on
            # Enter — the text looked "accepted" (echoed into the
            # transcript, recorded in history) but never reached the model,
            # and the draft was destroyed. Restore it into the editor
            # instead (cursor lands at the end, `set_text`'s own default)
            # so nothing is lost and nothing pretends to be accepted. Full
            # upstream queueing (`restoreQueuedMessagesToEditor`) is a
            # phase-4 parity item, not built here.
            editor.set_text(text)
            return
        editor.add_to_history(text)
        _append(text)
        if text.startswith("/"):
            asyncio.create_task(_run_command(text))
        else:
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
                        transcript.replace_child(slot, Markdown(full, caps))
                    slot = None
                    tui.request_render()
                elif isinstance(event, ToolCallEvent):
                    # Maintainer side-by-side finding (task-19 acceptance,
                    # pulled forward from phase-4): a styled ToolExecution
                    # component (bold title + state-tinted background)
                    # replaces the old plain "[tool] <name> <args>" Text
                    # line. Keyed by tool_call.id so the matching
                    # ToolResultEvent below can find it again.
                    comp = ToolExecution(event.tool_call.name, event.tool_call.arguments)
                    comp.set_expanded(tools_expanded)
                    tool_components[event.tool_call.id] = comp
                    transcript.add_child(comp)
                    tui.request_render()
                elif isinstance(event, ToolResultEvent):
                    # The component's own error-tinted background is now
                    # the error indicator (matches upstream: there is no
                    # separate red error line for tool-result errors,
                    # tool-execution.ts's state background is the sole
                    # indicator) — replaces the old separate red `_append`
                    # for `is_error` tool results.
                    tool_comp = tool_components.get(event.tool_call.id)
                    if tool_comp is not None:
                        tool_comp.set_result(event.result.content, event.result.is_error)
                    tui.request_render()
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
        nonlocal tools_expanded
        if frame == "\x0f":  # Ctrl+O ("app.tools.expand")
            # Upstream wires this as `this.defaultEditor.onAction
            # ("app.tools.expand", ...)` (interactive-mode.ts:2513) — an
            # editor-level action binding. This port's `keybindings.py`/
            # `DEFAULT_EDITOR_BINDINGS` maps *editor* actions only (cursor
            # motion, kill-ring, etc.); toggling every ToolExecution
            # component in the transcript is an app-level concern, not an
            # editor one, so it is intercepted here — at the exact same
            # layer this app already special-cases Ctrl+C/Ctrl+D — instead
            # of being threaded through the editor's action-binding table.
            tools_expanded = not tools_expanded
            for tool_comp in tool_components.values():
                tool_comp.set_expanded(tools_expanded)
            tui.request_render()
            return
        if frame == "\x03":  # Ctrl+C
            # Critical finding 1 (task-16 fix round 1): raw mode
            # (engine/terminal.py) clears ISIG for the whole session, so a
            # REAL terminal's Ctrl+C never arrives as a process signal —
            # only as this stdin byte. If a turn is in flight, cancel it
            # (routes through _run_turn's existing `asyncio.CancelledError`
            # handler -> "[interrupted]"); otherwise fall back to
            # editor.py's documented behavior of no-oping on Ctrl+C
            # ("parent's job (exit/clear)") by clearing the draft buffer
            # ourselves. `loop.add_signal_handler(signal.SIGINT, ...)` in
            # `_run_turn` remains wired as a secondary path for a genuine
            # *external* signal (e.g. `kill -INT <pid>` from another
            # process) — not the primary Ctrl+C path anymore.
            if turn_task is not None and not turn_task.done():
                turn_task.cancel()
            else:
                editor.set_text("")
                tui.request_render()
            return
        if frame == "\x04" and editor.text == "":  # Ctrl+D, empty buffer: exit
            _do_quit()
            return
        # Important finding 1 (task-16 fix round 1): TUI.handle_input now
        # requests its own render after dispatching (upstream parity,
        # tui.ts:827-834) — no separate request_render() call needed here
        # anymore.
        tui.handle_input(frame)

    stdin_buffer = StdinBuffer(on_frame=_on_stdin_frame)

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
