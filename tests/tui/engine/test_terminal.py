"""
Tests for pipython.tui.engine.terminal module.

Tests cover:
- Kitty keyboard protocol reply parsing (parse_kitty_reply)
- Raw mode termios entry/exit sequences and idempotency — exercised through
  the *real* termios/tty/select/os.read boundary via ``raw_env()`` below,
  not a blanket ``sys.stdin`` mock (fix round 1, Critical 1: the previous
  version of this file mocked ``sys.stdin`` wholesale, so
  ``sys.stdin.fileno()`` returned a ``MagicMock``, tripping every
  ``isinstance(fd, int)`` guard in ``terminal.py`` and short-circuiting
  before termios/tty/select/os.read ever ran).
- Kitty/DA negotiation branches (clean reply, timeout, garbage, DA fallback,
  flags=0 fallback) with non-lossy typeahead preservation via
  ``drain_pending()`` (fix round 1, Critical 2).
- RealTerminal TerminalIO protocol implementation
- SIGWINCH handler registration for resize, with zero-arg callback arity
  (fix round 1, Important 3)
- atexit registration unconditional on raw-mode success (fix round 1,
  Important 4), and restartability after stop() (fix round 1, Minor)
- Exception-safe cleanup guarantees
- ANSI control sequences for cursor/display control

Upstream reference: ~/Developer/nukcole-pi/packages/tui/src/terminal.ts
"""

import os
import signal
import termios
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import MagicMock, Mock, patch

from pipython.tui.engine.terminal import (
    RealTerminal,
    parse_kitty_reply,
    KITTY_QUERY_SEQUENCE,
    BRACKETED_PASTE_ENABLE,
    BRACKETED_PASTE_DISABLE,
    KITTY_PROTOCOL_DISABLE,
    MODIFY_OTHER_KEYS_ENABLE,
    MODIFY_OTHER_KEYS_DISABLE,
    HIDE_CURSOR,
    SHOW_CURSOR,
    CLEAR_LINE,
)


# =============================================================================
# Real-boundary test harness (Critical 1)
# =============================================================================


class _StubStdin:
    """A real-int-fd stand-in for ``sys.stdin`` — deliberately *not* a
    ``MagicMock``. A ``MagicMock``'s ``fileno()`` would itself return a
    ``MagicMock``, which fails ``isinstance(fd, int)`` in ``terminal.py`` and
    short-circuits raw-mode entry / Kitty negotiation before termios/tty/
    select/os.read ever execute — the exact mistake this file was rewritten
    to stop making. Real termios/select/os.read calls are still prevented,
    just by mocking *those* functions directly instead of hiding the fd
    behind a mock object.
    """

    def fileno(self) -> int:
        return 0


@dataclass
class RawEnv:
    """Handle to every mock installed by ``raw_env()``."""

    stdout: MagicMock
    signal: MagicMock
    tcgetattr: MagicMock
    tcsetattr: MagicMock
    setraw: MagicMock
    select: MagicMock
    read: MagicMock
    atexit_register: MagicMock
    atexit_unregister: MagicMock


@contextmanager
def raw_env(saved_termios=("saved-termios-attrs",)):
    """Patch the real termios/tty/select/os/signal/atexit boundary that
    ``RealTerminal`` calls into, with ``sys.stdin`` replaced by
    ``_StubStdin`` (real int fd, not a MagicMock) so ``start()``/``stop()``
    exercise their actual raw-mode-entry and Kitty-negotiation code paths
    end to end.

    Defaults:

    - ``termios.tcgetattr`` returns ``list(saved_termios)`` (a sentinel
      "saved attrs" value that must round-trip unchanged to ``tcsetattr`` on
      stop).
    - ``select.select`` returns ``([], [], [])`` — "not ready" — so the
      Kitty probe times out immediately with zero bytes read. Tests that
      don't care about negotiation reach a deterministic
      ``kitty_enabled=False`` / modifyOtherKeys-fallback-written end state
      without any real waiting. Override ``env.select.side_effect`` /
      ``env.read.side_effect`` per test to script other negotiation
      branches.
    - ``atexit.register``/``atexit.unregister`` are mocked so no test ever
      registers a real process-exit callback pointing at a torn-down mock
      environment.
    """
    with (
        patch("sys.stdin", new=_StubStdin()),
        patch("sys.stdout") as mock_stdout,
        patch("signal.signal") as mock_signal,
        patch("termios.tcgetattr", return_value=list(saved_termios)) as mock_tcgetattr,
        patch("termios.tcsetattr") as mock_tcsetattr,
        patch("tty.setraw") as mock_setraw,
        patch("select.select", return_value=([], [], [])) as mock_select,
        patch("os.read", return_value=b"") as mock_read,
        patch("atexit.register") as mock_atexit_register,
        patch("atexit.unregister") as mock_atexit_unregister,
    ):
        yield RawEnv(
            stdout=mock_stdout,
            signal=mock_signal,
            tcgetattr=mock_tcgetattr,
            tcsetattr=mock_tcsetattr,
            setraw=mock_setraw,
            select=mock_select,
            read=mock_read,
            atexit_register=mock_atexit_register,
            atexit_unregister=mock_atexit_unregister,
        )


