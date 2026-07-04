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

   **Task 17 review, Important 1 (fix round 2) — flush granularity:** this
   deviation is also why flushing ``sys.stdout`` inside ``RealTerminal.write``
   itself (this port's first fix for the "newline-less frame never reaches a
   line-buffered tty" bug, see ``terminal.py``'s ``RealTerminal.flush``
   docstring) was the wrong granularity. Because ``do_render`` emits one
   discrete ``term.write()`` per atomic ANSI primitive rather than upstream's
   single accumulated buffer, a per-write flush means N flushes per rendered
   frame (N = however many cursor-move/erase/text-chunk primitives that
   frame happened to emit) instead of one — needless syscall overhead
   proportional to diff complexity, not to frame count. The earlier
   justification that "upstream's single-buffer-per-frame write makes
   per-write equivalent to per-frame anyway" does not hold *for this port*
   precisely because of this deviation: upstream's one-write-per-frame shape
   is exactly what makes a per-write flush equivalent to a per-frame flush
   *there*; this port's discrete-write shape breaks that equivalence. The
   architecturally correct fix keeps ``write()`` flush-free and adds a
   single ``term.flush()`` call at the very end of ``do_render`` instead
   (see below) — restoring one flush per frame regardless of how many
   discrete writes the diff needed.
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
11. **Upstream's width-exceeds-terminal crash-log branch is not ported**
    (``if (!isImage && visibleWidth(line) > width) { ... }``, tui.ts:1519-1545)
    — the case where a rendered line is wider than the terminal writes a
    debug dump to ``~/.pi/agent/pi-crash.log``, stops the terminal, and
    throws. That is a debug safety net for catching a misbehaving component
    during upstream development, not part of the diff algorithm itself;
    unconditional filesystem writes from deep inside a render call are
    undesirable in this port regardless. Omitting it does not change any
    diff/viewport behavior this task's tests exercise — a too-wide line still
    gets erased (``ERASE_LINE_FULL``) and written by the surrounding code
    exactly as upstream does either way, just without the crash-log side
    effect and the ``throw``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, TypeGuard

from .terminal import HIDE_CURSOR, SHOW_CURSOR
from .utils import visible_width

if TYPE_CHECKING:
    from asyncio import Handle

    from .terminal import TerminalIO

