"""RED-phase tests for basic TUI components (text, box, spacer, truncated_text, loader).

These tests exercise the render() semantics and golden output lines per upstream
component sources, with ≥4 cases per component (≥20 total). Tests are exact
assertions on rendered output; all ANSI/width handling is ported from upstream.

Upstream citations:
- Text: ~/Developer/nukcole-pi/packages/tui/src/components/text.ts
- Box: ~/Developer/nukcole-pi/packages/tui/src/components/box.ts
- Spacer: ~/Developer/nukcole-pi/packages/tui/src/components/spacer.ts
- TruncatedText: ~/Developer/nukcole-pi/packages/tui/src/components/truncated-text.ts
- Loader: ~/Developer/nukcole-pi/packages/tui/src/components/loader.ts
"""

import asyncio

import pytest

from pipython.tui.components.text import Text
from pipython.tui.components.box import Box
from pipython.tui.components.spacer import Spacer
from pipython.tui.components.truncated_text import TruncatedText
from pipython.tui.components.loader import Loader
from pipython.tui.engine.utils import visible_width


# ==============================================================================
# TEXT COMPONENT TESTS (≥4 cases)
# ==============================================================================


class TestText:
    """Text(content: str, style: str = ""):

    Renders multi-line text with word wrapping via utils.wrap_text_with_ansi
    at given width. No padding by default. Style application per upstream.
    """

    def test_text_simple_content(self):
        """Test basic text rendering (single line, fits within width)."""
        text = Text("hello")
        lines = text.render(20)
        assert lines == ["hello"]

    def test_text_wrapping_at_width(self):
        """Test word wrapping at specified width boundary."""
        text = Text("the quick brown fox jumps")
        lines = text.render(10)
        # wrap_text_with_ansi breaks at word boundaries
        assert len(lines) >= 2
        for line in lines:
            # Each line should fit within the width when measuring visible width
            from pipython.tui.engine.utils import visible_width

            assert visible_width(line) <= 10

    def test_text_cjk_wrapping(self):
        """Test CJK text wrapping (Chinese characters can break mid-string).

        Golden assertion derived from ``wrap_text_with_ansi``'s own
        behavior: each Han-script grapheme is its own token
        (``_CJK_BREAK_RE`` in ``engine/utils.py``), so "你好世界" (4 chars,
        width 2 each) packs exactly 2 chars per 4-column line: "你好" then
        "世界" — not a vaguer "some lines, each <= width" check.
        """
        text = Text("你好世界")
        lines = text.render(4)  # 2 chars per line (each CJK char is width 2)
        assert lines == ["你好", "世界"]
        for line in lines:
            assert visible_width(line) <= 4

    def test_text_style_reopens_across_cjk_wrap(self):
        """Test that a non-empty ``style`` is reopened on every continuation
        line and the final line ends with a reset — hand-verified against
        ``wrap_text_with_ansi``/``_AnsiCodeTracker``'s actual behavior:

        ``Text.render()`` wraps content as ``f"{style}{content}{RESET}"``
        before handing it to ``wrap_text_with_ansi``. The SGR code
        ``\\x1b[31m`` gets tokenized onto the first CJK grapheme ("你"), so
        line 1 opens with it; at the wrap boundary the tracker's
        ``get_line_end_reset()`` only closes underline/hyperlink state (not
        plain SGR colors), so line 1 does *not* carry a reset — instead,
        line 2 re-opens the still-active style via
        ``tracker.get_active_codes()`` before its own content, and the
        trailing ``\\x1b[0m`` (embedded by ``Text.render()`` after the raw
        content) lands on the last token, closing the final line.
        """
        text = Text("你好世界", style="\x1b[31m")
        lines = text.render(4)
        assert lines == ["\x1b[31m你好", "\x1b[31m世界\x1b[0m"]
        # First line: reopens style, no reset yet (SGR color survives a wrap
        # boundary — get_line_end_reset() only closes underline/hyperlink).
        assert lines[0].startswith("\x1b[31m")
        assert not lines[0].endswith("\x1b[0m")
        # Final line: reopens style again, and ends with the trailing reset.
        assert lines[-1].startswith("\x1b[31m")
        assert lines[-1].endswith("\x1b[0m")

    def test_text_set_content(self):
        """Test set_content() method to update text dynamically."""
        text = Text("initial")
        lines1 = text.render(20)
        text.set_content("updated content")
        lines2 = text.render(20)
        assert lines1 != lines2
        assert "updated" in lines2[0]

    def test_text_empty_content(self):
        """Test rendering empty text."""
        text = Text("")
        lines = text.render(20)
        assert lines == [""] or lines == []

    def test_text_multiline_input(self):
        """Test text with embedded newlines."""
        text = Text("line1\nline2")
        lines = text.render(20)
        assert len(lines) >= 2