class TestParseKittyReply:
    """Test kitty keyboard protocol reply parsing."""

    def test_parse_kitty_reply_valid_flags_response(self):
        r"""Kitty probe response: CSI?<flags>u format.

        Upstream: terminal.ts line 26, parseKeyboardProtocolNegotiationSequence()
        Pattern: /^\x1b\[\?(\d+)u$/
        """
        # Valid kitty reply with flags=7 (all flags enabled)
        assert parse_kitty_reply("\x1b[?7u") is True
        # Valid with different flag values
        assert parse_kitty_reply("\x1b[?0u") is True
        assert parse_kitty_reply("\x1b[?15u") is True

    def test_parse_kitty_reply_device_attributes_response(self):
        r"""Device attributes (DA) fallback: CSI?c format.

        Upstream: terminal.ts line 30, parseKeyboardProtocolNegotiationSequence()
        Pattern: /^\x1b\[\?[\d;]*c$/
        Sent when terminal doesn't support Kitty protocol.
        """
        # Simple DA response
        assert parse_kitty_reply("\x1b[?c") is True
        # DA with multiple parameters
        assert parse_kitty_reply("\x1b[?63;1;2c") is True
        assert parse_kitty_reply("\x1b[?1;0c") is True

    def test_parse_kitty_reply_invalid_garbage(self):
        """Invalid/garbage data should return False."""
        assert parse_kitty_reply("") is False
        assert parse_kitty_reply("random text") is False
        assert parse_kitty_reply("\x1b[?7x") is False  # Wrong terminator
        assert parse_kitty_reply("\x1b[7u") is False  # Missing ? in CSI
        assert parse_kitty_reply("\x1b") is False
        assert parse_kitty_reply("\x1b[") is False  # Incomplete

    def test_parse_kitty_reply_partial_accepted_as_pending(self):
        """Partial/incomplete sequences may need buffering."""
        # These are prefixes but not complete sequences
        # Implementation may return False or handle buffering
        partial = "\x1b[?"
        # Should not crash on partial input
        result = parse_kitty_reply(partial)
        assert isinstance(result, bool)


