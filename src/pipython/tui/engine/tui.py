"""Differential-rendering TUI engine core — Python port of upstream pi's
``packages/tui/src/tui.ts``.

Scope (task 7 of the phase-3 TUI port; see
``.superpowers/sdd/task-7-brief.md``): the ``Component``/``Focusable``
contracts (tui.ts:64-88, 104-107), ``CURSOR_MARKER`` (tui.ts:120),
``Container`` (tui.ts:256-290), and the pure content-diff/viewport core of
``TUI.doRender`` (tui.ts:1254-1620, a 367-line function). Overlay
compositing, focus-restore state machines, resize (width/height-change)
handling, and hardware-cursor/IME marker extraction are a *later* task
(tui.py 之二 — overlay 栈/焦点链 + resize/硬件光标) and are deliberately not
implemented here; the seams below are left clean for that task to extend
(``_hardware_cursor_row`` is tracked but never diverges from the plain
content cursor row without marker-driven repositioning; ``set_focus``/
``handle_input`` are minimal by design).

Declared deviations from upstream:

1. **No resize (width/height-change) handling.** ``previous_width``/
   ``previous_height`` tracking and the ``widthChanged``/``heightChanged``
   full-redraw branches (tui.ts:1258-1259, 1344-1358) are intentionally
   omitted — a later task's job. ``do_render`` always re-renders against the
   terminal's *current* ``columns``, it just never treats a change in that
   value as a reason to force a full redraw.
2. **No overlay compositing, cursor-marker extraction, or IME hardware-cursor
   positioning** (``compositeOverlays``/``extractCursorPosition``/
   ``applyLineResets``/``positionHardwareCursor``, tui.ts:1050+, 1095+,
   1234+, 1627+) — a later task's job. ``_hardware_cursor_row`` exists (it's
   part of the diff algorithm's own cursor-addressing math, not an IME
   feature by itself) but nothing in this module ever moves it away from
   ``_cursor_row``.
3. **No Kitty terminal-image branches at all** — per the task-7 brief's
   filter warning, every ``isImageLine``/``getKittyImageReservedRows``/
   ``deleteKittyImages``/``collectKittyImageIds``/
   ``expandChangedRangeForKittyImages`` reference in upstream's ``doRender``
   is skipped outright; terminal images are a declared spec non-goal.
4. **No synchronized-output wrapping** (``\x1b[?2026h``/``\x1b[?2026l``,
   wrapped around every buffer upstream writes). This is a flicker-reduction
   nicety orthogonal to the diff algorithm itself — safe to layer on top
   later without touching any of the logic below.
5. **Discrete per-primitive ``term.write()`` calls, not one accumulated
   buffer string per render pass.** Upstream builds one big ``buffer``
   string per ``doRender`` call and writes it via a single
   ``this.terminal.write(buffer)``. This port instead issues one
   ``term.write()`` call per atomic ANSI operation (cursor move, carriage
   return, line erase, text chunk) because (a) ``TerminalIO`` (task 6) is a
   minimal write-only ``Protocol`` — it has no ``moveBy``/``eraseLine``
   convenience methods the way upstream's concrete ``Terminal`` does, so
   this module must emit raw ANSI itself — and (b) the test double
   (``RecordingTerm``, ``tests/tui/engine/conftest.py``) is deliberately
   built to record/replay a *sequence* of atomic operations for assertion
   purposes, matching the task-7 brief's own test-plan wording for e.g.
   ``test_single_middle_line_change_rewrites_only_that_line``: "1. Move
   cursor... 2. Erase that line... 3. Write the new content" — three
   discrete steps. Same bytes reach the terminal in the same order either
   way; the only real difference from upstream is the loss of atomic
   redraw during a signal/resize race, which synchronized-output wrapping
   (deviation 4) guards against.
6. **``request_render()`` degrades to an immediate, synchronous
   ``do_render()`` call when there is no running asyncio event loop**,
   rather than upstream's Node-always-has-an-event-loop assumption
   (``process.nextTick``/``setTimeout``, tui.ts:712-748). This makes
   ``request_render()`` itself safely callable from synchronous code (e.g.
   directly from a test, with no loop running) in addition to
   ``do_render()``, which the brief requires to be directly, synchronously
   callable regardless.
7. **No ``MIN_RENDER_INTERVAL_MS`` (~16ms) throttle / re-schedule loop.**
   Upstream's ``scheduleRender`` (tui.ts:737-748) throttles to roughly
   60fps and re-arms itself if a render was requested again while one was
   in flight. The task-7 brief specifies plain ``loop.call_soon`` coalescing
   only ("`request_render`...`loop.call_soon` 归并，多次调用一帧执行") — every
   ``request_render()`` call before the next event-loop iteration collapses
   into a single ``do_render()``, with no additional frame-rate throttling.
8. **``set_root(component)`` is this port's own API surface, not
   upstream's.** Upstream's ``TUI`` *is* a ``Container`` (``class TUI
   extends Container``) — you add children to the TUI instance directly.
   The task-7 brief specifies a single ``set_root`` entry point instead
   (simpler than making ``TUI`` itself a multi-child container). Kept a
   pure assignment — it deliberately does not itself call
   ``request_render()`` — so tests can call ``set_root`` then ``do_render()``
   directly without an implicit prior render muddying op-sequence
   assertions.
9. **``Component.handle_input`` is not a formal Protocol member**, even
   though upstream's ``handleInput?(data: string): void`` (tui.ts:75) is a
   genuinely optional interface member in TypeScript's structural-optional
   sense. Python's ``typing.Protocol`` has no equivalent: giving a Protocol
   method a body is only "inherited for free" by classes that explicitly
   subclass the Protocol (nominal), not by unrelated duck-typed classes
   checked structurally — so declaring it here would make it a *required*
   member for every ``Component``, breaking plain render+invalidate
   components (including this task's own test double, ``StaticComponent``).
   Kept as a dynamically-probed convention instead, exactly like
   ``Focusable`` is probed via ``is_focusable``: callers use
   ``getattr(component, "handle_input", None)`` (see ``TUI.handle_input``).
10. **``Component.wantsKeyRelease`` (tui.ts:81) is not ported at all** — it
    is outside the task-7 brief's Produces list entirely (an input-dispatch
    concern belonging to a later task), not omitted by oversight.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, TypeGuard

from .terminal import CLEAR_LINE

if TYPE_CHECKING:
    from asyncio import Handle

    from .terminal import TerminalIO

__all__ = [
    "CURSOR_MARKER",
    "Component",
    "Focusable",
    "is_focusable",
    "Container",
    "TUI",
]


# =============================================================================
# Cursor marker (tui.ts:113-120)
# =============================================================================

CURSOR_MARKER = "\x1b_pi:c\x07"
"""Zero-width APC (Application Program Command) sequence a focused component
emits at the cursor position in its rendered output (tui.ts:120). Terminals
ignore it outright. Finding and stripping it, then positioning the hardware
cursor there, is a later task's job (see module docstring deviation 2) —
this task only defines the constant for that task to consume."""


# =============================================================================
# Component / Focusable contracts (tui.ts:64-88, 104-112)
# =============================================================================


class Component(Protocol):
    """tui.ts:64-88 ``Component`` — the two *required* members only
    (``render``/``invalidate``). See module docstring deviations 9-10 for
    why ``handleInput``/``wantsKeyRelease`` are not part of this Protocol."""

    def render(self, width: int) -> list[str]:
        """Render to lines for the given viewport width (tui.ts:70)."""
        ...

    def invalidate(self) -> None:
        """Invalidate any cached rendering state (tui.ts:87)."""
        ...


class Focusable(Protocol):
    """tui.ts:104-107 ``Focusable`` — the sole mutable attribute upstream's
    TUI reads/writes directly on focus change. There is no
    ``focus()``/``unfocus()`` method pair; components inspect ``.focused``
    themselves inside ``render()`` to decide whether to emit
    ``CURSOR_MARKER`` (a later task's concern)."""

    focused: bool


def is_focusable(component: Component | None) -> TypeGuard[Focusable]:
    """tui.ts:110-112 ``isFocusable`` type guard: ``True`` iff *component* is
    non-``None`` and exposes a ``focused`` attribute."""
    return component is not None and hasattr(component, "focused")


# =============================================================================
# Container (tui.ts:256-290)
# =============================================================================


class Container:
    """tui.ts:256-290 ``Container`` — a ``Component`` that concatenates its
    children's rendered lines. Structurally satisfies ``Component`` (it
    implements ``render``/``invalidate``); not explicitly subclassed from
    the Protocol, matching this module's duck-typing style throughout."""

    def __init__(self) -> None:
        self.children: list[Component] = []

    def add_child(self, component: Component) -> None:
        self.children.append(component)

    def remove_child(self, component: Component) -> None:
        try:
            self.children.remove(component)
        except ValueError:
            pass

    def clear(self) -> None:
        self.children = []

    def invalidate(self) -> None:
        for child in self.children:
            child.invalidate()

    def render(self, width: int) -> list[str]:
        lines: list[str] = []
        for child in self.children:
            lines.extend(child.render(width))
        return lines


# =============================================================================
# TUI (tui.ts:295-1714; this task ports only the doRender diff/viewport core,
# tui.ts:1254-1620 — see module docstring for the full scope statement)
# =============================================================================


class TUI:
    """Differential-rendering driver: diffs the root component's rendered
    lines against the previous frame, cursor-addresses to the first changed
    line, and rewrites only what changed — growing downward without ever
    clearing the screen (scrollback history is preserved), per the task-7
    brief's port convention."""

    def __init__(self, term: TerminalIO, *, clear_on_shrink: bool = False) -> None:
        self.term = term
        self.clear_on_shrink = clear_on_shrink

        self._root: Component | None = None
        self._focused: Component | None = None

        # upstream `stopped = false` by default (tui.ts:317) — NOT gated
        # behind start(); do_render() must be directly callable without it
        # (task-7 brief: "do_render()（测试可直调同步跑）").
        self._stopped = False

        # request_render() coalescing (tui.ts:712-748, simplified per module
        # docstring deviation 7: plain call_soon coalescing, no throttle).
        self._render_scheduled = False
        self._render_handle: Handle | None = None

        # Diff/viewport bookkeeping (tui.ts:297-315). previous_width/
        # previous_height are intentionally absent — see module docstring
        # deviation 1.
        self._previous_lines: list[str] = []
        self._cursor_row = 0  # tui.ts:310 — end of rendered content
        self._hardware_cursor_row = 0  # tui.ts:311 — actual cursor row
        self._max_lines_rendered = 0  # tui.ts:314
        self._previous_viewport_top = 0  # tui.ts:315

    # -- component tree --------------------------------------------------

    def set_root(self, component: Component) -> None:
        """Set the single root component this port renders (see module
        docstring deviation 8 for why this differs from upstream's
        Container-based API). Does not itself request a render."""
        self._root = component

    def set_focus(self, component: Component | None) -> None:
        """Flip ``.focused`` on the previously- and newly-focused components
        (tui.ts:366-368's core effect, minus the overlay focus-restore state
        machine at tui.ts:370-506, which is a later task's job)."""
        if is_focusable(self._focused):
            self._focused.focused = False
        self._focused = component
        if is_focusable(self._focused):
            self._focused.focused = True

    def handle_input(self, data: str) -> None:
        """Forward a raw input frame to the focused component's optional
        ``handle_input``, if it has one (tui.ts:handleInput's core dispatch,
        minus overlay/debug-key routing — a later task's job). Parsing the
        frame into a ``KeyEvent`` is the component's own responsibility."""
        if self._focused is None:
            return
        handler = getattr(self._focused, "handle_input", None)
        if callable(handler):
            handler(data)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """tui.ts:632-643, trimmed to this task's scope (no terminal input
        wiring or cell-size query — later tasks)."""
        self._stopped = False
        self.request_render()

    def stop(self) -> None:
        """tui.ts:682-701, trimmed to this task's scope: ``TerminalIO`` (task
        6) has no ``show_cursor``/``stop`` members of its own to call here —
        only cancels any pending coalesced render."""
        self._stopped = True
        if self._render_handle is not None:
            self._render_handle.cancel()
            self._render_handle = None
        self._render_scheduled = False

    # -- render scheduling (tui.ts:712-748) ---------------------------------

    def request_render(self, force: bool = False) -> None:
        """Coalesce repeated calls into a single ``do_render()`` per event
        loop turn (module docstring deviation 7). ``force=True`` resets all
        diff state immediately so the next render is a full first-render-style
        repaint (tui.ts:713-720)."""
        if force:
            self._previous_lines = []
            self._cursor_row = 0
            self._hardware_cursor_row = 0
            self._max_lines_rendered = 0
            self._previous_viewport_top = 0

        if self._render_scheduled:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. called from synchronous code/tests,
            # module docstring deviation 6) — nothing to coalesce against.
            self.do_render()
            return

        self._render_scheduled = True
        self._render_handle = loop.call_soon(self._run_scheduled_render)

    def _run_scheduled_render(self) -> None:
        self._render_scheduled = False
        self._render_handle = None
        if self._stopped:
            return
        self.do_render()

    # -- the diff/viewport core (tui.ts:1254-1620) --------------------------

    def do_render(self) -> None:
        """Synchronously render one frame: diff the root's output against
        the previous frame and write only what changed. Directly callable
        from tests (task-7 brief)."""
        if self._stopped:
            return

        height = self.term.rows
        width = self.term.columns

        prev_viewport_top = self._previous_viewport_top
        viewport_top = prev_viewport_top
        hardware_cursor_row = self._hardware_cursor_row

        def compute_line_diff(target_row: int) -> int:
            current_screen_row = hardware_cursor_row - prev_viewport_top
            target_screen_row = target_row - viewport_top
            return target_screen_row - current_screen_row

        new_lines = self._root.render(width) if self._root is not None else []

        def full_render(clear: bool) -> None:
            if clear:
                self.term.write("\x1b[2J\x1b[H\x1b[3J")  # clear screen + scrollback
            for i, line in enumerate(new_lines):
                if i > 0:
                    self.term.write("\r\n")
                self.term.write(line)
            self._cursor_row = max(0, len(new_lines) - 1)
            self._hardware_cursor_row = self._cursor_row
            if clear:
                self._max_lines_rendered = len(new_lines)
            else:
                self._max_lines_rendered = max(self._max_lines_rendered, len(new_lines))
            buffer_length = max(height, len(new_lines))
            self._previous_viewport_top = max(0, buffer_length - height)
            self._previous_lines = new_lines

        # First render — just output everything (tui.ts:1335-1339).
        if not self._previous_lines:
            full_render(False)
            return

        # Content shrunk below the working area — re-render to clear empty
        # rows (tui.ts:1359-1365).
        if self.clear_on_shrink and len(new_lines) < self._max_lines_rendered:
            full_render(True)
            return

        # Find first and last changed lines (tui.ts:1367-1394).
        first_changed = -1
        last_changed = -1
        max_lines = max(len(new_lines), len(self._previous_lines))
        for i in range(max_lines):
            old_line = self._previous_lines[i] if i < len(self._previous_lines) else ""
            new_line = new_lines[i] if i < len(new_lines) else ""
            if old_line != new_line:
                if first_changed == -1:
                    first_changed = i
                last_changed = i

        appended_lines = len(new_lines) > len(self._previous_lines)
        if appended_lines:
            if first_changed == -1:
                first_changed = len(self._previous_lines)
            last_changed = len(new_lines) - 1

        append_start = (
            appended_lines and first_changed == len(self._previous_lines) and first_changed > 0
        )

        # No changes — nothing to write (tui.ts:1397-1401, minus the
        # hardware-cursor-repositioning call, a later task's job).
        if first_changed == -1:
            self._previous_viewport_top = prev_viewport_top
            return

        # All changes are in deleted lines — nothing to render, just erase
        # the tail (tui.ts:1404-1449).
        if first_changed >= len(new_lines):
            if len(self._previous_lines) > len(new_lines):
                target_row = max(0, len(new_lines) - 1)
                if target_row < prev_viewport_top:
                    full_render(True)
                    return
                self._move_cursor(compute_line_diff(target_row))
                self.term.write("\r")
                extra_lines = len(self._previous_lines) - len(new_lines)
                if extra_lines > height:
                    full_render(True)
                    return
                clear_start_offset = 0 if len(new_lines) == 0 else 1
                if extra_lines > 0 and clear_start_offset > 0:
                    self._move_cursor(clear_start_offset)
                for i in range(extra_lines):
                    self.term.write("\r")
                    self.term.write(CLEAR_LINE)
                    if i < extra_lines - 1:
                        self._move_cursor(1)
                move_back = max(0, extra_lines - 1 + clear_start_offset)
                if move_back > 0:
                    self._move_cursor(-move_back)
                self._cursor_row = target_row
                self._hardware_cursor_row = target_row
            self._previous_lines = new_lines
            self._previous_viewport_top = prev_viewport_top
            return

        # Differential rendering can only touch what was actually visible
        # (tui.ts:1452-1456).
        if first_changed < prev_viewport_top:
            full_render(True)
            return

        # Render from first changed line to last changed line
        # (tui.ts:1458-1553).
        prev_viewport_bottom = prev_viewport_top + height - 1
        move_target_row = first_changed - 1 if append_start else first_changed
        if move_target_row > prev_viewport_bottom:
            current_screen_row = max(0, min(height - 1, hardware_cursor_row - prev_viewport_top))
            move_to_bottom = height - 1 - current_screen_row
            if move_to_bottom > 0:
                self._move_cursor(move_to_bottom)
            scroll = move_target_row - prev_viewport_bottom
            for _ in range(scroll):
                self.term.write("\r\n")
            prev_viewport_top += scroll
            viewport_top += scroll
            hardware_cursor_row = move_target_row

        self._move_cursor(compute_line_diff(move_target_row))
        self.term.write("\r\n" if append_start else "\r")

        render_end = min(last_changed, len(new_lines) - 1)
        for i in range(first_changed, render_end + 1):
            if i > first_changed:
                self.term.write("\r\n")
            self.term.write(CLEAR_LINE)
            self.term.write(new_lines[i])

        final_cursor_row = render_end

        # If there were more lines before, clear them and move cursor back
        # (tui.ts:1556-1571).
        if len(self._previous_lines) > len(new_lines):
            if render_end < len(new_lines) - 1:
                self._move_cursor(len(new_lines) - 1 - render_end)
                final_cursor_row = len(new_lines) - 1
            extra_lines = len(self._previous_lines) - len(new_lines)
            for _ in range(len(new_lines), len(self._previous_lines)):
                self.term.write("\r\n")
                self.term.write(CLEAR_LINE)
            self._move_cursor(-extra_lines)

        self._cursor_row = max(0, len(new_lines) - 1)
        self._hardware_cursor_row = final_cursor_row
        self._max_lines_rendered = max(self._max_lines_rendered, len(new_lines))
        self._previous_viewport_top = max(prev_viewport_top, final_cursor_row - height + 1)
        self._previous_lines = new_lines

    # -- cursor primitive (module docstring deviation 5) --------------------

    def _move_cursor(self, delta: int) -> None:
        """Move the cursor vertically by ``delta`` rows: down if positive, up
        if negative, no-op if zero. Emitted directly as raw ANSI (not via a
        ``TerminalIO`` method — see module docstring deviation 5)."""
        if delta > 0:
            self.term.write(f"\x1b[{delta}B")
        elif delta < 0:
            self.term.write(f"\x1b[{-delta}A")
