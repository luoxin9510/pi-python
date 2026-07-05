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
(Task 17). This module's own tests mock at the real system boundary —
``termios.tcgetattr``/``tcsetattr``, ``tty.setraw``, ``select.select``,
``os.read``, ``signal.signal``, ``sys.stdout`` — plus ``sys.stdin`` replaced
with a minimal stub whose ``fileno()`` returns a real ``int`` (e.g. ``0``),
*not* a blanket ``MagicMock`` (whose mocked ``fileno()`` would return another
``MagicMock``, tripping the ``isinstance(fd, int)`` guards below and
short-circuiting before termios/tty/select/os.read ever run — the RED
mistake fixed in fix round 1). Every termios/tty/select/read call is still
guarded so a genuinely non-tty stdin (no ``fileno()``, or ``fileno()``
raising) degrades to "raw mode / Kitty probe skipped" rather than raising.

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

   **Fix round 1 addition:** unlike upstream — which only ever applies the
   modifyOtherKeys fallback on an *actual* negative reply (DA, or
   kitty-flags with ``flags == 0``) — this port also applies the fallback
   when the probe ends with **no classifiable reply at all** (timeout,
   select/read error, or the max-buffer cap hit with only garbage). A
   synchronous, bounded probe cannot distinguish "this terminal will never
   answer" from "this terminal is just slow"; since the risk of a spurious
   ``\x1b[>4;2m`` write to a Kitty-capable terminal (expected to be
   ignored/superseded) is far cheaper than silently leaving *no* protocol
   negotiated at all, ``_negotiate_kitty_protocol`` treats every
   non-``kitty-flags`` outcome — including ``None`` — as "apply the
   fallback".

   **Fix round 2 disclosure:** the 200ms budget above is a genuine race
   against network/pty latency, not just a "give up" backstop — if a
   negotiation reply (Kitty-flags or DA) arrives after the deadline (RTT >
   200ms: a slow pty, a loaded remote SSH hop, etc.), it will **not** be
   recognized as a negotiation reply at all; it surfaces downstream as
   ordinary — and unparseable — input bytes once Task 16/17 wires
   ``drain_pending()``'s output (or subsequent live stdin) into the input
   pipeline. Upstream never has this failure mode: its negotiation filter is
   a resident ``stdinBuffer`` listener with no deadline, so a late reply is
   still recognized and swallowed whenever it eventually arrives
   (terminal.ts:181-330). This port's synchronous, bounded probe has no such
   persistent filter after it returns — Task 16/17 should be aware a
   slow-answering terminal can leak escape-sequence garbage into the very
   first real keystrokes it processes.
2. **No self-``SIGWINCH`` refresh-kick** (terminal.ts:154-156). Upstream
   re-sends itself ``SIGWINCH`` right after enabling raw mode because Node
   caches nothing dimension-wise but still wants one guaranteed resize
   *event* fired after startup (dimensions can go stale across a
   suspend/resume that swallowed the real signal). This port's
   ``columns``/``rows`` are plain properties recomputed on every access
   (never cached), so there is no staleness to correct, and no test requires
   an initial synthetic resize callback; omitted as unnecessary complexity.
3. **Cursor visibility folded into ``stop()``** (writes ``SHOW_CURSOR``
   unconditionally on the first ``stop()`` call). Upstream's
   ``ProcessTerminal.stop()`` (terminal.ts:406-452) does not itself restore
   cursor visibility — that is left to app-level shutdown code elsewhere in
   the TS tree. The task-6 brief explicitly folds "show cursor" into this
   port's ``stop()`` contract ("`finally` 级别... 显示光标") so the *one*
   guaranteed-to-run cleanup path (exception handler / ``atexit``) also
   restores cursor visibility, rather than depending on a second call site
   downstream remembering to do it.
4. **``columns``/``rows`` fall back through ``shutil.get_terminal_size()``**
   rather than upstream's literal ``process.stdout.columns || Number(env) ||
   80`` OR-chain. Real ``sys.stdout`` has no ``.columns``/``.rows``
   attributes (that's a Node ``tty.WriteStream`` affordance); the property
   still checks for one first (satisfying the RED tests, which set it
   directly on a mocked ``sys.stdout``), then defers to
   ``shutil.get_terminal_size(fallback=(80, 24))`` — which itself already
   layers ``COLUMNS``/``LINES`` env override, then a real ``ioctl`` query,
   then the ``(80, 24)`` fallback, matching upstream's intent through the
   idiomatic Python API instead of hand-rolling the same OR-chain.
5. **``drainInput``/``setTitle``/``setProgress``/``clearScreen``/
   ``clearFromCursor``/Windows VT-input enabling are not ported.** The
   task-6 brief's Produces list is exhaustive for this task (``TerminalIO``,
   ``start``/``stop``/``kitty_enabled``/``on_resize``, and the four cursor
   primitives) — these upstream members are out of scope here, not omitted
   by oversight.
6. **Kitty-probe typeahead bytes are preserved via a pull-based
   ``drain_pending()``, not upstream's push-based forwarding.** Upstream
   never drops a byte during negotiation: every chunk that isn't a
   recognized negotiation reply is forwarded immediately to ``inputHandler``
   (terminal.ts:181-318, ``forwardInputSequence`` / the "pending" buffering
   in ``readKeyboardProtocolNegotiationSequence``). This port's probe is a
   blocking, synchronous ``select``/``os.read`` loop with no input-handler
   callback wired in yet, so it cannot forward bytes as they arrive; instead
   it accumulates every byte that isn't part of a matched reply — found by
   *searching* the growing buffer for the reply pattern anywhere (not
   requiring the whole buffer to be the reply) and excising just that match
   — into ``self._pending_input``, drained via ``drain_pending() -> bytes``.
   **Task 16 MUST call ``drain_pending()`` and feed the result into
   ``StdinBuffer.feed()`` before attaching ``loop.add_reader(fd, ...)``** —
   any bytes returned here arrived on stdin *before* the async reader took
   over and would otherwise be silently lost (typed-ahead keystrokes eaten,
   or worse, a reply-plus-typeahead chunk producing a false-negative Kitty
   detection because the reply pattern wasn't anchored to the whole buffer).

   **Fix round 2 addition:** the initial cut of this probe returned as soon
   as *any* negotiation reply was found — including a bare Kitty-flags
   reply — leaving the trailing DA reply (guaranteed by
   ``KITTY_QUERY_SEQUENCE``'s own ``\x1b[c`` suffix) unconsumed on every
   Kitty-capable terminal, to be read later as ordinary input bytes.
   ``_read_negotiation_reply`` now treats the DA reply as the probe's
   universal terminator (matching upstream, terminal.ts:246-249): a
   Kitty-flags reply is recorded but does not end the read; the read keeps
   going, within the same 200ms budget, until DA is also found and excised.
   Residual case: if DA never arrives before the deadline, ``kitty_enabled``
   still latches ``True`` off the Kitty-flags reply alone, and everything
   accumulated so far is preserved via ``drain_pending()`` rather than
   silently discarded.
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
    "ResizeCallback",
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

# Unanchored byte-string counterparts of the two patterns above, used by
# ``_find_negotiation_reply`` to *search* a raw, possibly typeahead-polluted
# stdin buffer for a reply anywhere within it (see module docstring
# deviation 6) rather than requiring the whole buffer to be the reply.
_KITTY_FLAGS_SEARCH_RE = re.compile(rb"\x1b\[\?(\d+)u")
_DEVICE_ATTRS_SEARCH_RE = re.compile(rb"\x1b\[\?[\d;]*c")


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


def _find_negotiation_reply(buffer: bytes) -> tuple[tuple[str, int], bytes] | None:
    """Search ``buffer`` *anywhere* for a Kitty-flags or device-attributes
    negotiation reply and excise just the matched span, per upstream's
    non-lossy forwarding semantics (terminal.ts:181-318) — unlike
    ``_parse_negotiation_sequence`` (which classifies an already-isolated,
    fully-matched sequence), this tolerates typed-ahead bytes before and/or
    after the reply within the same chunk.

    Returns ``(("kitty-flags", flags) | ("device-attributes", 0), leftover)``
    where ``leftover`` is every byte of ``buffer`` outside the matched reply
    (both the prefix and suffix, concatenated) — the caller preserves this
    via ``RealTerminal._pending_input`` / ``drain_pending()`` rather than
    discarding it. ``None`` if no reply pattern is found anywhere yet.
    """
    match = _KITTY_FLAGS_SEARCH_RE.search(buffer)
    if match:
        flags = int(match.group(1))
        leftover = buffer[: match.start()] + buffer[match.end() :]
        return ("kitty-flags", flags), leftover
    match = _DEVICE_ATTRS_SEARCH_RE.search(buffer)
    if match:
        leftover = buffer[: match.start()] + buffer[match.end() :]
        return ("device-attributes", 0), leftover
    return None


# =============================================================================
# TerminalIO protocol
# =============================================================================


class TerminalIO(Protocol):
    """Minimal terminal output boundary — the engine writes through this
    exclusively so tests can inject a recording double instead of a real
    terminal (see Task 7 conftest's ``RecordingTerm``).

    ``flush()`` (Task 17 review, Important 1) is deliberately *not* a formal
    member of this Protocol, even though ``RealTerminal`` implements one
    (below) and ``TUI.do_render`` calls it once per frame. Same rationale as
    ``tui.py`` module docstring deviation 9's ``Component.handle_input``:
    Python's ``typing.Protocol`` has no notion of a genuinely *optional*
    structural member — declaring ``flush`` here would make every
    ``TerminalIO`` double statically required to implement it (this was
    tried and reverted: it broke a minimal write-only test double with a
    ``reportArgumentType`` error, since Protocol conformance is all-or-
    nothing per member). Callers that want to flush therefore probe for it
    dynamically — ``getattr(term, "flush", None)`` + ``callable(...)``,
    exactly like ``Focusable`` is probed via ``is_focusable`` and
    ``handle_input`` via ``TUI.handle_input`` — rather than calling it
    unconditionally. See ``TUI._flush_term``."""

    def write(self, data: str) -> None: ...

    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...


# Public callback shape for on_resize — upstream's `onResize: () => void`
# (terminal.ts:150). Zero-arg by design; see on_resize()'s docstring.
ResizeCallback = Callable[[], None]

# Internal: the raw signal.signal handler shape ((signum, frame) -> Any)
# that ResizeCallback gets wrapped in before reaching signal.signal.
_RawSignalHandler = Callable[[int, "FrameType | None"], object]


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
        self._resize_handler: _RawSignalHandler | None = None
        self._pending_input: bytes = b""

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
        # Inline flush (Task 17 review, Important 2): this write is not
        # frame-driven — nothing downstream of start() triggers a do_render
        # flush on our behalf — and the Kitty query right below depends on
        # the terminal having actually *seen* prior writes before its reply
        # can arrive within the 200ms negotiation window (deviation 1).
        self.flush()

        # Restore guarantee, registered unconditionally right after the
        # first state-mutating write: bracketed paste (and the Kitty query
        # right below) happen regardless of whether raw-mode entry itself
        # succeeded, so the "finally"-grade restore must be armed
        # regardless too — gating this on `_raw_fd is not None` would leave
        # bracketed paste / the Kitty push enabled forever on a non-tty
        # stdin (fd lookup or termios failed) if the process exits without
        # an explicit stop(). stop() is already idempotent and safe to call
        # even when raw mode never engaged.
        atexit.register(self.stop)

        self._protocol_query_sent = True
        self.write(KITTY_QUERY_SEQUENCE)  # terminal.ts:225
        self.flush()  # see above — must reach the terminal before we read

        self._negotiate_kitty_protocol()

    def stop(self) -> None:
        """Finally-grade restore: bracketed paste, Kitty/modifyOtherKeys
        flags, termios raw mode, and cursor visibility. Idempotent — safe to
        call from an exception handler or twice in a row (terminal.ts:406-452,
        plus the task-6 brief's cursor-show addition, see deviation 3).

        Resets ``_started`` so a subsequent ``start()`` call re-enters raw
        mode and re-negotiates Kitty from scratch (upstream's terminal is
        likewise restartable — nothing in ``ProcessTerminal`` latches
        "already started" permanently)."""
        if self._stopped:
            return
        self._stopped = True
        self._started = False

        self.write(BRACKETED_PASTE_DISABLE)  # terminal.ts:412
        # Inline flush (Task 17 review, Important 2): stop()'s restore path
        # is not frame-driven either — there is no subsequent do_render to
        # flush on this call's behalf, and the process may exit immediately
        # after stop() returns, so every restore write must reach the
        # terminal before that happens rather than sit in Python's stdout
        # buffer.
        self.flush()

        if self._protocol_query_sent or self.kitty_enabled:
            self.write(KITTY_PROTOCOL_DISABLE)  # terminal.ts:374, 419
            self.flush()
            self.kitty_enabled = False
            self._protocol_query_sent = False

        self._disable_modify_other_keys()

        self._restore_raw_mode()

        self.write(SHOW_CURSOR)
        self.flush()

        atexit.unregister(self.stop)

    # -- TerminalIO ------------------------------------------------------

    def write(self, data: str) -> None:
        sys.stdout.write(data)

    def flush(self) -> None:
        """Flush ``sys.stdout`` (Task 17 review, Important 1 — fix round 2).

        Python's stdout on a real tty is line-buffered: a frame's bytes only
        reach the terminal if the frame happens to contain ``"\\n"``. Node's
        ``process.stdout.write`` (upstream terminal.ts:455) has no such
        buffering, so upstream never needs an explicit flush at all — but a
        newline-less diff-only frame (plain keystroke echo, or a
        shrink-only "[interrupted]" frame) would otherwise sit unflushed
        until some later frame happens to carry a newline, or the process
        exits. See ``.superpowers/sdd/task-17-report.md`` "Task 17
        (resumed)" for the real-tmux e2e evidence this was diagnosed from.

        Fix round 2 correction: the first fix flushed inside ``write()``
        itself — once per ``sys.stdout.write()`` call. That is the *wrong*
        granularity for this port specifically: ``tui.py``'s ``do_render``
        deliberately issues one discrete ``term.write()`` per atomic ANSI
        primitive (cursor move, carriage return, line erase, text chunk —
        ``tui.py`` module docstring deviation 5), unlike upstream, which
        accumulates one buffer string per frame and writes it once
        (``this.terminal.write(buffer)``). A prior justification note
        (``.superpowers/sdd/task-17-report.md``'s original "Suggested fix")
        claimed "upstream's single-buffer-per-frame write makes per-write
        equivalent to per-frame anyway" — that claim does not hold for
        *this* port: because of deviation 5's discrete writes, flushing
        inside ``write()`` itself means N flushes per rendered frame (N =
        however many atomic ANSI ops that frame happened to emit), not one.
        The architecturally correct granularity is a single flush at the end
        of each ``do_render`` call (see ``tui.py``'s ``do_render``, which
        now calls ``term.flush()`` once after cursor positioning) — this
        method exists so callers (``do_render``, and this class's own
        ``start()``/``stop()``) can request that flush explicitly, on their
        own schedule, instead of ``write()`` doing it unconditionally on
        every call.

        ``start()``'s negotiation writes and ``stop()``'s restore writes are
        the two exceptions that still flush inline, immediately after each
        write (Task 17 review, Important 2): neither is frame-driven — there
        is no subsequent ``do_render`` call whose end-of-frame flush would
        otherwise cover them — and both have a real timing requirement of
        their own (the 200ms Kitty negotiation window; restore writes that
        must reach the terminal before the process exits).
        """
        sys.stdout.flush()

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

    def on_resize(self, cb: ResizeCallback) -> None:
        """Register ``cb`` — an upstream-shaped zero-arg
        ``Callable[[], None]`` (``onResize: () => void``, terminal.ts:150)
        — to run on every SIGWINCH. ``cb`` is wrapped in a signal-arity
        adapter internally (``lambda signum, frame: cb()``) so callers never
        need to accept ``(signum, frame)`` themselves.

        WARNING — SIGWINCH is a single, process-wide slot: this method
        claims it via ``signal.signal`` directly. The app layer must NOT
        *also* register SIGWINCH through ``asyncio``'s
        ``loop.add_signal_handler(signal.SIGWINCH, ...)`` — whichever
        registration runs last silently clobbers the other with no error
        (see Task 8/16 wiring notes). Resize must be wired through
        ``on_resize`` only.
        """

        def _handler(signum: int, frame: FrameType | None) -> None:
            cb()

        self._resize_handler = _handler
        signal.signal(signal.SIGWINCH, _handler)

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

        Guarded end-to-end: a stdin with no ``fileno()``, a ``fileno()`` that
        raises, or a non-``int`` ``fileno()`` result all degrade to "raw mode
        skipped" rather than raising — real-terminal raw-mode behavior is
        covered by the e2e suite (Task 17).
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

        Any outcome other than a *positive* Kitty-flags reply
        (``flags != 0``) — including a negative reply (DA, or kitty-flags
        with ``flags == 0``) *and* getting no classifiable reply at all
        (timeout / select or read error / garbage that never resolves) —
        applies the modifyOtherKeys fallback. See module docstring
        deviation 1's "Fix round 1 addition" for why the no-reply case is
        folded into the fallback here rather than left untouched.
        """
        negotiation = self._read_negotiation_reply(_KITTY_PROBE_TIMEOUT_S)
        if negotiation is not None:
            kind, flags = negotiation
            if kind == "kitty-flags" and flags != 0:
                self.kitty_enabled = True
                return
        self._enable_modify_other_keys()

    def _read_negotiation_reply(self, timeout_s: float) -> tuple[str, int] | None:
        """Synchronously read stdin until the probe is *terminated* or
        ``timeout_s`` elapses, *without dropping any other byte* seen along
        the way (typed-ahead keystrokes, or a reply-plus-typeahead chunk) —
        ported from upstream's non-lossy forwarding semantics
        (terminal.ts:181-318), see module docstring deviation 6.

        Since ``KITTY_QUERY_SEQUENCE`` always ends with the primary Device
        Attributes query (``\\x1b[c``), *every* terminal — Kitty-capable or
        not — answers with a DA reply. Upstream treats that DA reply as the
        probe's universal terminator: both a Kitty-flags reply *and* the DA
        reply that follows it get consumed before upstream stops watching
        for negotiation sequences (terminal.ts:246-249). This port mirrors
        that: finding a Kitty-flags reply does **not** return immediately —
        it is recorded, and the read keeps going (within the same
        ``timeout_s`` budget) until the DA reply is also found and excised.
        Only a DA reply — whether or not a Kitty-flags reply preceded it —
        actually ends the probe. See module docstring deviation 6's "Fix
        round 2" note for the one residual case this can't close: a
        Kitty-flags reply followed by a DA reply that never arrives before
        the deadline.

        Every exit path funnels leftover/non-reply bytes into
        ``self._pending_input`` (drained via ``drain_pending()``) instead of
        discarding them: a found reply excises just its own span (keeping
        the surrounding bytes), and a timeout/error/overflow keeps the
        *entire* accumulated buffer.
        """
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return None
        if not isinstance(fd, int):
            return None

        deadline = time.monotonic() + timeout_s
        buffer = b""
        # Set once a Kitty-flags reply is found; the read keeps going past
        # that point (same deadline) looking for the trailing DA reply that
        # terminates the probe — see the docstring above.
        kitty_result: tuple[str, int] | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._pending_input += buffer
                return kitty_result
            try:
                ready, _, _ = select.select([fd], [], [], remaining)
            except (OSError, ValueError, TypeError):
                self._pending_input += buffer
                return kitty_result
            if not ready:
                self._pending_input += buffer
                return kitty_result
            try:
                chunk = os.read(fd, 64)
            except OSError:
                self._pending_input += buffer
                return kitty_result
            if not chunk:
                self._pending_input += buffer
                return kitty_result
            buffer += chunk

            while True:
                found = _find_negotiation_reply(buffer)
                if found is None:
                    break
                negotiation, buffer = found
                if negotiation[0] == "device-attributes":
                    self._pending_input += buffer
                    return kitty_result if kitty_result is not None else negotiation
                # Kitty-flags reply: record (first one wins) and keep
                # searching the same buffer — a same-chunk DA reply must
                # still be excised before this method returns.
                if kitty_result is None:
                    kitty_result = negotiation

            if len(buffer) > _KITTY_PROBE_MAX_BUFFER:
                self._pending_input += buffer
                return kitty_result

    def drain_pending(self) -> bytes:
        """Return and clear bytes collected during Kitty negotiation that
        were not part of the negotiation reply itself — typed-ahead
        keystrokes, unrecognized garbage, or a timed-out/overflowed probe's
        raw buffer (see module docstring deviation 6).

        **Task 16 MUST call this and feed the result into
        ``StdinBuffer.feed()`` before attaching ``loop.add_reader(fd,
        ...)``** — any bytes returned here arrived on stdin before the
        async reader took over and would otherwise be silently lost.
        """
        pending, self._pending_input = self._pending_input, b""
        return pending

    def _enable_modify_other_keys(self) -> None:
        """terminal.ts:320-324. Called only from ``start()``'s negotiation
        path (via ``_negotiate_kitty_protocol``), so this write flushes
        inline too — see ``start()``'s own comment: nothing frame-driven
        follows it to flush on its behalf."""
        if self.kitty_enabled or self._modify_other_keys_active:
            return
        self.write(MODIFY_OTHER_KEYS_ENABLE)
        self.flush()
        self._modify_other_keys_active = True

    def _disable_modify_other_keys(self) -> None:
        """terminal.ts:326-330. Called only from ``stop()``'s restore path,
        so this write flushes inline too — see ``stop()``'s own comment."""
        if not self._modify_other_keys_active:
            return
        self.write(MODIFY_OTHER_KEYS_DISABLE)
        self.flush()
        self._modify_other_keys_active = False