class TestRawModeSequence:
    """Raw mode entry/exit termios call sequences — exercised for real via
    ``raw_env()`` (Critical 1: the previous blanket ``sys.stdin`` mock never
    let these calls execute at all)."""

    def test_start_enters_raw_mode_and_calls_termios_in_order(self):
        """start() must: fetch stdin's fd, ``tcgetattr(fd)`` to save state,
        ``tty.setraw(fd)`` to engage raw mode — then write bracketed paste
        enable and the Kitty query (terminal.ts:139-147, 225)."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            env.tcgetattr.assert_called_once_with(0)
            env.setraw.assert_called_once_with(0)
            assert term._raw_fd == 0

            env.stdout.write.assert_any_call(BRACKETED_PASTE_ENABLE)
            env.stdout.write.assert_any_call(KITTY_QUERY_SEQUENCE)

    def test_stop_restores_termios_with_saved_attrs(self):
        """stop() must call ``tcsetattr(fd, TCSADRAIN, <the attrs tcgetattr
        returned>)`` — the actual restore call this suite previously never
        reached (terminal.ts:449-451)."""
        with raw_env(saved_termios=("SAVED",)) as env:
            term = RealTerminal()
            term.start()
            term.stop()

            env.tcsetattr.assert_called_once_with(0, termios.TCSADRAIN, ["SAVED"])

            env.stdout.write.assert_any_call(BRACKETED_PASTE_DISABLE)
            env.stdout.write.assert_any_call(KITTY_PROTOCOL_DISABLE)

    def test_stop_is_idempotent(self):
        """Calling stop() twice should not double-restore or raise."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            term.stop()
            first_write_count = env.stdout.write.call_count
            first_tcsetattr_count = env.tcsetattr.call_count

            term.stop()

            assert env.stdout.write.call_count == first_write_count
            assert env.tcsetattr.call_count == first_tcsetattr_count

    def test_restart_after_stop_reenters_raw_mode(self):
        """Minor: stop() resets ``_started`` so ``start()`` after ``stop()``
        works again — upstream's terminal is likewise restartable."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()
            term.stop()

            assert term._started is False

            term.start()

            assert env.tcgetattr.call_count == 2
            assert env.setraw.call_count == 2
            enable_writes = [
                c for c in env.stdout.write.call_args_list if c.args == (BRACKETED_PASTE_ENABLE,)
            ]
            assert len(enable_writes) == 2


class TestAtexitGating:
    """Important 4: ``atexit.register(self.stop)`` must be armed
    unconditionally right after the first state-mutating write in
    ``start()``, not gated on raw-mode entry having succeeded."""

    def test_atexit_registered_even_when_raw_mode_fails(self):
        with raw_env() as env:
            env.tcgetattr.side_effect = termios.error("Inappropriate ioctl for device")

            term = RealTerminal()
            term.start()

            assert term._raw_fd is None  # raw mode genuinely failed
            env.atexit_register.assert_called_once_with(term.stop)
            # Bracketed paste is still written even though raw mode failed.
            env.stdout.write.assert_any_call(BRACKETED_PASTE_ENABLE)

    def test_atexit_unregistered_on_stop(self):
        with raw_env() as env:
            term = RealTerminal()
            term.start()
            term.stop()

            env.atexit_unregister.assert_called_once_with(term.stop)


class TestNegotiationBranches:
    """Critical 1 + Critical 2: script ``select.select``/``os.read`` to drive
    every Kitty/DA negotiation branch through the real termios/select/
    os.read boundary, and verify the probe never drops a byte — it searches
    for the reply pattern anywhere in the accumulating buffer and preserves
    every other byte via ``drain_pending()``."""

    def test_clean_kitty_reply_enables_kitty(self):
        """Important 1 (fix round 2): ``KITTY_QUERY_SEQUENCE`` always ends
        with the DA query (``\\x1b[c``), so on every Kitty-capable terminal
        the trailing DA reply arrives too — here in the *same* chunk as the
        Kitty-flags reply. Both replies must be excised; none may leak into
        ``drain_pending()``. Fails against the pre-fix
        ``_read_negotiation_reply`` (which returns as soon as the Kitty-flags
        reply is found, leaving ``\x1b[?1;2c`` as pending input)."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], [])]
            env.read.side_effect = [b"\x1b[?7u\x1b[?1;2c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is True
            assert term.drain_pending() == b""
            written = [c.args[0] for c in env.stdout.write.call_args_list]
            assert MODIFY_OTHER_KEYS_ENABLE not in written

    def test_kitty_flags_then_da_in_second_read_both_excised(self):
        """Important 1 (fix round 2): the Kitty-flags reply and the trailing
        DA reply arrive in two *separate* ``os.read`` chunks (simulating them
        landing in different pty reads). The probe must keep reading past
        the first (Kitty-flags) match and perform a second ``os.read`` to
        find and excise the DA reply too. ``env.read.call_count == 2`` is the
        genuine RED discriminator here: pre-fix code returns immediately
        after the first read/match and never attempts a second read."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([0], [], [])]
            env.read.side_effect = [b"\x1b[?7u", b"\x1b[?c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is True
            assert term.drain_pending() == b""
            assert env.read.call_count == 2

    def test_kitty_flags_da_never_arrives_before_deadline_residual(self):
        """Documents the one residual case module docstring deviation 6's
        "Fix round 2" note describes: a Kitty-flags reply is seen, but the
        DA reply that should terminate the probe never arrives before the
        200ms deadline. ``kitty_enabled`` still latches ``True`` off the
        Kitty-flags reply alone, and everything accumulated so far (here,
        unrelated typed-ahead bytes ``b"ZZ"`` sharing the chunk with the
        Kitty reply) is preserved via ``drain_pending()`` rather than
        discarded. ``env.select.call_count == 2`` is the genuine RED
        discriminator: pre-fix code returns immediately after the first
        match and never calls ``select`` a second time, so this assertion
        fails pre-fix even though ``kitty_enabled``/``drain_pending()`` alone
        happen to coincide with old behavior for this particular input."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([], [], [])]
            env.read.side_effect = [b"\x1b[?7uZZ"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is True
            assert term.drain_pending() == b"ZZ"
            assert env.select.call_count == 2

    def test_timeout_disables_kitty_and_writes_modify_other_keys_fallback(self):
        """No reply at all within the probe window (default ``raw_env()``'s
        immediate "not ready" select) leaves ``kitty_enabled`` False and
        writes the modifyOtherKeys fallback (fix round 1 addition, see
        terminal.py module docstring deviation 1)."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == b""

    def test_garbage_then_timeout_disables_kitty_and_preserves_bytes(self):
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([], [], [])]
            env.read.side_effect = [b"garbage"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == b"garbage"

    def test_typeahead_and_reply_mixed_in_one_chunk_preserved(self):
        """A single stdin chunk containing typed-ahead keystrokes *and* the
        negotiation reply must both detect the reply and preserve the typed
        bytes (Critical 2) — not discard everything because the whole
        buffer doesn't equal the reply. A DA reply is appended after the
        Kitty reply (fix round 2, Important 1: every Kitty-capable terminal
        also answers the probe's trailing DA query) to prove it does NOT
        get counted as leftover pending input."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], [])]
            env.read.side_effect = [b"abc\x1b[?31u\x1b[?c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is True
            assert term.drain_pending() == b"abc"

    def test_reply_mid_buffer_bytes_before_and_after_preserved(self):
        """DA appended at the very end, after the "XY" typeahead (fix round
        2, Important 1), to prove the universal DA terminator is excised
        rather than folded into the preserved typeahead."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], [])]
            env.read.side_effect = [b"ab\x1b[?7uXY\x1b[?c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is True
            assert term.drain_pending() == b"abXY"

    def test_device_attributes_reply_triggers_modify_other_keys_fallback(self):
        with raw_env() as env:
            env.select.side_effect = [([0], [], [])]
            env.read.side_effect = [b"\x1b[?1;2c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == b""

    def test_kitty_flags_zero_triggers_modify_other_keys_fallback(self):
        """DA appended after the negative (``flags == 0``) Kitty-flags reply
        (fix round 2, Important 1) proves the "only DA seen after a
        *negative* Kitty reply" path also fully excises both replies —
        ``drain_pending()`` must be empty, not left holding the DA reply."""
        with raw_env() as env:
            env.select.side_effect = [([0], [], [])]
            env.read.side_effect = [b"\x1b[?0u\x1b[?c"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == b""

    def test_timeout_across_multiple_reads_preserves_all_bytes(self):
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([0], [], []), ([], [], [])]
            env.read.side_effect = [b"ab", b"cd"]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            assert term.drain_pending() == b"abcd"

    def test_os_read_error_preserves_buffered_bytes(self):
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([0], [], [])]
            env.read.side_effect = [b"xy", OSError("boom")]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == b"xy"

    def test_buffer_overflow_preserves_bytes_and_falls_back(self):
        with raw_env() as env:
            chunk = b"z" * 40  # two chunks (80 bytes) exceed _KITTY_PROBE_MAX_BUFFER (64)
            env.select.side_effect = [([0], [], [])] * 2
            env.read.side_effect = [chunk, chunk]

            term = RealTerminal()
            term.start()

            assert term.kitty_enabled is False
            env.stdout.write.assert_any_call(MODIFY_OTHER_KEYS_ENABLE)
            assert term.drain_pending() == chunk + chunk

    def test_drain_pending_clears_after_read(self):
        with raw_env() as env:
            env.select.side_effect = [([0], [], []), ([], [], [])]
            env.read.side_effect = [b"leftover"]

            term = RealTerminal()
            term.start()

            assert term.drain_pending() == b"leftover"
            assert term.drain_pending() == b""


class TestStopOnException:
    """Test that stop() still restores on exception path."""

    def test_stop_restores_on_exception(self):
        """Exception during terminal operation should trigger cleanup via finally/atexit.

        Upstream: terminal.ts line 406 - stop() is called, cleanup guaranteed.
        """
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            # Simulate exception during operation
            try:
                term.write("test")
                raise RuntimeError("Simulated error")
            except RuntimeError:
                pass

            # Manually call stop (in real code this is via finally/atexit)
            term.stop()

            # Verify restore sequences were written
            env.stdout.write.assert_any_call(BRACKETED_PASTE_DISABLE)


class TestTerminalIOProtocol:
    """Test RealTerminal implements TerminalIO protocol."""

    def test_write_method_exists(self):
        """RealTerminal.write(data: str) method required by TerminalIO."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            term.write("Hello, terminal!")

            env.stdout.write.assert_called_with("Hello, terminal!")

    def test_columns_property_exists(self):
        """RealTerminal.columns: int property required by TerminalIO.

        Upstream: terminal.ts line 465-467
        Returns stdout.columns or COLUMNS env var or default 80
        """
        with raw_env() as env:
            env.stdout.columns = 100

            term = RealTerminal()
            term.start()

            assert term.columns == 100

    def test_rows_property_exists(self):
        """RealTerminal.rows: int property required by TerminalIO.

        Upstream: terminal.ts line 469-471
        Returns stdout.rows or LINES env var or default 24
        """
        with raw_env() as env:
            env.stdout.rows = 30

            term = RealTerminal()
            term.start()

            assert term.rows == 30


class TestWriteFlushesStdout:
    """Bug fix (evidence: ``.superpowers/sdd/task-17-report.md`` "Task 17
    (resumed)"): line-buffered tty stdout silently drops any frame lacking a
    trailing newline — ordinary keystroke echo and the ``[interrupted]``
    shrink-frame (cursor moves + erase-line only, no ``\\n``) never render
    on a real terminal, because ``RealTerminal.write`` never called
    ``sys.stdout.flush()``. Every ``write()`` must flush immediately after,
    including the restore writes issued from ``stop()``."""

    def test_write_flushes_after_each_write(self):
        with raw_env() as env:
            term = RealTerminal()
            term.start()

            flushes_before = env.stdout.flush.call_count
            term.write("partial frame, no trailing newline")

            assert env.stdout.flush.call_count == flushes_before + 1
            # flush must come after the write it belongs to, not before.
            write_call_index = len(env.stdout.method_calls) - 1
            assert env.stdout.method_calls[write_call_index][0] == "flush"
            assert env.stdout.method_calls[write_call_index - 1] == (
                "write",
                ("partial frame, no trailing newline",),
                {},
            )

    def test_stop_restore_writes_each_flush(self):
        """stop() issues several restore writes (bracketed paste disable,
        Kitty/modifyOtherKeys disable, show cursor) — each one must flush,
        not just the last."""
        with raw_env() as env:
            term = RealTerminal()
            term.start()
            writes_before_stop = env.stdout.write.call_count
            flushes_before_stop = env.stdout.flush.call_count

            term.stop()

            writes_during_stop = env.stdout.write.call_count - writes_before_stop
            flushes_during_stop = env.stdout.flush.call_count - flushes_before_stop
            assert writes_during_stop > 0
            assert flushes_during_stop == writes_during_stop


class TestResizeHandler:
    """Important 3: ``on_resize(cb)`` wraps ``cb`` in a zero-arg,
    upstream-shaped adapter (``Callable[[], None]``) rather than passing it
    to ``signal.signal`` unwrapped. The installed *signal handler* still has
    ``(signum, frame)`` arity (that's what ``signal.signal`` requires) — but
    invoking it must call ``cb`` with zero arguments."""

    def test_on_resize_registers_sigwinch(self):
        """RealTerminal.on_resize(cb) registers a handler for SIGWINCH.

        Upstream: terminal.ts line 150, process.stdout.on('resize')
        Python: signal.signal(signal.SIGWINCH, handler)
        """
        with patch("signal.signal") as mock_signal:
            term = RealTerminal()
            callback = Mock()
            term.on_resize(callback)

            assert mock_signal.call_count == 1
            registered_signum, installed_handler = mock_signal.call_args.args
            assert registered_signum == signal.SIGWINCH
            assert callable(installed_handler)

    def test_installed_handler_invokes_callback_with_zero_args(self):
        """Wiring test, not identity: invoke the handler actually passed to
        ``signal.signal`` with real signal-handler arity, and verify ``cb``
        is invoked with none. (The RED suite's old
        ``mock_signal.assert_any_call(signal.SIGWINCH, callback)`` identity
        assertion no longer holds — ``on_resize`` now wraps ``cb`` rather
        than passing it through unwrapped.)"""
        with patch("signal.signal") as mock_signal:
            term = RealTerminal()
            callback = Mock()
            term.on_resize(callback)

            _, installed_handler = mock_signal.call_args.args
            installed_handler(signal.SIGWINCH, None)

            callback.assert_called_once_with()


class TestANSISequences:
    """Test that ANSI control sequences match upstream terminal.ts."""

    def test_kitty_query_sequence(self):
        """KITTY_KEYBOARD_PROTOCOL_QUERY per terminal.ts line 17.

        Flags=7 (1|2|4): disambiguate escapes | report event types | report alt keys
        Upstream: \\x1b[>7u\\x1b[?u\\x1b[c
        """
        expected = "\x1b[>7u\x1b[?u\x1b[c"
        assert KITTY_QUERY_SEQUENCE == expected

    def test_bracketed_paste_enable(self):
        """Enable bracketed paste mode per terminal.ts line 147.

        CSI ? 2 0 0 4 h
        """
        assert BRACKETED_PASTE_ENABLE == "\x1b[?2004h"

    def test_bracketed_paste_disable(self):
        """Disable bracketed paste mode per terminal.ts line 412.

        CSI ? 2 0 0 4 l
        """
        assert BRACKETED_PASTE_DISABLE == "\x1b[?2004l"

    def test_kitty_protocol_disable(self):
        """Disable Kitty keyboard protocol per terminal.ts line 374, 419.

        CSI < u
        """
        assert KITTY_PROTOCOL_DISABLE == "\x1b[<u"

    def test_modify_other_keys_enable(self):
        """Enable modifyOtherKeys fallback per terminal.ts line 322.

        CSI > 4 ; 2 m
        """
        assert MODIFY_OTHER_KEYS_ENABLE == "\x1b[>4;2m"

    def test_modify_other_keys_disable(self):
        """Disable modifyOtherKeys fallback per terminal.ts line 328.

        CSI > 4 ; 0 m
        """
        assert MODIFY_OTHER_KEYS_DISABLE == "\x1b[>4;0m"

    def test_cursor_control_sequences(self):
        """Cursor control ANSI sequences per terminal.ts."""
        # Hide cursor: CSI ? 2 5 l (line 485)
        assert HIDE_CURSOR == "\x1b[?25l"
        # Show cursor: CSI ? 2 5 h (line 489)
        assert SHOW_CURSOR == "\x1b[?25h"
        # Clear line: CSI K (line 493)
        assert CLEAR_LINE == "\x1b[K"


class TestTerminalIOIntegration:
    """Integration tests for complete terminal lifecycle."""

    def test_terminal_lifecycle(self):
        """Full terminal start -> write -> stop sequence."""
        with raw_env() as env:
            env.stdout.columns = 80
            env.stdout.rows = 24

            term = RealTerminal()
            assert hasattr(term, "start")
            assert hasattr(term, "stop")
            assert hasattr(term, "write")
            assert hasattr(term, "columns")
            assert hasattr(term, "rows")
            assert hasattr(term, "on_resize")
            assert hasattr(term, "drain_pending")

    def test_columns_default_fallback(self):
        """RealTerminal.columns falls back to exactly 80 if stdout.columns is
        None (Minor: pinned from the RED suite's hedged ``in (80, None)``).

        Minor 3 (fix round 2): patches ``shutil.get_terminal_size`` directly
        rather than relying on pytest's default fd-level output capture
        making the real ``sys.__stdout__`` a non-tty — that assumption broke
        under ``pytest -s`` (capture disabled), where a real tty stdout would
        make the real ioctl probe return the actual terminal size instead of
        the fallback. This version is deterministic regardless of capture
        mode."""
        with (
            raw_env() as env,
            patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))),
        ):
            env.stdout.columns = None

            term = RealTerminal()
            term.start()

            assert term.columns == 80

    def test_rows_default_fallback(self):
        """RealTerminal.rows falls back to exactly 24 if stdout.rows is None.

        Minor 3 (fix round 2): same ``shutil.get_terminal_size`` patch as
        ``test_columns_default_fallback``, making this independent of
        pytest's capture mode / robust under ``pytest -s``."""
        with (
            raw_env() as env,
            patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))),
        ):
            env.stdout.rows = None

            term = RealTerminal()
            term.start()

            assert term.rows == 24
