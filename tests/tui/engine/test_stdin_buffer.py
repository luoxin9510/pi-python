"""
Tests for StdinBuffer

Translated from upstream: packages/tui/test/stdin-buffer.test.ts
Based on code from OpenTUI (https://github.com/anomalyco/opentui)
MIT License - Copyright (c) 2025 opentui
"""

import pytest
from typing import Callable


class FakeTimer:
    """Manual timer for testing - allows driving time in tests without real sleeps."""

    def __init__(self):
        self.pending: list[tuple[float, Callable[[], None]]] = []
        self.current_time = 0.0

    def schedule(self, delay: float, callback: Callable[[], None]) -> int:
        """Schedule a callback to run after delay milliseconds."""
        timeout_id = len(self.pending)
        self.pending.append((self.current_time + delay / 1000.0, callback))
        # Sort by time
        self.pending.sort(key=lambda x: x[0])
        return timeout_id

    def cancel(self, timeout_id: int) -> None:
        """Cancel a scheduled timeout."""
        if timeout_id < len(self.pending):
            self.pending.pop(timeout_id)

    def advance(self, ms: float) -> None:
        """Advance time and run any due callbacks."""
        self.current_time += ms / 1000.0
        # Run all callbacks due by current_time
        while self.pending and self.pending[0][0] <= self.current_time:
            _, callback = self.pending.pop(0)
            callback()


# Try to import the actual StdinBuffer - tests should fail with ModuleNotFoundError initially
try:
    from pipython.tui.engine.stdin_buffer import StdinBuffer
except ImportError:
    StdinBuffer = None


@pytest.fixture
def buffer_setup():
    """Fixture to set up a test buffer with FakeTimer."""
    if StdinBuffer is None:
        pytest.skip("StdinBuffer not yet implemented")

    timer = FakeTimer()
    emitted_sequences = []

    def on_frame(sequence: str) -> None:
        emitted_sequences.append(sequence)

    buffer = StdinBuffer(
        on_frame=on_frame,
        esc_timeout=0.01,  # 10ms in seconds - matches upstream's default
        timer=timer,
    )

    return {
        "buffer": buffer,
        "timer": timer,
        "emitted_sequences": emitted_sequences,
    }


class TestRegularCharacters:
    """Test handling of regular (non-escape) characters."""

    def test_pass_through_regular_characters_immediately(self, buffer_setup):
        """Regular characters should be emitted immediately."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"a")
        assert emitted == ["a"]

    def test_pass_through_multiple_regular_characters(self, buffer_setup):
        """Multiple regular characters should each be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"abc")
        assert emitted == ["a", "b", "c"]

    def test_handle_unicode_characters(self, buffer_setup):
        """Unicode characters should be handled correctly."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed("hello 世界".encode("utf-8"))
        assert emitted == ["h", "e", "l", "l", "o", " ", "世", "界"]


class TestCompleteEscapeSequences:
    """Test handling of complete escape sequences."""

    def test_pass_through_complete_mouse_sgr_sequences(self, buffer_setup):
        """Complete mouse SGR sequences should be emitted as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        mouse_seq = "\x1b[<35;20;5m"
        buffer.feed(mouse_seq.encode())
        assert emitted == [mouse_seq]

    def test_pass_through_complete_arrow_key_sequences(self, buffer_setup):
        """Arrow key sequences should be emitted as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        up_arrow = "\x1b[A"
        buffer.feed(up_arrow.encode())
        assert emitted == [up_arrow]

    def test_pass_through_complete_function_key_sequences(self, buffer_setup):
        """Function key sequences should be emitted as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        f1 = "\x1b[11~"
        buffer.feed(f1.encode())
        assert emitted == [f1]

    def test_pass_through_meta_key_sequences(self, buffer_setup):
        """Meta key sequences should be emitted as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        meta_a = "\x1ba"
        buffer.feed(meta_a.encode())
        assert emitted == [meta_a]

    def test_pass_through_ss3_sequences(self, buffer_setup):
        """SS3 sequences should be emitted as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        ss3 = "\x1bOA"
        buffer.feed(ss3.encode())
        assert emitted == [ss3]