__all__ = [
    "CURSOR_MARKER",
    "ERASE_LINE_FULL",
    "Component",
    "Focusable",
    "is_focusable",
    "Container",
    "TUI",
    "OverlayHandle",
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


ERASE_LINE_FULL = "\x1b[2K"
"""Erase-entire-line sequence ``doRender`` itself builds directly into its
buffer (tui.ts:1432, 1508 [Kitty-image row-clear — out of scope, module
docstring deviation 3], 1519, 1564) — literal ``"\\x1b[2K"``, distinct from
``terminal.py``'s ``CLEAR_LINE = "\\x1b[K"`` (terminal.ts:493, ``clearLine()``
method). Those are two different upstream call sites: ``doRender`` never
calls ``terminal.clearLine()``; it always inlines its own erase literal.
Fix round 1: this port previously imported and wrote ``terminal.py``'s
``CLEAR_LINE`` here by mistake — same *purpose* (erase a line) but the wrong
*bytes*, one column short of upstream's own (a full ``\\x1b[2K`` clears the
entire line regardless of cursor column; ``\\x1b[K`` only clears from the
cursor to the end of the line)."""


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

    def replace_child(self, old: Component, new: Component) -> None:
        """Swap ``old`` for ``new`` in place (same index), leaving every
        other child and their order untouched. Not an upstream port — this
        port's own convenience, added (Task 16 fix round 1, Minor finding 2)
        so callers doing an in-place content replace (e.g. ``app2.py``
        swapping a streaming ``Text`` slot for its rendered ``Markdown`` at
        message_end) don't have to reach into ``self.children`` and
        re-derive the index via ``.index(old)`` themselves. A no-op if
        ``old`` isn't currently a child, mirroring ``remove_child``'s own
        suppressed-``ValueError`` convention above."""
        try:
            idx = self.children.index(old)
        except ValueError:
            return
        self.children[idx] = new

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
# Overlay stack (tui.ts:326, 366-620 focus-restore state machine, 509-580
# showOverlay's returned handle) — Task 8's addition on top of Task 7's
# Component/Container/diff core above.
# =============================================================================


class _OverlayEntry:
    """tui.ts:398-405 ``OverlayStackEntry``, narrowed to this port's
    simplified ``show_overlay(component, *, anchor_row=None)`` signature: no
    ``options``/``hidden``/``focusOrder`` fields because this port has no
    ``OverlayOptions`` (anchor enum/margins/width/maxHeight/visible-callback/
    nonCapturing), no ``setHidden``, and no ``.focus()``-triggered
    refocusing — the overlay stack's list order already *is* paint/focus
    order (entries are only ever appended, never reordered), so a separate
    monotonic ``focusOrder`` counter would carry no information a plain list
    index doesn't already have."""

    def __init__(
        self,
        component: Component,
        pre_focus: Component | None,
        anchor_row: int | None,
        *,
        non_capturing: bool = False,
    ) -> None:
        self.component = component
        self.pre_focus = pre_focus
        self.anchor_row = anchor_row
        self.non_capturing = non_capturing


class OverlayHandle:
    """tui.ts:509-580 ``showOverlay``'s returned handle object, narrowed to
    ``.close()`` only per this task's brief Produces list — upstream's
    ``.setHidden()``/``.focus()``/``.unfocus()``/``.isFocused()``/
    ``.isHidden()`` are out of scope (no hide/reveal or manual-refocus API on
    this port's overlay surface)."""

    def __init__(self, tui: TUI, entry: _OverlayEntry) -> None:
        self._tui = tui
        self._entry = entry

    def close(self) -> None:
        """tui.ts:527-541, the ``hide: () => {...}`` closure returned by
        ``showOverlay``: remove this overlay from the stack, retarget any
        other overlay whose ``pre_focus`` pointed at it
        (``retargetOverlayPreFocus``, tui.ts:411-417 — this is what makes
        closing overlays *out of order* safe, see ``TUI._close_overlay``),
        and — only if this overlay currently holds focus — restore focus to
        the new topmost overlay, or, if none remain, to whichever component
        held focus before this overlay opened."""
        self._tui._close_overlay(self._entry)


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

        # Diff/viewport bookkeeping (tui.ts:297-315).
        self._previous_lines: list[str] = []
        self._cursor_row = 0  # tui.ts:310 — end of rendered content
        self._hardware_cursor_row = 0  # tui.ts:311 — actual cursor row
        self._max_lines_rendered = 0  # tui.ts:314
        self._previous_viewport_top = 0  # tui.ts:315

        # tui.ts:298-299 previousWidth/previousHeight — Task 8 addition (Task
        # 7 deliberately omitted these, see module docstring deviation 1's
        # "as of Task 7" framing). 0 is upstream's own sentinel for "no
        # render yet" (doRender's widthChanged/heightChanged both require
        # previous_* != 0 first — so a genuine first render never counts as
        # a resize no matter what the terminal's actual current size is).
        self._previous_width = 0
        self._previous_height = 0

        # Task 8 addition: idempotent HIDE_CURSOR/SHOW_CURSOR toggling.
        # Upstream's positionHardwareCursor (tui.ts:1627-1656) calls
        # terminal.hideCursor()/showCursor() unconditionally on *every*
        # doRender — real terminals don't care about redundant hide/show
        # writes, but this port's discrete-write test double
        # (RecordingTerm) records every write() as a distinct op, and
        # Task 7's own `test_unchanged_rerender_writes_nothing` baseline gate
        # asserts *zero* new ops on a second identical render. Tracking
        # whether the hardware cursor is currently shown/hidden and only
        # writing on an actual transition preserves that baseline while
        # still positioning the cursor (row/col move) on every render that
        # has a marker, exactly as upstream does unconditionally.
        self._cursor_visible = True

        # tui.ts:326 overlayStack — Task 8 addition. See module docstring
        # for what this port's overlay surface omits relative to upstream's
        # full OverlayOptions/overlayFocusRestore state machine.
        self._overlay_stack: list[_OverlayEntry] = []

        # Fix round 1: minimal stand-in for upstream's previousWidth/
        # previousHeight = -1 sentinel (tui.ts:715-716), which routes the
        # next doRender into the widthChanged branch — fullRender(true), a
        # clear-and-redraw — rather than the plain first-render path
        # (fullRender(false), no clear). Since this port doesn't track
        # previous_width/previous_height at all (deviation 1), a dedicated
        # flag plays the same "force the next render to clear" role without
        # implementing full resize tracking.
        self._force_full_clear = False

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
        frame into a ``KeyEvent`` is the component's own responsibility.

        Task 16 fix round 1 (Important finding 1): requests a render right
        after dispatching, unconditionally — upstream parity (tui.ts:
        827-834: ``this.focusedComponent.handleInput(data);
        this.requestRender();``, both inside the same "a handler exists"
        guard this method already has). Previously this method dispatched
        only, leaving every caller to remember its own follow-up
        ``request_render()`` — ``app2.py`` had grown exactly such a
        per-frame workaround (with a docstring that misattributed the
        missing repaint to ``Editor`` having "no tui reference", when the
        actual gap was here); that workaround is now removed as redundant."""
        if self._focused is None:
            return
        handler = getattr(self._focused, "handle_input", None)
        if callable(handler):
            handler(data)
            self.request_render()

    # -- overlay stack (tui.ts:509-580, 411-417) ----------------------------

    def show_overlay(
        self,
        component: Component,
        *,
        anchor_row: int | None = None,
        non_capturing: bool = False,
    ) -> OverlayHandle:
        """tui.ts:509-580 ``showOverlay``, narrowed to this port's simplified
        signature (``anchor_row`` plus ``non_capturing`` only — no
        ``OverlayOptions`` anchor enum/margins/width/maxHeight/
        visible-callback; see module docstring). Records the
        currently-focused component as the new entry's ``pre_focus``
        *before* moving focus (tui.ts:512-517), then steals focus via the
        existing ``set_focus`` (Task 7 contract: reads/writes ``.focused``)
        and requests a render so the overlay actually appears without the
        caller needing to call ``do_render()`` itself (tui.ts:518-519's
        ``terminal.hideCursor()``/``requestRender()`` — the immediate
        ``hideCursor()`` call is skipped as a redundant nicety: this port's
        own ``_position_hardware_cursor`` already converges to the right
        hidden/shown state by the end of the render ``request_render()``
        triggers here).

        Fix round 1 (Critical finding 1): ``non_capturing`` ports upstream's
        ``OverlayOptions.nonCapturing`` (tui.ts:205-206 "If true, don't
        capture keyboard focus when shown"; tui.ts:503 ``if
        (!options?.nonCapturing && this.isOverlayVisible(entry)) {
        this.setFocus(component); }``). When ``True``, ``show_overlay``
        skips ``set_focus`` entirely — the caller's previously-focused
        component (e.g. an ``Editor`` showing a passive autocomplete
        ``SelectList`` overlay that has no ``handle_input`` of its own)
        keeps focus and keeps receiving ``TUI.handle_input``. Without this,
        focus silently steals onto a component with no ``handle_input`` at
        all, and ``TUI.handle_input``'s ``getattr(component, "handle_input",
        None)`` probe finds nothing to call — every subsequent keystroke
        vanishes into a permanent no-op (the real production deadlock this
        option exists to prevent; see ``tests/tui/engine/test_overlay_focus.py``'s
        ``TestNonCapturingOverlay`` and ``editor.py``'s own
        ``_apply_autocomplete_suggestions``, which now passes
        ``non_capturing=True`` here)."""
        entry = _OverlayEntry(
            component=component,
            pre_focus=self._focused,
            anchor_row=anchor_row,
            non_capturing=non_capturing,
        )
        self._overlay_stack.append(entry)
        if not non_capturing:
            self.set_focus(component)
        self.request_render()
        return OverlayHandle(self, entry)

    def _close_overlay(self, entry: _OverlayEntry) -> None:
        """tui.ts:527-541's ``hide()`` closure body. Safe to call for an
        overlay that isn't the topmost (out-of-order close, tui.ts's own
        stack-invariant comment at 366-380): ``_retarget_overlay_pre_focus``
        runs *before* removal so any overlay still open that was chained to
        this one's focus keeps a valid restore target, and focus is only
        ever touched here if THIS overlay currently holds it — closing a
        non-focused overlay from underneath the current one is a pure
        stack-membership change with no focus side effect at all."""
        if entry not in self._overlay_stack:
            return
        self._retarget_overlay_pre_focus(entry)
        self._overlay_stack.remove(entry)
        if self._focused is entry.component:
            top = self._overlay_stack[-1] if self._overlay_stack else None
            self.set_focus(top.component if top is not None else entry.pre_focus)
        self.request_render()

    def _retarget_overlay_pre_focus(self, removed: _OverlayEntry) -> None:
        """tui.ts:411-417 ``retargetOverlayPreFocus``: any *other* still-open
        overlay whose ``pre_focus`` pointed at the overlay being removed
        gets repointed at what that removed overlay would itself have
        restored focus to. Without this, closing overlays out of order
        (bottom-of-stack first, e.g. open A, B then close A while B is still
        open) would leave B's ``pre_focus`` dangling on a component (A) that
        is no longer part of the overlay stack at all."""
        for overlay in self._overlay_stack:
            if overlay is not removed and overlay.pre_focus is removed.component:
                overlay.pre_focus = removed.pre_focus

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

    # -- resize (terminal.ts:150 `onResize`; wired via Task 6's
    # `RealTerminal.on_resize`, NOT `loop.add_signal_handler(SIGWINCH, ...)`
    # — see terminal.py's `on_resize` docstring warning) --------------------

    def on_resize(self) -> None:
        """Zero-arg resize hook, shaped to match ``terminal.py``'s
        ``ResizeCallback`` (``Callable[[], None]``) so the app layer can wire
        it directly: ``real_terminal.on_resize(tui.on_resize)``. Upstream has
        no separate ``onResize`` method on ``TUI`` either — it wires
        ``terminal.start((data) => this.handleInput(data), () =>
        this.requestRender())`` (tui.ts:660-666), i.e. plain
        ``requestRender()`` on every resize. That suffices here too: this
        port's ``do_render`` compares the terminal's *live* ``columns``/
        ``rows`` against what was actually rendered last time
        (``_previous_width``/``_previous_height``) and does the
        widthChanged/heightChanged full-redraw + ``_previous_viewport_top``
        correction itself (tui.ts:1258-1259, 1344-1358) — ``on_resize``
        itself doesn't need to know a resize happened, only that *some*
        render should happen soon, exactly like upstream."""
        self.request_render()

    # -- render scheduling (tui.ts:712-748) ---------------------------------

    def request_render(self, force: bool = False) -> None:
        """Coalesce repeated calls into a single ``do_render()`` per event
        loop turn (module docstring deviation 7). ``force=True`` resets all
        diff state immediately and arms ``_force_full_clear`` so the next
        ``do_render()`` clears the screen+scrollback and repaints everything
        fresh (tui.ts:713-720) — matching upstream's ``previousWidth``/
        ``previousHeight = -1`` sentinel routing into the ``widthChanged``
        branch (tui.ts:1343-1345, ``fullRender(true)``), NOT upstream's plain
        first-render path (``fullRender(false)``, tui.ts:1336-1339), which
        never clears and would leave stale content on screen underneath the
        repaint (fix round 1 — see ``_force_full_clear``'s own comment in
        ``__init__``)."""
        if force:
            self._previous_lines = []
            self._cursor_row = 0
            self._hardware_cursor_row = 0
            self._max_lines_rendered = 0
            self._previous_viewport_top = 0
            self._force_full_clear = True

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
        from tests (task-7 brief).

        Thin wrapper around ``_do_render_impl`` so that exactly one
        ``term.flush()`` happens per rendered frame, at the very end, no
        matter which of ``_do_render_impl``'s many internal branches/early
        returns actually ran (Task 17 review, Important 1 — see ``tui.py``
        module docstring deviation 5's "flush granularity" note and
        ``terminal.py``'s ``RealTerminal.flush`` docstring for the full
        writeup of why frame-granularity, not write-granularity, is the
        correct shape here)."""
        if self._stopped:
            return
        self._do_render_impl()
        self._flush_term()

    def _flush_term(self) -> None:
        """Call ``self.term.flush()`` if it has one. Guarded via
        ``getattr``/``callable`` rather than calling it unconditionally
        because ``flush`` is deliberately *not* a formal ``TerminalIO``
        Protocol member (see ``terminal.py``'s ``TerminalIO`` docstring) —
        a bare double implementing only ``write``/``columns``/``rows`` (the
        original three-member surface) must keep working without raising
        ``AttributeError``."""
        flush = getattr(self.term, "flush", None)
        if callable(flush):
            flush()

    def _do_render_impl(self) -> None:
        """The diff/viewport core itself (tui.ts:1254-1620) — every branch
        below returns directly back to ``do_render``, which flushes exactly
        once after this method returns by whichever path."""
        height = self.term.rows
        width = self.term.columns

        # tui.ts:1257-1258 widthChanged/heightChanged — Task 8 addition.
        # previous_* == 0 is the "no render yet" sentinel (see __init__), so
        # a genuine first render never spuriously counts as a resize.
        width_changed = self._previous_width != 0 and self._previous_width != width
        height_changed = self._previous_height != 0 and self._previous_height != height

        prev_viewport_top = self._previous_viewport_top
        viewport_top = prev_viewport_top
        hardware_cursor_row = self._hardware_cursor_row

        def compute_line_diff(target_row: int) -> int:
            current_screen_row = hardware_cursor_row - prev_viewport_top
            target_screen_row = target_row - viewport_top
            return target_screen_row - current_screen_row

        new_lines = self._root.render(width) if self._root is not None else []

        # Composite overlays over the main content (tui.ts:1274-1276) before
        # the differential compare — so overlay lines participate in the
        # diff exactly like any other content, and a change confined to an
        # overlay only rewrites the rows it actually occupies.
        if self._overlay_stack:
            new_lines = self._composite_overlays(new_lines, width, height)

        # Find and strip CURSOR_MARKER from the *composited* final line
        # array (tui.ts:1279 — after overlay compositing, before line
        # resets) so overlay/scrolled content is positioned correctly
        # without any component ever computing its own screen coordinates.
        cursor_pos = self._extract_cursor_position(new_lines, height)

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
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_lines = new_lines
            self._previous_width = width
            self._previous_height = height

        # Forced full clear (fix round 1): stands in for upstream's
        # previousWidth/previousHeight = -1 sentinel reaching the
        # widthChanged branch (tui.ts:1343-1345) — checked *before* the
        # plain first-render branch below, exactly like upstream checks
        # widthChanged before falling through to the unconditional
        # first-render path. Must win even though request_render(force=True)
        # also empties _previous_lines (which would otherwise satisfy the
        # first-render branch's condition too, but with the wrong — no clear
        # — fullRender(False) behavior).
        if self._force_full_clear:
            self._force_full_clear = False
            full_render(True)
            return

        # First render — just output everything (tui.ts:1335-1339).
        if not self._previous_lines and not width_changed and not height_changed:
            full_render(False)
            return

        # Terminal width changed — wrapping changes, always needs a full
        # re-render (tui.ts:1343-1347).
        if width_changed:
            full_render(True)
            return

        # Terminal height changed — re-render to keep the visible viewport
        # aligned (tui.ts:1349-1353). Upstream carves out an exception for
        # Termux's software-keyboard-driven height toggling
        # (`!isTermuxSession()`) to avoid replaying full history on every
        # keyboard show/hide; this port doesn't special-case that platform
        # quirk, so a height change always gets a full redraw here.
        if height_changed:
            full_render(True)
            return

        # Content shrunk below the working area — re-render to clear empty
        # rows (tui.ts:1359-1365). Skipped while an overlay is open: overlays
        # need the padding rows compositeOverlays extends the buffer with.
        if (
            self.clear_on_shrink
            and len(new_lines) < self._max_lines_rendered
            and not self._overlay_stack
        ):
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

        # No changes — nothing to write, but the hardware cursor may still
        # need repositioning (e.g. it moved within an unchanged line's
        # content) (tui.ts:1397-1401).
        if first_changed == -1:
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_viewport_top = prev_viewport_top
            self._previous_height = height
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
                    self.term.write(ERASE_LINE_FULL)
                    if i < extra_lines - 1:
                        self._move_cursor(1)
                move_back = max(0, extra_lines - 1 + clear_start_offset)
                if move_back > 0:
                    self._move_cursor(-move_back)
                self._cursor_row = target_row
                self._hardware_cursor_row = target_row
            self._position_hardware_cursor(cursor_pos, len(new_lines))
            self._previous_lines = new_lines
            self._previous_width = width
            self._previous_height = height
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
            self.term.write(ERASE_LINE_FULL)
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
                self.term.write(ERASE_LINE_FULL)
            self._move_cursor(-extra_lines)

        self._cursor_row = max(0, len(new_lines) - 1)
        self._hardware_cursor_row = final_cursor_row
        self._max_lines_rendered = max(self._max_lines_rendered, len(new_lines))
        self._previous_viewport_top = max(prev_viewport_top, final_cursor_row - height + 1)
        self._position_hardware_cursor(cursor_pos, len(new_lines))
        self._previous_lines = new_lines
        self._previous_width = width
        self._previous_height = height

    # -- overlay compositing (tui.ts:1032-1085's function head + early
    # return; the anchor-enum/margin/maxHeight resolveOverlayLayout math and
    # the kitty-image/segment-splicing tail, tui.ts:1085-1160, are out of
    # scope — see _composite_overlays' own docstring) --------------------

    def _composite_overlays(self, lines: list[str], width: int, height: int) -> list[str]:
        """tui.ts:1032-1085 ``compositeOverlays``, narrowed to this port's
        simplified ``anchor_row``-only overlay API: no anchor
        enum/margins/maxHeight/nonCapturing/visible-callback
        (``resolveOverlayLayout``, tui.ts:987-1030, has no equivalent
        here — every overlay renders at the *full* terminal ``width`` and
        simply overwrites, rather than column-splices into
        (``compositeLineAt``, tui.ts:1210-1252), the corresponding rows of
        ``lines`` starting at its ``anchor_row``). That "just overwrite the
        full row" simplification is only a degenerate case of upstream's own
        splice math for the COLUMN dimension (``col=0, overlayWidth=width``
        collapses ``compositeLineAt`` to a plain overwrite) — it does
        *not* extend to the ROW dimension the same way. ``row``/
        ``anchor_row`` is a *screen-relative* coordinate (row 0 means "the
        top of the currently visible viewport", not "buffer index 0"), so it
        still needs translating into absolute buffer-array indices via
        upstream's own ``viewportStart`` offset (tui.ts:1074 ``const
        viewportStart = Math.max(0, workingHeight - termHeight);``, tui.ts:
        1079 ``const idx = viewportStart + row + i;``) — ported verbatim
        below as ``viewport_start``.

        Fix round 2: this method previously composited at the bare buffer
        index ``idx = row + i``, silently correct only while the working
        buffer is no taller than the terminal (``viewport_start == 0``) and
        silently *wrong* the moment content has scrolled past one screenful
        (``viewport_start > 0``): an overlay anchored at ``anchor_row=0``
        would land ``viewport_start`` rows *above* the visible window —
        invisible on a real terminal (already scrolled into scrollback) —
        and, since ``_extract_cursor_position`` only scans the bottom
        ``height`` rows, any ``CURSOR_MARKER`` the overlay carried would
        never be found there either, leaking the raw marker bytes into what
        actually gets written instead of being stripped.

        Still ports the padding behavior (tui.ts:1064-1069): the working
        buffer is extended with empty lines so every overlay has a row to
        land on even if it would otherwise run past the end of ``lines`` or
        the terminal's visible height."""
        if not self._overlay_stack:
            return lines
        result = list(lines)
        rendered: list[tuple[list[str], int]] = []
        min_lines_needed = len(result)
        for entry in self._overlay_stack:
            overlay_lines = entry.component.render(width)
            row = entry.anchor_row if entry.anchor_row is not None else 0
            rendered.append((overlay_lines, row))
            min_lines_needed = max(min_lines_needed, row + len(overlay_lines))

        working_height = max(len(result), height, min_lines_needed)
        while len(result) < working_height:
            result.append("")

        # tui.ts:1074 — translate the screen-relative anchor_row into an
        # absolute buffer index via the same scroll offset the rest of
        # do_render already uses (mirrors _previous_viewport_top's own
        # max(0, buffer_length - height) formula, and matches
        # _extract_cursor_position's viewport_top exactly once `result` is
        # padded to working_height, as it is above).
        viewport_start = max(0, working_height - height)

        for overlay_lines, row in rendered:
            for i, line in enumerate(overlay_lines):
                idx = viewport_start + row + i  # tui.ts:1079
                if 0 <= idx < len(result):
                    result[idx] = line
        return result

    # -- hardware cursor (tui.ts:118-120 CURSOR_MARKER, tui.ts:1234-1252
    # extractCursorPosition, tui.ts:1627-1656 positionHardwareCursor) -------

    def _extract_cursor_position(self, lines: list[str], height: int) -> tuple[int, int] | None:
        """tui.ts:1234-1252 ``extractCursorPosition``: scan only the bottom
        ``height`` (visible-viewport) lines, from the last upward, for the
        first row containing ``CURSOR_MARKER``. Strips *that one*
        occurrence from the line (components should only ever embed a
        single marker; extraction doesn't scrub every occurrence if one
        misbehaves and emits more than one — matching upstream's own
        single-``indexOf``-then-return behavior) and returns its (row, col),
        column measured as the *visible* width of the text before the
        marker (ANSI-aware, via ``visible_width`` — not raw ``len()``, which
        would count invisible escape bytes from preceding SGR codes as
        columns). Mutates ``lines`` in place, exactly like upstream mutates
        its ``newLines`` array in place via index assignment."""
        viewport_top = max(0, len(lines) - height)
        for row in range(len(lines) - 1, viewport_top - 1, -1):
            line = lines[row]
            marker_index = line.find(CURSOR_MARKER)
            if marker_index != -1:
                before_marker = line[:marker_index]
                col = visible_width(before_marker)
                lines[row] = line[:marker_index] + line[marker_index + len(CURSOR_MARKER) :]
                return (row, col)
        return None

    def _position_hardware_cursor(
        self, cursor_pos: tuple[int, int] | None, total_lines: int
    ) -> None:
        """tui.ts:1627-1656 ``positionHardwareCursor``. When no marker was
        found this render, hides the hardware cursor (idempotently — see
        ``_cursor_visible``'s docstring in ``__init__``); otherwise moves it
        to the marker's (row, col) — row via the same relative
        ``\\x1b[nB``/``\\x1b[nA`` primitive ``_move_cursor`` uses, column via
        an *absolute* ``\\x1b[<col+1>G`` (1-indexed) — and shows it
        (idempotently). The column move is written unconditionally whenever
        a marker was found (even if the row didn't change), since the
        cursor's column almost always changes between renders (e.g. typing)
        even when its row doesn't; upstream does the same (the row delta is
        conditional, the column move never is).

        Deliberately does *not* port upstream's ``showHardwareCursor``
        opt-in flag (``PI_HARDWARE_CURSOR=1`` env var, default off, which
        would otherwise keep the terminal cursor hidden even when a marker
        is found) — not in this task's Produces list, and gating real
        cursor visibility behind an undocumented env var would make the
        marker-driven positioning this task exists to add invisible by
        default."""
        if cursor_pos is None or total_lines <= 0:
            if self._cursor_visible:
                self.term.write(HIDE_CURSOR)
                self._cursor_visible = False
            return

        row, col = cursor_pos
        target_row = max(0, min(row, total_lines - 1))
        target_col = max(0, col)

        row_delta = target_row - self._hardware_cursor_row
        if row_delta > 0:
            self.term.write(f"\x1b[{row_delta}B")
        elif row_delta < 0:
            self.term.write(f"\x1b[{-row_delta}A")
        self.term.write(f"\x1b[{target_col + 1}G")

        self._hardware_cursor_row = target_row
        if not self._cursor_visible:
            self.term.write(SHOW_CURSOR)
            self._cursor_visible = True

    # -- cursor primitive (module docstring deviation 5) --------------------

    def _move_cursor(self, delta: int) -> None:
        """Move the cursor vertically by ``delta`` rows: down if positive, up
        if negative, no-op if zero. Emitted directly as raw ANSI (not via a
        ``TerminalIO`` method — see module docstring deviation 5)."""
        if delta > 0:
            self.term.write(f"\x1b[{delta}B")
        elif delta < 0:
            self.term.write(f"\x1b[{-delta}A")
