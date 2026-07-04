"""Stdin byte-stream framing — Python port of upstream pi's
``packages/tui/src/stdin-buffer.ts`` (``StdinBuffer``, 434 lines, full port).

Buffers raw stdin bytes and emits complete "frames": regular characters
pass through immediately, complete escape sequences (CSI/OSC/DCS/APC/SS3/
meta-key) are emitted whole, partial sequences are held until either more
data completes them or an injectable timer fires (flushing whatever is
buffered as a single frame), and bracketed-paste content
(``ESC[200~`` … ``ESC[201~``) is delivered as one block via a dedicated
``on_paste`` callback rather than split into per-character frames.

Interface (binding, per task-3 brief): ``StdinBuffer(on_frame, esc_timeout=0.05,
timer=...)`` with ``feed(data: bytes) -> None``. The frozen RED test fixture
(``tests/tui/engine/test_stdin_buffer.py``) additionally requires an
``on_paste`` callback and a ``timer`` object shaped like the tests'
``FakeTimer`` — ``schedule(delay_ms, callback) -> handle`` /
``cancel(handle) -> None`` — rather than a bare callable as the brief's
shorthand ("timer: Callable") suggested; this port follows the test
contract as the source of truth for that shape (see the ``Timer`` protocol
below) and falls back to a small asyncio-backed timer when none is
injected.

Deviations from upstream (declared per port convention):

- Default ``esc_timeout`` is 0.05s (50ms), per the binding task-3 interface
  spec — upstream's ``StdinBufferOptions.timeout`` defaults to 10ms
  (stdin-buffer.ts:284). Same mechanism, different default; both are
  overridable exactly as the tests do (``esc_timeout=0.01``).
- ``on_paste`` is a separate constructor callback rather than a signal
  upstream expresses via ``EventEmitter``'s ``"paste"`` event
  (stdin-buffer.ts:265-268, 328, 362). If omitted, paste content is
  delivered through ``on_frame`` instead of being silently dropped, so
  bracketed paste is still surfaced as "one frame" even for callers that
  only supply a single callback.
- Each ``feed()`` chunk is decoded with ``errors="replace"``, mirroring
  Node's tolerant ``Buffer.toString("utf8")`` (which does not throw on
  incomplete multi-byte sequences split across chunks). Upstream never
  buffers partial UTF-8 bytes across chunks either — this matches that
  behaviour rather than adding a new limitation.
- Plain (non-escape, non-paste) characters are extracted one Unicode
  *codepoint* at a time (Python string indexing), whereas upstream indexes
  by UTF-16 *code unit* (JS string indexing, stdin-buffer.ts:249). For an
  astral-plane character typed directly outside of bracketed paste (not
  exercised by any translated test), upstream's JS indexing would split
  the UTF-16 surrogate pair into two pseudo-frames; this port emits the
  whole codepoint as a single frame. Not observable in the translated
  suite — the one astral character present (U+1F389, "🎉") appears inside
  a paste block, which is sliced as a substring rather than iterated,
  giving an identical result in both languages.
- A pre-existing upstream quirk, ported as-is (not introduced here): when a
  bracketed-paste start marker is found partway through the buffer
  (stdin-buffer.ts:337-348), any *incomplete* escape sequence preceding it
  in the same chunk is silently dropped — only fully completed sequences
  before the marker are emitted, the remainder is discarded rather than
  kept buffered. No translated test exercises this combination.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Literal, Protocol

__all__ = ["StdinBuffer", "Timer"]

ESC = "\x1b"
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"

_SequenceStatus = Literal["complete", "incomplete", "not-escape"]

_KITTY_PRINTABLE_RE = re.compile(r"^\x1b\[(\d+)(?::\d*)?(?::\d+)?u$")
_MOUSE_SGR_RE = re.compile(r"^<\d+;\d+;\d+[Mm]$")
_DIGITS_RE = re.compile(r"^\d+$")
_ESC_RESTART_CHARS = ("[", "]", "O", "P", "_")


class Timer(Protocol):
    """Injectable timer contract, matching the RED test suite's ``FakeTimer``.

    ``schedule`` takes a delay in *milliseconds* and returns an opaque
    handle; ``cancel`` takes that handle back to cancel a pending call.
    Parameter names match ``FakeTimer`` exactly (``delay``/``timeout_id``)
    since pyright's structural protocol check is name-sensitive. The handle
    is typed ``Any`` (rather than e.g. ``object``) because concrete timers
    disagree on its type (``FakeTimer`` uses ``int``, the asyncio-backed
    default uses ``asyncio.TimerHandle``) and the protocol only needs to
    round-trip it opaquely between ``schedule`` and ``cancel``.
    """

    def schedule(self, delay: float, callback: Callable[[], None]) -> Any: ...

    def cancel(self, timeout_id: Any) -> None: ...


class _AsyncioTimer:
    """Default production timer, backed by the running asyncio event loop."""

    def schedule(self, delay: float, callback: Callable[[], None]) -> asyncio.TimerHandle:
        loop = asyncio.get_running_loop()
        return loop.call_later(delay / 1000.0, callback)

    def cancel(self, timeout_id: asyncio.TimerHandle) -> None:
        timeout_id.cancel()


def _parse_unmodified_kitty_printable_codepoint(sequence: str) -> int | None:
    """stdin-buffer.ts:184-190."""
    match = _KITTY_PRINTABLE_RE.match(sequence)
    if not match:
        return None
    codepoint = int(match.group(1))
    return codepoint if codepoint >= 32 else None


def _is_complete_csi_sequence(data: str) -> _SequenceStatus:
    """stdin-buffer.ts:84-126."""
    if not data.startswith(ESC + "["):
        return "complete"

    if len(data) < 3:
        return "incomplete"

    payload = data[2:]
    last_char = payload[-1]
    last_char_code = ord(last_char)

    if 0x40 <= last_char_code <= 0x7E:
        if payload.startswith("<"):
            if _MOUSE_SGR_RE.match(payload):
                return "complete"
            if last_char in ("M", "m"):
                parts = payload[1:-1].split(";")
                if len(parts) == 3 and all(_DIGITS_RE.match(p) for p in parts):
                    return "complete"
            return "incomplete"
        return "complete"

    return "incomplete"


def _is_complete_osc_sequence(data: str) -> _SequenceStatus:
    """stdin-buffer.ts:132-143."""
    if not data.startswith(ESC + "]"):
        return "complete"
    if data.endswith(ESC + "\\") or data.endswith("\x07"):
        return "complete"
    return "incomplete"


def _is_complete_dcs_sequence(data: str) -> _SequenceStatus:
    """stdin-buffer.ts:150-161."""
    if not data.startswith(ESC + "P"):
        return "complete"
    if data.endswith(ESC + "\\"):
        return "complete"
    return "incomplete"


def _is_complete_apc_sequence(data: str) -> _SequenceStatus:
    """stdin-buffer.ts:168-179."""
    if not data.startswith(ESC + "_"):
        return "complete"
    if data.endswith(ESC + "\\"):
        return "complete"
    return "incomplete"


def _is_complete_sequence(data: str) -> _SequenceStatus:
    """stdin-buffer.ts:29-78."""
    if not data.startswith(ESC):
        return "not-escape"

    if len(data) == 1:
        return "incomplete"

    after_esc = data[1:]

    if after_esc.startswith("["):
        if after_esc.startswith("[M"):
            # Old-style mouse: ESC[M + 3 bytes = 6 total.
            return "complete" if len(data) >= 6 else "incomplete"
        return _is_complete_csi_sequence(data)

    if after_esc.startswith("]"):
        return _is_complete_osc_sequence(data)

    if after_esc.startswith("P"):
        return _is_complete_dcs_sequence(data)

    if after_esc.startswith("_"):
        return _is_complete_apc_sequence(data)

    if after_esc.startswith("O"):
        # SS3: ESC O followed by a single character.
        return "complete" if len(after_esc) >= 2 else "incomplete"

    if len(after_esc) == 1:
        # Meta key sequence: ESC followed by a single character.
        return "complete"

    # Unknown escape sequence - treat as complete.
    return "complete"


def _extract_complete_sequences(buffer: str) -> tuple[list[str], str]:
    """Split accumulated buffer into complete sequences. stdin-buffer.ts:192-255."""
    sequences: list[str] = []
    pos = 0

    while pos < len(buffer):
        remaining = buffer[pos:]

        if not remaining.startswith(ESC):
            sequences.append(remaining[0])
            pos += 1
            continue

        seq_end = 1
        consumed = False
        while seq_end <= len(remaining):
            candidate = remaining[:seq_end]
            status = _is_complete_sequence(candidate)

            if status == "complete":
                if candidate == ESC + ESC:
                    # WezTerm with enable_kitty_keyboard sends the Escape key
                    # press as a raw ESC byte and the release as a full Kitty
                    # CSI-u sequence, concatenated. If the char right after
                    # this "\x1b\x1b" would start a new escape sequence,
                    # emit only the first ESC and restart from the second.
                    next_char = remaining[seq_end] if seq_end < len(remaining) else None
                    if next_char in _ESC_RESTART_CHARS:
                        sequences.append(ESC)
                        pos += 1
                        consumed = True
                        break
                sequences.append(candidate)
                pos += seq_end
                consumed = True
                break
            elif status == "incomplete":
                seq_end += 1
            else:
                # Should not happen when starting with ESC.
                sequences.append(candidate)
                pos += seq_end
                consumed = True
                break

        if not consumed:
            return sequences, remaining

    return sequences, ""


class StdinBuffer:
    """Buffers stdin input and emits complete frames via ``on_frame``.

    Handles partial escape sequences that arrive across multiple ``feed()``
    calls, and delivers bracketed-paste content as a single block via
    ``on_paste`` (see the module docstring for the full port-convention
    notes and declared deviations).
    """

    def __init__(
        self,
        on_frame: Callable[[str], None],
        on_paste: Callable[[str], None] | None = None,
        esc_timeout: float = 0.05,
        timer: Timer | None = None,
    ) -> None:
        self._on_frame = on_frame
        self._on_paste = on_paste if on_paste is not None else on_frame
        self._esc_timeout = esc_timeout
        self._timer: Timer = timer if timer is not None else _AsyncioTimer()

        self._buffer = ""
        self._timeout_handle: Any | None = None
        self._paste_mode = False
        self._paste_buffer = ""
        self._pending_kitty_codepoint: int | None = None

    def feed(self, data: bytes) -> None:
        """Process incoming bytes. stdin-buffer.ts:287-306 (Buffer branch)."""
        if len(data) == 1 and data[0] > 127:
            # High-bit-set single byte: legacy "meta sends escape" encoding
            # (Alt+char sent as a raw high byte) -> ESC + (byte - 128).
            text = ESC + chr(data[0] - 128)
        else:
            text = data.decode("utf-8", errors="replace")
        self._process_str(text)

    def _process_str(self, s: str) -> None:
        """stdin-buffer.ts:287-387 (string-space body of ``process``)."""
        if self._timeout_handle is not None:
            self._timer.cancel(self._timeout_handle)
            self._timeout_handle = None

        if len(s) == 0 and len(self._buffer) == 0:
            self._emit_data_sequence("")
            return

        self._buffer += s

        if self._paste_mode:
            self._paste_buffer += self._buffer
            self._buffer = ""
            self._try_complete_paste()
            return

        start_index = self._buffer.find(BRACKETED_PASTE_START)
        if start_index != -1:
            if start_index > 0:
                before_paste = self._buffer[:start_index]
                sequences, _ = _extract_complete_sequences(before_paste)
                for sequence in sequences:
                    self._emit_data_sequence(sequence)

            self._pending_kitty_codepoint = None
            self._buffer = self._buffer[start_index + len(BRACKETED_PASTE_START) :]
            self._paste_mode = True
            self._paste_buffer = self._buffer
            self._buffer = ""
            self._try_complete_paste()
            return

        sequences, remainder = _extract_complete_sequences(self._buffer)
        self._buffer = remainder

        for sequence in sequences:
            self._emit_data_sequence(sequence)

        if len(self._buffer) > 0:
            self._timeout_handle = self._timer.schedule(self._esc_timeout * 1000, self._on_timeout)

    def _try_complete_paste(self) -> None:
        """Shared tail of the two paste-completion sites in ``process()``
        (stdin-buffer.ts:319-333 and 353-367)."""
        end_index = self._paste_buffer.find(BRACKETED_PASTE_END)
        if end_index == -1:
            return

        pasted_content = self._paste_buffer[:end_index]
        remaining = self._paste_buffer[end_index + len(BRACKETED_PASTE_END) :]

        self._paste_mode = False
        self._paste_buffer = ""
        self._pending_kitty_codepoint = None

        self._on_paste(pasted_content)

        if len(remaining) > 0:
            self._process_str(remaining)

    def _on_timeout(self) -> None:
        """stdin-buffer.ts:379-385."""
        for sequence in self.flush():
            self._emit_data_sequence(sequence)

    def _emit_data_sequence(self, sequence: str) -> None:
        """stdin-buffer.ts:389-398."""
        raw_codepoint = ord(sequence) if len(sequence) == 1 else None
        if raw_codepoint is not None and raw_codepoint == self._pending_kitty_codepoint:
            self._pending_kitty_codepoint = None
            return

        self._pending_kitty_codepoint = _parse_unmodified_kitty_printable_codepoint(sequence)
        self._on_frame(sequence)

    def flush(self) -> list[str]:
        """Manually emit buffered incomplete sequences. stdin-buffer.ts:400-414."""
        if self._timeout_handle is not None:
            self._timer.cancel(self._timeout_handle)
            self._timeout_handle = None

        if len(self._buffer) == 0:
            return []

        sequences = [self._buffer]
        self._buffer = ""
        self._pending_kitty_codepoint = None
        return sequences

    def clear(self) -> None:
        """Discard all buffered content. stdin-buffer.ts:416-425."""
        if self._timeout_handle is not None:
            self._timer.cancel(self._timeout_handle)
            self._timeout_handle = None
        self._buffer = ""
        self._paste_mode = False
        self._paste_buffer = ""
        self._pending_kitty_codepoint = None

    def get_buffer(self) -> str:
        """Inspect internal buffer state. stdin-buffer.ts:427-429."""
        return self._buffer

    def destroy(self) -> None:
        """Cancel any pending timer and drop buffered state. stdin-buffer.ts:431-433."""
        self.clear()