class TestPartialEscapeSequences:
    """Test handling of escape sequences split across multiple feeds."""

    def test_buffer_incomplete_mouse_sgr_sequence(self, buffer_setup):
        """Incomplete mouse SGR sequences should be buffered."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b")
        assert emitted == []
        assert buffer.get_buffer() == "\x1b"

        buffer.feed(b"[<35")
        assert emitted == []
        assert buffer.get_buffer() == "\x1b[<35"

        buffer.feed(b";20;5m")
        assert emitted == ["\x1b[<35;20;5m"]
        assert buffer.get_buffer() == ""

    def test_buffer_incomplete_csi_sequence(self, buffer_setup):
        """Incomplete CSI sequences should be buffered."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[")
        assert emitted == []

        buffer.feed(b"1;")
        assert emitted == []

        buffer.feed(b"5H")
        assert emitted == ["\x1b[1;5H"]

    def test_buffer_split_across_many_chunks(self, buffer_setup):
        """Sequences can be split across many individual byte feeds."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        for byte in b"\x1b[<35;20;5m":
            buffer.feed(bytes([byte]))

        assert emitted == ["\x1b[<35;20;5m"]

    def test_flush_incomplete_sequence_after_timeout(self, buffer_setup):
        """Incomplete sequences should be flushed after timeout."""
        buffer = buffer_setup["buffer"]
        timer = buffer_setup["timer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35")
        assert emitted == []

        # Advance time past timeout
        timer.advance(15)

        assert emitted == ["\x1b[<35"]


class TestMixedContent:
    """Test handling of mixed regular characters and escape sequences."""

    def test_handle_characters_followed_by_escape_sequence(self, buffer_setup):
        """Characters followed by an escape sequence should emit in order."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"abc\x1b[A")
        assert emitted == ["a", "b", "c", "\x1b[A"]

    def test_handle_escape_sequence_followed_by_characters(self, buffer_setup):
        """Escape sequence followed by characters should emit in order."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[Aabc")
        assert emitted == ["\x1b[A", "a", "b", "c"]

    def test_handle_multiple_complete_sequences(self, buffer_setup):
        """Multiple complete sequences should each emit."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[A\x1b[B\x1b[C")
        assert emitted == ["\x1b[A", "\x1b[B", "\x1b[C"]

    def test_handle_partial_sequence_with_preceding_characters(self, buffer_setup):
        """Partial sequence after characters should buffer the sequence."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"abc\x1b[<35")
        assert emitted == ["a", "b", "c"]
        assert buffer.get_buffer() == "\x1b[<35"

        buffer.feed(b";20;5m")
        assert emitted == ["a", "b", "c", "\x1b[<35;20;5m"]


class TestKittyKeyboardProtocol:
    """Test handling of Kitty keyboard protocol sequences."""

    def test_handle_kitty_csi_u_press_events(self, buffer_setup):
        """Kitty CSI u press events should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[97u")
        assert emitted == ["\x1b[97u"]

    def test_handle_kitty_csi_u_release_events(self, buffer_setup):
        """Kitty CSI u release events should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[97;1:3u")
        assert emitted == ["\x1b[97;1:3u"]

    def test_handle_batched_kitty_press_and_release(self, buffer_setup):
        """Batched Kitty press and release should emit both."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[97u\x1b[97;1:3u")
        assert emitted == ["\x1b[97u", "\x1b[97;1:3u"]

    def test_handle_multiple_batched_kitty_events(self, buffer_setup):
        """Multiple batched Kitty events should each emit."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[97u\x1b[97;1:3u\x1b[98u\x1b[98;1:3u")
        assert emitted == ["\x1b[97u", "\x1b[97;1:3u", "\x1b[98u", "\x1b[98;1:3u"]

    def test_handle_kitty_arrow_keys_with_event_type(self, buffer_setup):
        """Kitty arrow keys with event type should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[1;1:1A")
        assert emitted == ["\x1b[1;1:1A"]

    def test_handle_kitty_functional_keys_with_event_type(self, buffer_setup):
        """Kitty functional keys with event type should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[3;1:3~")
        assert emitted == ["\x1b[3;1:3~"]

    def test_split_esc_esc_csi_into_standalone_esc_and_csi(self, buffer_setup):
        """ESC+ESC+CSI should split into standalone ESC and CSI sequence."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        # WezTerm with Kitty keyboard sends Escape key press as raw \x1b
        # and release as full Kitty CSI-u sequence, concatenated.
        buffer.feed(b"\x1b\x1b[27;129:3u")
        assert emitted == ["\x1b", "\x1b[27;129:3u"]

    def test_split_esc_esc_csi_with_no_modifier(self, buffer_setup):
        """ESC+ESC+CSI with no modifier should split."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b\x1b[27;1:3u")
        assert emitted == ["\x1b", "\x1b[27;1:3u"]

    def test_keep_esc_esc_as_single_sequence_when_not_followed_by_new_escape(self, buffer_setup):
        """ESC+ESC alone (not followed by new escape) should stay as-is."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b\x1b")
        assert emitted == ["\x1b\x1b"]

    def test_handle_plain_characters_mixed_with_kitty_sequences(self, buffer_setup):
        """Plain characters mixed with Kitty sequences should emit in order."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"a\x1b[97;1:3u")
        assert emitted == ["a", "\x1b[97;1:3u"]

    def test_drop_raw_duplicate_character_after_matching_kitty_printable_sequence(
        self, buffer_setup
    ):
        """Raw duplicate character after Kitty printable sequence should be dropped."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[224u\xc3\xa0")  # à in UTF-8
        assert emitted == ["\x1b[224u"]

    def test_drop_raw_duplicate_character_across_chunks(self, buffer_setup):
        """Raw duplicate after Kitty printable sequence across chunks should be dropped."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[64u")
        buffer.feed(b"@")
        assert emitted == ["\x1b[64u"]

    def test_keep_non_matching_plain_character_after_kitty_printable_sequence(self, buffer_setup):
        """Non-matching plain character after Kitty sequence should be kept."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[97ub")
        assert emitted == ["\x1b[97u", "b"]

    def test_keep_raw_character_after_modified_kitty_printable_sequence(self, buffer_setup):
        """Raw character after modified Kitty sequence should be kept."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[64;3u@")
        assert emitted == ["\x1b[64;3u", "@"]

    def test_handle_rapid_typing_simulation_with_kitty_protocol(self, buffer_setup):
        """Rapid typing with interleaved press/release should emit in order."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[104u\x1b[104;1:3u\x1b[105u\x1b[105;1:3u")
        assert emitted == ["\x1b[104u", "\x1b[104;1:3u", "\x1b[105u", "\x1b[105;1:3u"]


