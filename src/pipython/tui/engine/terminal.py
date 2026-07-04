"""Real terminal I/O — Python port of upstream pi's
``packages/tui/src/terminal.ts`` (531 lines full; native-modifiers call sites
skipped per phase-3 spec §5 ruling, see module-level deviation notes below).

Produces (binding, per task-6 brief):

- ``TerminalIO(Protocol)``: ``write(data)`` / ``columns`` / ``rows`` — the
  sole output boundary the rest of the engine writes through; tests inject a
  ``RecordingTerm`` double (Task 7 conftest) instead of this real
  implementation.
- ``RealTerminal(TerminalIO)``: ``start()`` (termios raw mode + Kitty
  keyboard-protocol capability negotiation + bracketed paste), ``stop()``
  (finally-grade restore: termios, kitty/modifyOtherKeys flags popped, cursor
  shown — idempotent, safe from an exception handler or ``atexit``),
  ``kitty_enabled: bool``, ``on_resize(cb)`` (SIGWINCH).
- Cursor primitives: ``move_to_row(delta)``, ``erase_line()``,
  ``hide_cursor()``/``show_cursor()``, backed by the ANSI string constants
  exported alongside the class (``HIDE_CURSOR`` etc.) for reuse by ``tui.py``.
- ``parse_kitty_reply(sequence) -> bool``: pure-function reply classifier,
  directly unit-tested (terminal.ts:23-34 ``parseKeyboardProtocolNegotiationSequence``).

Real-terminal behavior (actual pty interaction) is exercised in the e2e suite
(Task 17) — this module's own tests mock only ``sys.stdin``/``sys.stdout``/
``signal.signal``; termios/tty are the sole allowed *system* mock boundary
project-wide, and in practice this module never calls them with a mocked,
non-integer file descriptor (every termios/tty/select call is guarded so a
non-tty or mocked stdin degrades to "raw mode / Kitty probe skipped" rather
than raising).

Declared deviations from upstream:

1. **Kitty probe is synchronous with a 200ms timeout**, per the task-6
   brief's binding port convention — not upstream's fully async
   ``stdin.on("data", ...)`` pipeline (terminal.ts:220-226). Upstream's own
   ``KEYBOARD_PROTOCOL_RESPONSE_FRAGMENT_TIMEOUT_MS = 150`` (terminal.ts:16)
   governs a *different* sub-case (buffering a split reply that arrives
   across multiple stdin chunks after negotiation has already started), not
   an overall "give up and stop waiting" window — upstream never times out
   the initial probe at all, it just waits indefinitely for input events.
   Since this port's ``start()`` runs synchronously (no event loop wired in
   at this layer), a bounded wait is required to avoid hanging when nothing
   ever answers the probe; the brief fixes that bound at 200ms.
2. **No self-``SIGWINCH`` refresh-kick** (terminal.ts:154-156). Upstream
   re-sends itself ``SIGWINCH`` right after enabling raw mode because Node
   caches nothing dimension-wise but still wants one guaranteed resize
   *event* fired after startup (dimensions can go stale across a
   suspend/resume that swallowed the real signal). This port's
   ``columns``/``rows`` are plain properties recomputed on every access
   (never cached), so there is no staleness to correct, and no test requires
   an initial synthetic resize callback; omitted as unnecessary complexity.
3. **``on_resize(cb)`` registers ``cb`` directly as the raw ``signal.signal``
   handler** (receives ``(signum, frame)``), rather than wrapping it in a
   zero-argument adapter closer to upstream's ``onResize: () => void``. The
   RED test suite's identity-equality assertion
   (``mock_signal.assert_any_call(signal.SIGWINCH, callback)``) requires the
   exact callback object to reach ``signal.signal``, which a wrapper closure
   would break; per this repo's established precedent (see
   ``stdin_buffer.py`` module docstring, "test contract as source of truth"),
   the test shape wins. Callers registering a handler with ``on_resize``
   must accept it being invoked with signal-handler arity.
4. **Cursor visibility folded into ``stop()``** (writes ``SHOW_CURSOR``
   unconditionally on the first ``stop()`` call). Upstream's
   ``ProcessTerminal.stop()`` (terminal.ts:406-452) does not itself restore
   cursor visibility — that is left to app-level shutdown code elsewhere in
   the TS tree. The task-6 brief explicitly folds "show cursor" into this
   port's ``stop()`` contract ("`finally` 级别... 显示光标") so the *one*
   guaranteed-to-run cleanup path (exception handler / ``atexit``) also
   restores cursor visibility, rather than depending on a second call site
   downstream remembering to do it.
5. **``columns``/``rows`` fall back through ``shutil.get_terminal_size()``**
   rather than upstream's literal ``process.stdout.columns || Number(env) ||
   80`` OR-chain. Real ``sys.stdout`` has no ``.columns``/``.rows``
   attributes (that's a Node ``tty.WriteStream`` affordance); the property
   still checks for one first (satisfying the RED tests, which set it
   directly on a mocked ``sys.stdout``), then defers to
   ``shutil.get_terminal_size(fallback=(80, 24))`` — which itself already
   layers ``COLUMNS``/``LINES`` env override, then a real ``ioctl`` query,
   then the ``(80, 24)`` fallback, matching upstream's intent through the
   idiomatic Python API instead of hand-rolling the same OR-chain.
6. **``drainInput``/``setTitle``/``setProgress``/``clearScreen``/
   ``clearFromCursor``/Windows VT-input enabling are not ported.** The
   task-6 brief's Produces list is exhaustive for this task (``TerminalIO``,
   ``start``/``stop``/``kitty_enabled``/``on_resize``, and the four cursor
   primitives) — these upstream members are out of scope here, not omitted
   by oversight.
"""