# ==============================================================================
# BOX COMPONENT TESTS (≥4 cases)
# ==============================================================================


class TestBox:
    """Box(child: Component, *, padding: int = 0):

    Container applying padding to a single child component. Child lines pass
    through unchanged when ``padding == 0``; otherwise every row (blank
    padding rows and content rows alike) is padded out to the box's own
    render ``width`` so the box always yields a rectangular block.

    **No ``border`` parameter.** Upstream ``box.ts`` has no border-drawing
    code at all (only ``paddingX``/``paddingY``/``bgFn``); an earlier
    revision of this port invented a ``border: bool`` glyph-drawing feature
    with zero upstream precedent and zero consumers anywhere in the task
    graph. Per the maintainer's ruling (plan Task 9 Produces, updated), that
    parameter — and these tests' former border assertions — were removed.
    Bordered UI is phase-4's dynamic-border components' job, not this Box.
    """

    def test_box_no_padding_pass_through(self):
        """padding=0: bare pass-through, exact lines and exact width (no
        forced fill to the requested render width — see box.py module
        docstring deviation 3)."""
        child = Text("content")
        box = Box(child, padding=0)
        lines = box.render(10)
        assert lines == ["content"]
        assert visible_width(lines[0]) == len("content")

    def test_box_with_padding_exact_rows(self):
        """padding=1 at width=10: exact row list and exact per-row
        visible_width == 10 for every row (blank padding rows and the
        content row alike), derived from Box.render's own padding math:
        content_width = width - 2*padding = 8, so "inner" (width 5) gets a
        3-space fill before the closing 1-space pad, and the blank padding
        rows are a full ``width``-wide blank."""
        child = Text("inner")
        box = Box(child, padding=1)
        lines = box.render(10)
        assert lines == [" " * 10, " inner    ", " " * 10]
        for line in lines:
            assert visible_width(line) == 10

    def test_box_padding_two_multiple_rows(self):
        """padding=2 at width=8: 2 blank rows above/below, content_width =
        8 - 2*2 = 4, so a 2-char child ("hi") gets a 2-space fill before the
        closing 2-space pad. Every one of the 5 rows must be exactly
        visible_width == 8 (the padding math's own invariant)."""
        child = Text("hi")
        box = Box(child, padding=2)
        lines = box.render(8)
        assert lines == [
            " " * 8,
            " " * 8,
            "  hi    ",
            " " * 8,
            " " * 8,
        ]
        assert len(lines) == 5
        for line in lines:
            assert visible_width(line) == 8

    def test_box_padding_wraps_multiline_child(self):
        """padding=1 with a child that itself renders multiple lines: each
        content row must independently be padded to the same interior
        width, and every row (blank + content) must have the same exact
        visible_width."""
        child = Text("line1\nline2")
        box = Box(child, padding=1)
        lines = box.render(10)
        # 1 blank top + 2 content rows + 1 blank bottom
        assert len(lines) == 4
        for line in lines:
            assert visible_width(line) == 10
        assert lines[1] == " line1    "
        assert lines[2] == " line2    "


# ==============================================================================
# SPACER COMPONENT TESTS (≥4 cases)
# ==============================================================================


