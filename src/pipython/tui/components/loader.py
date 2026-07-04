"""Loader component — Python port of upstream pi's
``packages/tui/src/components/loader.ts`` (92 lines), reshaped to task-9
brief's simplified interface:
``Loader(tui_request_render: Callable, frames: list[str] | None = None,
interval: float = 0.08)``.

Upstream's ``Loader extends Text`` and takes a whole ``ui: TUI`` instance
plus separate spinner-color/message-color callback functions and a mutable
``message`` (loader.ts:17-41) — this port takes just the one callable it
actually needs (``ui.requestRender`` narrowed to its own parameter, per the
task-9 brief's Produces list) and drops the color/message machinery
entirely (no RED test exercises ``setMessage``/color styling; task-9's
Produces list has no message parameter at all). Default frames/interval are
ported verbatim (loader.ts:11-12): the braille spinner
``["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]`` at 80ms — expressed here as
seconds (``0.08``) per the brief's own ``interval: float`` unit.

Deviations from upstream loader.ts:

1. Does not extend ``Text`` (loader.ts:17 ``class Loader extends Text``) —
   composition instead of inheritance: this port's ``Loader`` implements
   ``Component`` directly rather than pulling in this port's simplified
   ``Text`` (task-9's own ``text.py``, which itself dropped the
   padding/background machinery ``Loader``'s superclass call relied on,
   loader.ts:35 ``super("", 1, 0)``). Nothing in the task-9 brief's Produces
   list requires word-wrapping (a spinner+message is always one line), so
   there is no wrapping behavior to reuse from ``Text`` here anyway.
2. No real ``setInterval``/timer thread. Per the task-9 brief's port
   convention ("spinner 帧推进靠注入的 request_render（测试手动步进，不真
   sleep）"), frame advancement is exposed as an explicit, synchronously
   callable seam — ``tick()`` — rather than upstream's self-driving
   ``setInterval`` callback (loader.ts:77-81). ``start()``/``stop()`` do
   schedule ``tick()`` via ``asyncio.loop.call_later`` *when a running event
   loop is present* (mirroring Task 7's ``TUI.request_render`` degrade
   pattern in ``engine/tui.py``, whose own docstring deviation 6 documents
   the same no-loop-available fallback), so real usage inside the actual TUI
   app still animates on its own — but with no event loop running (as in
   every RED test in ``test_basic_components.py``, all plain synchronous
   functions), no timer is ever created, and tests drive animation
   exclusively via direct ``tick()`` calls, with no real sleep anywhere.
3. No ``message``/color-callback/``setMessage``/``setIndicator`` API
   (loader.ts:23-26, 32-33, 39, 59-70, 83-91) — outside the task-9 brief's
   Produces list; ``render()`` emits the frame indicator alone.
4. Empty ``frames`` list renders one blank line rather than upstream's
   "indicator-less message line" (loader.ts:84-87's ``indicator = frame.
   length > 0 ? ... : ""`` still has ``message`` text to fall back on) —
   this port has no message text to fall back on (deviation 3), so nothing
   is left to render but blank.
"""

from __future__ import annotations

import asyncio
from typing import Callable

__all__ = ["Loader"]

DEFAULT_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
DEFAULT_INTERVAL = 0.08


class Loader:
    """tui.ts ``Component``-compatible: a single-line animated spinner whose
    frame advancement is driven either by a real event-loop timer (when one
    is running) or by manually calling ``tick()`` (module docstring
    deviation 2)."""

    def __init__(
        self,
        tui_request_render: Callable[[], None],
        frames: list[str] | None = None,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self._request_render = tui_request_render
        self.frames = list(frames) if frames is not None else list(DEFAULT_FRAMES)
        self.interval = interval
        self.current_frame = 0
        self._running = False
        self._handle: asyncio.TimerHandle | None = None

    def start(self) -> None:
        """loader.ts:47-50 ``start()``: render immediately, then (re)arm
        animation (module docstring deviation 2 — real scheduling only when
        a loop is running; otherwise this is a no-op beyond the flag/render,
        exactly matching the brief's "no real sleeps in tests" convention)."""
        self._running = True
        self._request_render()
        self._schedule_next()

    def stop(self) -> None:
        """loader.ts:52-57 ``stop()``: cancel any pending scheduled tick."""
        self._running = False
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def tick(self) -> None:
        """Advance one animation frame and request a render — the manual
        seam the task-9 brief calls for (loader.ts:77-80's
        ``setInterval`` callback body, minus the timer itself). Safe to call
        whether or not ``start()`` was ever called; a no-op with zero
        frames."""
        if not self.frames:
            return
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self._request_render()

    def _schedule_next(self) -> None:
        """loader.ts:72-81 ``restartAnimation()``, narrowed to schedule a
        single next ``tick()`` (re-armed from ``_on_timer`` below) rather
        than upstream's self-repeating ``setInterval`` — only when a running
        asyncio loop exists (module docstring deviation 2); single-or-fewer
        frames never animate (loader.ts:74-76)."""
        if not self._running or len(self.frames) <= 1:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._handle = loop.call_later(self.interval, self._on_timer)

    def _on_timer(self) -> None:
        self.tick()
        self._schedule_next()

    def invalidate(self) -> None:
        """No cached render state to invalidate."""

    def render(self, width: int) -> list[str]:
        """loader.ts:43-45's ``render()`` plus 83-87's ``updateDisplay()``
        frame-formatting, collapsed into one line (no leading blank line —
        upstream's own leading ``""`` in ``["", ...super.render(width)]`` is
        an artifact of ``Text``'s ``paddingY=0``-but-still-``Loader``-adds-
        one-blank-line-itself quirk this port's simplified, non-``Text``-
        based ``Loader`` has no reason to reproduce; see module docstring
        deviation 1)."""
        if not self.frames:
            return [""]
        frame = self.frames[self.current_frame]
        return [f"{frame} " if frame else ""]