from __future__ import annotations

import atexit
import os
import re
import select
import shutil
import signal
import sys
import termios
import time
import tty
from types import FrameType
from typing import Any, Callable, Protocol

__all__ = [
    "TerminalIO",
    "RealTerminal",
    "parse_kitty_reply",
    "KITTY_QUERY_SEQUENCE",
    "BRACKETED_PASTE_ENABLE",
    "BRACKETED_PASTE_DISABLE",
    "KITTY_PROTOCOL_DISABLE",
    "MODIFY_OTHER_KEYS_ENABLE",
    "MODIFY_OTHER_KEYS_DISABLE",
    "HIDE_CURSOR",
    "SHOW_CURSOR",
    "CLEAR_LINE",
]


# =============================================================================
# ANSI constants (terminal.ts:15-17, 147, 374/412/419, 322/328, 485/489/493)
# =============================================================================

_DESIRED_KITTY_KEYBOARD_PROTOCOL_FLAGS = 7  # 1|2|4, terminal.ts:15
KITTY_QUERY_SEQUENCE = (
    f"\x1b[>{_DESIRED_KITTY_KEYBOARD_PROTOCOL_FLAGS}u\x1b[?u\x1b[c"  # terminal.ts:17
)
BRACKETED_PASTE_ENABLE = "\x1b[?2004h"  # terminal.ts:147
BRACKETED_PASTE_DISABLE = "\x1b[?2004l"  # terminal.ts:412
KITTY_PROTOCOL_DISABLE = "\x1b[<u"  # terminal.ts:374, 419
MODIFY_OTHER_KEYS_ENABLE = "\x1b[>4;2m"  # terminal.ts:322
MODIFY_OTHER_KEYS_DISABLE = "\x1b[>4;0m"  # terminal.ts:328
HIDE_CURSOR = "\x1b[?25l"  # terminal.ts:485
SHOW_CURSOR = "\x1b[?25h"  # terminal.ts:489
CLEAR_LINE = "\x1b[K"  # terminal.ts:493

# See deviation 1: 200ms per the task-6 brief's binding port convention, not
# upstream's 150ms fragment-buffering constant (terminal.ts:16).
_KITTY_PROBE_TIMEOUT_S = 0.2
_KITTY_PROBE_MAX_BUFFER = 64


# =============================================================================
# Kitty/DA negotiation-reply parsing (terminal.ts:23-34)
# =============================================================================

_KITTY_FLAGS_RE = re.compile(r"^\x1b\[\?(\d+)u$")
_DEVICE_ATTRS_RE = re.compile(r"^\x1b\[\?[\d;]*c$")