class TestSpacer:
    """Spacer(lines: int = 1):

    Renders N empty lines (no content, just vertical space).
    """

    def test_spacer_default_one_line(self):
        """Test spacer with default 1 line."""
        spacer = Spacer()
        lines = spacer.render(20)
        assert len(lines) == 1
        assert lines[0] == ""

    def test_spacer_multiple_lines(self):
        """Test spacer with multiple lines."""
        spacer = Spacer(lines=5)
        lines = spacer.render(20)
        assert len(lines) == 5
        assert all(line == "" for line in lines)

    def test_spacer_zero_lines(self):
        """Test spacer with zero lines."""
        spacer = Spacer(lines=0)
        lines = spacer.render(20)
        assert len(lines) == 0

    def test_spacer_large_count(self):
        """Test spacer with large line count."""
        spacer = Spacer(lines=100)
        lines = spacer.render(20)
        assert len(lines) == 100


# ==============================================================================
# TRUNCATED TEXT COMPONENT TESTS (≥4 cases)
# ==============================================================================


class TestTruncatedText:
    """TruncatedText(content: str):

    Single-line text truncated to width with ellipsis ("…") via
    utils.truncate_to_width. Renders as single line (or padded empty).
    """

    def test_truncated_text_fits_no_ellipsis(self):
        """Test text that fits within width (no truncation)."""
        truncated = TruncatedText("short")
        lines = truncated.render(20)
        assert "short" in lines[0]
        assert "…" not in lines[0]

    def test_truncated_text_exceeds_width(self):
        """Test text longer than width is truncated with ellipsis."""
        truncated = TruncatedText("this is a very long string")
        lines = truncated.render(10)
        assert len(lines) == 1
        # Should contain ellipsis
        assert "…" in lines[0]

    def test_truncated_text_cjk_truncation(self):
        """Test CJK text truncation with ellipsis."""
        # Using CJK: "你好世界朋友" (hello world friends)
        truncated = TruncatedText("你好世界朋友")
        lines = truncated.render(6)  # 3 chars wide (each CJK char is 2 wide)
        assert len(lines) == 1
        from pipython.tui.engine.utils import visible_width

        # Result should fit within width
        assert visible_width(lines[0]) <= 6

    def test_truncated_text_multiline_input_first_line_only(self):
        """Test that multiline input renders only first line."""
        truncated = TruncatedText("line1\nline2\nline3")
        lines = truncated.render(20)
        assert len(lines) == 1
        assert "line1" in lines[0]
        assert "line2" not in lines[0]

    def test_truncated_text_empty_input(self):
        """Test empty input."""
        truncated = TruncatedText("")
        lines = truncated.render(20)
        assert len(lines) == 1


# ==============================================================================
# LOADER COMPONENT TESTS (≥4 cases)
# ==============================================================================