class TestMouseEvents:
    """Test handling of mouse events."""

    def test_handle_mouse_press_event(self, buffer_setup):
        """Mouse press events should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<0;10;5M")
        assert emitted == ["\x1b[<0;10;5M"]

    def test_handle_mouse_release_event(self, buffer_setup):
        """Mouse release events should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<0;10;5m")
        assert emitted == ["\x1b[<0;10;5m"]

    def test_handle_mouse_move_event(self, buffer_setup):
        """Mouse move events should be emitted."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35;20;5m")
        assert emitted == ["\x1b[<35;20;5m"]

    def test_handle_split_mouse_events(self, buffer_setup):
        """Mouse events split across feeds should complete and emit."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<3")
        buffer.feed(b"5;1")
        buffer.feed(b"5;")
        buffer.feed(b"10m")
        assert emitted == ["\x1b[<35;15;10m"]

    def test_handle_multiple_mouse_events(self, buffer_setup):
        """Multiple mouse events should each emit."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35;1;1m\x1b[<35;2;2m\x1b[<35;3;3m")
        assert emitted == ["\x1b[<35;1;1m", "\x1b[<35;2;2m", "\x1b[<35;3;3m"]

    def test_handle_old_style_mouse_sequence(self, buffer_setup):
        """Old-style mouse sequences (ESC[M + 3 bytes) should be handled."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[M abc")
        assert emitted == ["\x1b[M ab", "c"]

    def test_buffer_incomplete_old_style_mouse_sequence(self, buffer_setup):
        """Incomplete old-style mouse sequences should be buffered."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[M")
        assert buffer.get_buffer() == "\x1b[M"

        buffer.feed(b" a")
        assert buffer.get_buffer() == "\x1b[M a"

        buffer.feed(b"b")
        assert emitted == ["\x1b[M ab"]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_handle_empty_input(self, buffer_setup):
        """Empty input emits an empty-string data event (stdin-buffer.ts:302-311)."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"")
        assert emitted == [""]

    def test_handle_lone_escape_character_with_timeout(self, buffer_setup):
        """Lone ESC character should emit after timeout."""
        buffer = buffer_setup["buffer"]
        timer = buffer_setup["timer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b")
        assert emitted == []

        # Advance time past timeout
        timer.advance(15)
        assert emitted == ["\x1b"]

    def test_handle_lone_escape_character_with_explicit_flush(self, buffer_setup):
        """Lone ESC character should emit when explicitly flushed."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b")
        assert emitted == []

        flushed = buffer.flush()
        assert flushed == ["\x1b"]

    def test_handle_buffer_input(self, buffer_setup):
        """Should handle bytes input."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[A")
        assert emitted == ["\x1b[A"]

    def test_handle_very_long_sequences(self, buffer_setup):
        """Very long sequences should be handled."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        long_seq = "\x1b[" + "1;" * 50 + "H"
        buffer.feed(long_seq.encode())
        assert emitted == [long_seq]


class TestFlush:
    """Test manual flush functionality."""

    def test_flush_incomplete_sequences(self, buffer_setup):
        """Incomplete sequences should be returned by flush."""
        buffer = buffer_setup["buffer"]

        buffer.feed(b"\x1b[<35")
        flushed = buffer.flush()
        assert flushed == ["\x1b[<35"]
        assert buffer.get_buffer() == ""

    def test_return_empty_array_if_nothing_to_flush(self, buffer_setup):
        """Flush should return empty list if nothing buffered."""
        buffer = buffer_setup["buffer"]

        flushed = buffer.flush()
        assert flushed == []

    def test_emit_flushed_data_via_timeout(self, buffer_setup):
        """Data flushed via timeout should be emitted."""
        buffer = buffer_setup["buffer"]
        timer = buffer_setup["timer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35")
        assert emitted == []

        # Advance time past timeout
        timer.advance(15)

        assert emitted == ["\x1b[<35"]


class TestClear:
    """Test clear functionality."""

    def test_clear_buffered_content_without_emitting(self, buffer_setup):
        """Clear should remove buffered content without emitting."""
        buffer = buffer_setup["buffer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35")
        assert buffer.get_buffer() == "\x1b[<35"

        buffer.clear()
        assert buffer.get_buffer() == ""
        assert emitted == []


class TestBracketedPaste:
    """Test bracketed paste mode handling.

    Deviation from upstream (per the phase-3 plan, Task 3 Produces — a hard,
    mandated contract, not a translation choice): upstream's
    stdin-buffer.test.ts asserts pastes arrive on a *separate* ``"paste"``
    event with the ``ESC[200~``/``ESC[201~`` markers already stripped. This
    port instead delivers bracketed paste as a single frame through the
    *same* ``on_frame`` channel as every other frame, with both markers
    preserved in the frame text — downstream ``Editor.handle_input`` detects
    a paste by scanning for those markers rather than via a second callback.
    These tests assert that single-channel, marker-preserving contract
    directly against ``emitted_sequences`` instead of upstream's
    ``emitted_paste``.
    """

    PASTE_START = "\x1b[200~"
    PASTE_END = "\x1b[201~"

    def test_emit_complete_bracketed_paste_as_single_marker_wrapped_frame(self, buffer_setup):
        """Complete bracketed paste should arrive as one on_frame call, markers intact."""
        buffer = buffer_setup["buffer"]
        emitted_sequences = buffer_setup["emitted_sequences"]

        content = "hello world"

        buffer.feed((self.PASTE_START + content + self.PASTE_END).encode())

        assert emitted_sequences == [self.PASTE_START + content + self.PASTE_END]

    def test_handle_paste_arriving_in_chunks_still_one_frame(self, buffer_setup):
        """Paste arriving in multiple feed() chunks should still collapse to one frame."""
        buffer = buffer_setup["buffer"]
        emitted_sequences = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[200~")
        assert emitted_sequences == []

        buffer.feed(b"hello ")
        assert emitted_sequences == []

        buffer.feed(b"world\x1b[201~")
        assert emitted_sequences == [self.PASTE_START + "hello world" + self.PASTE_END]

    def test_handle_paste_with_input_before_and_after(self, buffer_setup):
        """Paste with regular input before and after should emit as three ordered frames."""
        buffer = buffer_setup["buffer"]
        emitted_sequences = buffer_setup["emitted_sequences"]

        buffer.feed(b"a")
        buffer.feed(b"\x1b[200~pasted\x1b[201~")
        buffer.feed(b"b")

        assert emitted_sequences == ["a", self.PASTE_START + "pasted" + self.PASTE_END, "b"]

    def test_handle_paste_with_newlines(self, buffer_setup):
        """Paste content with newlines should be preserved, markers intact, one frame."""
        buffer = buffer_setup["buffer"]
        emitted_sequences = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[200~line1\nline2\nline3\x1b[201~")

        assert emitted_sequences == [self.PASTE_START + "line1\nline2\nline3" + self.PASTE_END]

    def test_handle_paste_with_unicode(self, buffer_setup):
        """Paste content with unicode should be handled, markers intact, one frame."""
        buffer = buffer_setup["buffer"]
        emitted_sequences = buffer_setup["emitted_sequences"]

        content = "Hello 世界 🎉"
        buffer.feed((f"\x1b[200~{content}\x1b[201~").encode("utf-8"))

        assert emitted_sequences == [self.PASTE_START + content + self.PASTE_END]


class TestDestroy:
    """Test destroy/cleanup functionality."""

    def test_clear_buffer_on_destroy(self, buffer_setup):
        """Destroy should clear buffer."""
        buffer = buffer_setup["buffer"]

        buffer.feed(b"\x1b[<35")
        assert buffer.get_buffer() == "\x1b[<35"

        buffer.destroy()
        assert buffer.get_buffer() == ""

    def test_clear_pending_timeouts_on_destroy(self, buffer_setup):
        """Destroy should clear pending timeouts."""
        buffer = buffer_setup["buffer"]
        timer = buffer_setup["timer"]
        emitted = buffer_setup["emitted_sequences"]

        buffer.feed(b"\x1b[<35")
        buffer.destroy()

        # Advance time past timeout
        timer.advance(15)

        # Should not have emitted anything
        assert emitted == []