def _parse_negotiation_sequence(sequence: str) -> tuple[str, int] | None:
    """terminal.ts:23-34 ``parseKeyboardProtocolNegotiationSequence``.

    Returns ``("kitty-flags", flags)`` or ``("device-attributes", 0)``, or
    ``None`` if ``sequence`` isn't a recognized negotiation reply.
    """
    kitty_flags = _KITTY_FLAGS_RE.match(sequence)
    if kitty_flags:
        return ("kitty-flags", int(kitty_flags.group(1)))
    if _DEVICE_ATTRS_RE.match(sequence):
        return ("device-attributes", 0)
    return None


def parse_kitty_reply(sequence: str) -> bool:
    """``True`` if ``sequence`` is a recognized Kitty-flags or
    device-attributes negotiation reply (terminal.ts:23-34), ``False``
    otherwise (including empty/partial/garbage input)."""
    return _parse_negotiation_sequence(sequence) is not None


# =============================================================================
# TerminalIO protocol
# =============================================================================


class TerminalIO(Protocol):
    """Minimal terminal output boundary — the engine writes through this
    exclusively so tests can inject a recording double instead of a real
    terminal (see Task 7 conftest's ``RecordingTerm``)."""

    def write(self, data: str) -> None: ...

    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...


_ResizeHandler = Callable[[int, "FrameType | None"], object]