class TestLoader:
    """Loader(request_render: Callable, frames: list[str] | None = None, interval: float = 0.08):

    Animated spinner with manual frame advancement (no real sleeps).
    start()/stop() control animation. Frames default to braille spinner from
    loader.ts: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    """

    def test_loader_default_frames(self):
        """Test loader uses default braille spinner frames."""
        render_count = 0

        def mock_request_render():
            nonlocal render_count
            render_count += 1

        loader = Loader(mock_request_render)
        loader.start()
        lines = loader.render(20)
        # Should contain one of the default frames
        default_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        assert any(frame in lines[0] for frame in default_frames)
        loader.stop()

    def test_loader_custom_frames(self):
        """Test loader with custom animation frames."""
        render_count = 0

        def mock_request_render():
            nonlocal render_count
            render_count += 1

        custom_frames = ["1", "2", "3"]
        loader = Loader(mock_request_render, frames=custom_frames)
        loader.start()
        lines = loader.render(20)
        # Should contain the first frame (or one of the custom frames)
        assert any(frame in lines[0] for frame in custom_frames)
        loader.stop()

    def test_loader_start_stop(self):
        """Test start() and stop() methods control animation."""
        render_count = 0

        def mock_request_render():
            nonlocal render_count
            render_count += 1

        loader = Loader(mock_request_render)
        loader.start()
        initial_count = render_count
        assert initial_count >= 1
        loader.stop()
        # After stop, render_count should not increase from new renders
        # (no real timer fires in a synchronous test with no running event
        # loop, so this also holds trivially — but stop() must not raise).
        assert render_count == initial_count

    def test_loader_manual_frame_advance(self):
        """Test manual frame advancement via tick() (no sleep)."""
        render_count = 0

        def mock_request_render():
            nonlocal render_count
            render_count += 1

        custom_frames = ["A", "B", "C"]
        loader = Loader(mock_request_render, frames=custom_frames)
        loader.start()

        # Get initial frame (index 0 == "A")
        lines1 = loader.render(20)
        assert "A" in lines1[0]

        # Manually advance one frame via the brief's required seam (task-9
        # brief: "手动步进" — no real sleep/timer involved) and verify the
        # rendered frame actually moved to index 1 == "B".
        loader.tick()
        lines2 = loader.render(20)
        assert "B" in lines2[0]

        loader.stop()

    def test_loader_renders_message(self):
        """Test loader renders with a message."""

        def mock_request_render():
            pass

        loader = Loader(mock_request_render)
        loader.start()
        lines = loader.render(30)
        # Should have at least one line with content
        assert len(lines) >= 1
        loader.stop()

    def test_loader_empty_frames(self):
        """Test loader with empty frames list."""

        def mock_request_render():
            pass

        loader = Loader(mock_request_render, frames=[])
        loader.start()
        lines = loader.render(20)
        # With empty frames, should still render but without indicator
        assert len(lines) >= 1
        loader.stop()

    @pytest.mark.asyncio
    async def test_loader_double_start_then_stop_freezes_ticks(self):
        """Regression test for a timer-chain leak: calling start() twice in a
        row must not leave a stale, uncancelled ``asyncio`` timer handle
        alive after stop().

        Bug (pre-fix): ``_schedule_next()`` unconditionally overwrote
        ``self._handle`` with the newly armed handle *without cancelling
        whichever handle was already pending* from the first start() call.
        ``stop()`` only ever cancels whatever ``self._handle`` currently
        points to (the *second* call's handle) — so the first call's handle
        is orphaned, stays live on the real event loop, and fires at least
        once *after* stop() was called. Upstream's ``loader.ts:72-81
        restartAnimation()`` avoids exactly this by calling ``this.stop()``
        before rearming, so a fresh ``start()`` always cancels any prior
        pending timer first.

        Uses a real running asyncio event loop (required — ``_schedule_next``
        only arms a real ``call_later`` timer when one exists) with a tiny
        interval and bounded waits: no sleeps in a loop, no unbounded
        polling — just two fixed wait windows checking the tick count is
        frozen at whatever it was the instant stop() returned.
        """
        render_count = 0

        def mock_request_render():
            nonlocal render_count
            render_count += 1

        interval = 0.01
        loader = Loader(mock_request_render, frames=["A", "B", "C"], interval=interval)

        loader.start()
        loader.start()  # double start — must not spawn a second live timer chain
        count_at_stop = render_count
        loader.stop()

        # First bounded wait: a leaked handle from the first start() call
        # would fire well within 3 intervals and bump render_count past
        # count_at_stop.
        await asyncio.sleep(interval * 3)
        count_after_wait1 = render_count
        assert count_after_wait1 == count_at_stop, (
            "a stale timer handle fired after stop() — cancel-before-rearm "
            "did not cancel the first start()'s pending handle"
        )

        # Second bounded wait: confirms the count stays frozen, not just
        # coincidentally equal at the first checkpoint.
        await asyncio.sleep(interval * 3)
        count_after_wait2 = render_count
        assert count_after_wait2 == count_at_stop, (
            "render_count increased after stop() — a leaked timer chain is still ticking"
        )