class RealTerminal(TerminalIO):
    """Real ``sys.stdin``/``sys.stdout``-backed terminal: raw mode, Kitty
    keyboard-protocol negotiation, and the ANSI output boundary.

    See the module docstring for the full list of declared deviations from
    upstream ``ProcessTerminal`` (terminal.ts:99-531).
    """

    def __init__(self) -> None:
        self.kitty_enabled = False
        self._started = False
        self._stopped = True
        self._protocol_query_sent = False
        self._modify_other_keys_active = False
        self._raw_fd: int | None = None
        self._saved_termios: Any | None = None
        self._resize_handler: _ResizeHandler | None = None

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        """Enter raw mode, enable bracketed paste, and negotiate the Kitty
        keyboard protocol (terminal.ts:134-166, ``start``)."""
        if self._started:
            return
        self._started = True
        self._stopped = False

        self._enter_raw_mode()

        self.write(BRACKETED_PASTE_ENABLE)  # terminal.ts:147

        self._protocol_query_sent = True
        self.write(KITTY_QUERY_SEQUENCE)  # terminal.ts:225

        self._negotiate_kitty_protocol()

        # Restore guarantee (deviation: atexit backstop only makes sense —
        # and only avoids stray writes to an unrelated real stdout in
        # tests — once we actually engaged real terminal state).
        if self._raw_fd is not None:
            atexit.register(self.stop)

    def stop(self) -> None:
        """Finally-grade restore: bracketed paste, Kitty/modifyOtherKeys
        flags, termios raw mode, and cursor visibility. Idempotent — safe to
        call from an exception handler or twice in a row (terminal.ts:406-452,
        plus the task-6 brief's cursor-show addition, see deviation 4)."""
        if self._stopped:
            return
        self._stopped = True

        self.write(BRACKETED_PASTE_DISABLE)  # terminal.ts:412

        if self._protocol_query_sent or self.kitty_enabled:
            self.write(KITTY_PROTOCOL_DISABLE)  # terminal.ts:374, 419
            self.kitty_enabled = False
            self._protocol_query_sent = False

        self._disable_modify_other_keys()

        self._restore_raw_mode()

        self.write(SHOW_CURSOR)

        atexit.unregister(self.stop)

    # -- TerminalIO ------------------------------------------------------

    def write(self, data: str) -> None:
        sys.stdout.write(data)

    @property
    def columns(self) -> int:
        return self._dimension("columns", shutil.get_terminal_size(fallback=(80, 24)).columns)

    @property
    def rows(self) -> int:
        return self._dimension("rows", shutil.get_terminal_size(fallback=(80, 24)).lines)

    def _dimension(self, attr: str, fallback: int) -> int:
        value = getattr(sys.stdout, attr, None)
        if not value:
            return fallback
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    # -- resize (terminal.ts:150, ``process.stdout.on("resize", ...)``) --

    def on_resize(self, cb: _ResizeHandler) -> None:
        """Register ``cb`` for SIGWINCH. ``cb`` is installed directly as the
        raw signal handler (receives ``(signum, frame)``) — see module
        docstring deviation 3."""
        self._resize_handler = cb
        signal.signal(signal.SIGWINCH, cb)

    # -- cursor primitives (terminal.ts:473-494) --------------------------

    def move_to_row(self, delta: int) -> None:
        """Move the cursor up (``delta < 0``) or down (``delta > 0``) by
        ``abs(delta)`` lines; ``delta == 0`` is a no-op (terminal.ts:473-482
        ``moveBy``)."""
        if delta > 0:
            self.write(f"\x1b[{delta}B")
        elif delta < 0:
            self.write(f"\x1b[{-delta}A")

    def erase_line(self) -> None:
        self.write(CLEAR_LINE)

    def hide_cursor(self) -> None:
        self.write(HIDE_CURSOR)

    def show_cursor(self) -> None:
        self.write(SHOW_CURSOR)

    # -- raw mode (termios/tty — the only allowed system mock boundary) --

    def _enter_raw_mode(self) -> None:
        """terminal.ts:139-141 (save ``isRaw`` state, ``setRawMode(true)``).

        Guarded end-to-end: a non-tty or mocked ``stdin`` (this module's own
        tests patch ``sys.stdin`` wholesale, giving a non-integer
        ``fileno()``) degrades to "raw mode skipped" rather than raising —
        real-terminal raw-mode behavior is covered by the e2e suite (Task 17).
        """
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return
        if not isinstance(fd, int):
            return
        try:
            self._saved_termios = termios.tcgetattr(fd)
            tty.setraw(fd)
        except (termios.error, OSError, ValueError):
            self._saved_termios = None
            return
        self._raw_fd = fd

    def _restore_raw_mode(self) -> None:
        """terminal.ts:449-451 (restore ``wasRaw`` state)."""
        if self._raw_fd is None or self._saved_termios is None:
            return
        try:
            termios.tcsetattr(self._raw_fd, termios.TCSADRAIN, self._saved_termios)
        except (termios.error, OSError, ValueError):
            pass
        finally:
            self._raw_fd = None
            self._saved_termios = None

    # -- Kitty / modifyOtherKeys negotiation (terminal.ts:207-330) --------

    def _negotiate_kitty_protocol(self) -> None:
        """Read the Kitty/DA reply (bounded by ``_KITTY_PROBE_TIMEOUT_S``,
        see module docstring deviation 1) and apply
        ``handleKeyboardProtocolNegotiationSequence`` (terminal.ts:228-250).
        No reply within the timeout leaves both ``kitty_enabled`` and the
        modifyOtherKeys fallback untouched, matching upstream's own
        do-nothing-until-a-reply-arrives behavior.
        """
        negotiation = self._read_negotiation_reply(_KITTY_PROBE_TIMEOUT_S)
        if negotiation is None:
            return
        kind, flags = negotiation
        if kind == "kitty-flags" and flags != 0:
            self.kitty_enabled = True
            return
        self._enable_modify_other_keys()

    def _read_negotiation_reply(self, timeout_s: float) -> tuple[str, int] | None:
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return None
        if not isinstance(fd, int):
            return None

        deadline = time.monotonic() + timeout_s
        buffer = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                ready, _, _ = select.select([fd], [], [], remaining)
            except (OSError, ValueError, TypeError):
                return None
            if not ready:
                return None
            try:
                chunk = os.read(fd, 64)
            except OSError:
                return None
            if not chunk:
                return None
            buffer += chunk.decode("utf-8", errors="ignore")

            negotiation = _parse_negotiation_sequence(buffer)
            if negotiation is not None:
                return negotiation
            if len(buffer) > _KITTY_PROBE_MAX_BUFFER:
                return None

    def _enable_modify_other_keys(self) -> None:
        """terminal.ts:320-324."""
        if self.kitty_enabled or self._modify_other_keys_active:
            return
        self.write(MODIFY_OTHER_KEYS_ENABLE)
        self._modify_other_keys_active = True

    def _disable_modify_other_keys(self) -> None:
        """terminal.ts:326-330."""
        if not self._modify_other_keys_active:
            return
        self.write(MODIFY_OTHER_KEYS_DISABLE)
        self._modify_other_keys_active = False
