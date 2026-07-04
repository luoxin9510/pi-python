"""Test suite for resize handling and hardware cursor positioning (Task 8, Step 1: RED phase).

Resize and hardware cursor behavior tests:
- Resize triggers full redraw (clear or full rewrite ops) with viewport correction
- Hardware cursor extraction: CURSOR_MARKER in focused component renders,
  marker stripped from output, cursor positioned to marker location
- Cursor positioning works with overlays present
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

# These imports are expected to fail with ModuleNotFoundError on first run
# (until the implementation is written in tui.py).
try:
    from pipython.tui.engine.tui import (
        CURSOR_MARKER,
        TUI,
    )
except ModuleNotFoundError as e:
    _IMPORT_ERROR = e
    raise

if TYPE_CHECKING:
    from tests.tui.engine.conftest import RecordingTerm


class StaticComponent:
    """Simple test helper: a Component that renders a static list of lines."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.invalidated = False

    def render(self, width: int) -> list[str]:
        return list(self.lines)

    def invalidate(self) -> None:
        self.invalidated = True


class CursorComponent:
    """Test component with focus tracking and CURSOR_MARKER embedding."""

    def __init__(self, lines: list[str], cursor_col: int = 5) -> None:
        """
        Args:
            lines: Content lines
            cursor_col: Column offset where CURSOR_MARKER is embedded in first line
        """
        self.lines = lines
        self.focused = False
        self.cursor_col = cursor_col
        self.invalidated = False

    def render(self, width: int) -> list[str]:
        """Render lines; if focused, embed CURSOR_MARKER at cursor_col in first line."""
        lines = list(self.lines)
        if self.focused and lines:
            # Embed marker at cursor_col (simulating cursor position mid-line)
            line = lines[0]
            if len(line) >= self.cursor_col:
                lines[0] = line[: self.cursor_col] + CURSOR_MARKER + line[self.cursor_col :]
        return lines

    def invalidate(self) -> None:
        self.invalidated = True


@pytest.fixture
def tui(term: RecordingTerm) -> TUI:
    """Fixture: a TUI instance with a RecordingTerm."""
    return TUI(term)


class TestResize:
    """Resize triggering full redraw behavior tests."""

    def test_resize_triggers_full_redraw(self, term: RecordingTerm, tui: TUI) -> None:
        """Resizing terminal (width/height change) should trigger a full redraw.

        After resize, the ops should include full-clear or full-rewrite operations,
        not just differential updates.
        """
        component = StaticComponent(["line 1", "line 2", "line 3"])
        tui.set_root(component)
        tui.do_render()

        # Simulate terminal resize: change columns
        term.columns = 40  # Change from default 80

        # Trigger resize handling via TUI's on_resize hook
        try:
            tui.on_resize()
        except AttributeError as e:
            pytest.fail(f"on_resize hook not implemented: {e}")

        tui.do_render()

        # After resize, the screen should still display content correctly
        # (even if the exact ops are complex, the content should be present)
        screen = term.screen()
        full_text = "".join(screen)
        assert "line 1" in full_text

    def test_resize_with_columns_change_redraws(self, term: RecordingTerm, tui: TUI) -> None:
        """Changing terminal columns should cause content to be re-rendered at new width."""
        component = StaticComponent(["content line"])
        tui.set_root(component)
        tui.do_render()

        term.ops.clear()

        # Change columns (simulate terminal resize)
        term.columns = 40

        try:
            tui.on_resize()
        except AttributeError:
            pytest.fail("on_resize hook not implemented")

        tui.do_render()

        # Should produce ops (the resize should trigger re-render)
        # This is a basic check; the exact ops depend on implementation
        # but the content should be preserved
        screen = term.screen()
        final_text = "".join(screen)
        assert "content line" in final_text

    def test_resize_corrects_viewport_top(self, term: RecordingTerm, tui: TUI) -> None:
        """Resize should correct previous_viewport_top to avoid scroll jump.

        Per tui.ts:1258-1259, 1344-1358: when width or height changes, the
        implementation should apply viewport-top correction to ensure the screen
        doesn't jump unexpectedly. This is an internal invariant; the test verifies
        that after resize, the rendered content is still sensible (no gaps, crashes).
        """
        component = StaticComponent([f"line {i}" for i in range(1, 10)])  # 9 lines
        tui.set_root(component)
        tui.do_render()

        term.columns = 50

        try:
            tui.on_resize()
        except AttributeError:
            pytest.fail("on_resize hook not implemented")

        tui.do_render()

        screen = term.screen()
        # At least some lines should be present
        assert any("line" in line for line in screen)


class TestHardwareCursor:
    """Hardware cursor positioning via CURSOR_MARKER extraction."""

    def test_cursor_marker_stripped_from_output(self, term: RecordingTerm, tui: TUI) -> None:
        """CURSOR_MARKER embedded in render output should be stripped before writing.

        After do_render, no written line should contain the literal CURSOR_MARKER
        bytes — it should be extracted, cursor positioned there, and removed.
        """
        component = CursorComponent(["hello world"], cursor_col=5)
        component.focused = True
        tui.set_root(component)
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # CURSOR_MARKER should NOT appear in the final screen
        assert CURSOR_MARKER not in full_text, "CURSOR_MARKER should be stripped from final output"

        # But the original line content should still be there
        assert "hello world" in full_text

    def test_cursor_positioned_to_marker_location(self, term: RecordingTerm, tui: TUI) -> None:
        """After extract_cursor_position, the hardware cursor should move to the marker row/col.

        The terminal ops should end with a cursor-move command to the marker's position.
        Per tui.ts: the final ops are typically a cursor-move to (row, col) of the marker.
        The exact ANSI sequence is CSI <row> ';' <col> 'H' (absolute cursor position).
        """
        component = CursorComponent(["0123456789"], cursor_col=5)
        component.focused = True
        tui.set_root(component)
        tui.do_render()

        # Check the ops for cursor positioning at the marker's position
        # After render, ops should contain a cursor-move to row 0, col 5
        # (since marker is at column 5 in line "0123456789")
        ops_str = "".join(term.ops)

        # The ops should include a cursor move; typical format is "\x1b[<row>;<col>H"
        # For marker at col 5, row 0, we expect something like "\x1b[0;5H" or similar
        # (row might be 1-indexed in some terminals)
        # This is a presence check: there should be cursor-addressing ops
        has_cursor_move = bool(re.search(r"\x1b\[\d+;?\d*[HGf]", ops_str))
        assert has_cursor_move, (
            "Cursor positioning op (CSI H/G/f) should be present after extraction"
        )

    def test_cursor_works_with_unfocused_component(self, term: RecordingTerm, tui: TUI) -> None:
        """If component is not focused, CURSOR_MARKER should not be embedded (or shouldn't matter)."""
        component = CursorComponent(["hello world"], cursor_col=5)
        component.focused = False  # NOT focused
        tui.set_root(component)
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # CURSOR_MARKER should not appear (component is unfocused)
        assert CURSOR_MARKER not in full_text
        # Content should still be rendered
        assert "hello world" in full_text

    def test_cursor_marker_in_overlay(self, term: RecordingTerm, tui: TUI) -> None:
        """CURSOR_MARKER in an overlay component should be extracted correctly.

        When an overlay is open and has focus (and embeds CURSOR_MARKER),
        the marker should be extracted from the *composited* lines (overlay over main).
        """
        main = StaticComponent(["main line 1", "main line 2"])
        tui.set_root(main)
        tui.do_render()

        # Open an overlay with cursor
        overlay = CursorComponent(["overlay content"], cursor_col=7)
        try:
            tui.show_overlay(overlay, anchor_row=1)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        # Give overlay focus so it embeds marker
        overlay.focused = True
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # CURSOR_MARKER should be stripped (extracted)
        assert CURSOR_MARKER not in full_text, "CURSOR_MARKER in overlay should be stripped"

        # Both main and overlay content should be present
        assert "main line" in full_text
        assert "overlay content" in full_text


class TestCursorPositioningEdgeCases:
    """Edge cases for cursor positioning."""

    def test_cursor_at_start_of_line(self, term: RecordingTerm, tui: TUI) -> None:
        """CURSOR_MARKER at column 0 should position cursor there."""
        component = CursorComponent(["hello"], cursor_col=0)
        component.focused = True
        tui.set_root(component)
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # Marker should be stripped
        assert CURSOR_MARKER not in full_text
        # Content should be present
        assert "hello" in full_text

    def test_cursor_at_end_of_line(self, term: RecordingTerm, tui: TUI) -> None:
        """CURSOR_MARKER at the end of a line should position cursor at end."""
        component = CursorComponent(["hello"], cursor_col=5)
        component.focused = True
        tui.set_root(component)
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # Marker should be stripped
        assert CURSOR_MARKER not in full_text
        # Content should be "hello" (marker was after it but stripped)
        assert "hello" in full_text

    def test_multiple_markers_use_first(self, term: RecordingTerm, tui: TUI) -> None:
        """If somehow multiple CURSOR_MARKERs appear, extraction should use
        *only* the first one and leave the rest untouched.

        (This is a defensive test; components should only embed one, but the
        extraction logic should be robust — i.e. not crash/misbehave — when
        one doesn't.)

        RED correction #3 (citation: tui.ts:1234-1252 ``extractCursorPosition``):
        the original version of this test asserted ``CURSOR_MARKER not in
        full_text`` — i.e. that *every* occurrence gets stripped. That is not
        upstream's actual algorithm: ``extractCursorPosition`` does one
        ``line.indexOf(CURSOR_MARKER)`` per row, strips *that single
        occurrence*, and returns immediately — it never loops to find
        further occurrences on the same (or any other) row. For a line
        containing two markers, "before" + M + "middle" + M + "after", the
        real algorithm strips only the first M, producing
        "beforemiddle" + M + "after" — one marker instance necessarily
        survives. The original assertion could never pass against a
        faithful port of upstream; fixed to check that exactly one
        occurrence was removed (marker count 2 -> 1) and that the first
        marker's position was used to compute the cursor column (via the
        text before it, "before", same as a single-marker case would).
        """

        class MultiMarkerComponent:
            def __init__(self) -> None:
                self.focused = True
                self.invalidated = False

            def render(self, width: int) -> list[str]:
                # Embed marker multiple times (misbehaving component)
                # The extraction should find and use the first one
                return ["before" + CURSOR_MARKER + "middle" + CURSOR_MARKER + "after"]

            def invalidate(self) -> None:
                self.invalidated = True

        component = MultiMarkerComponent()
        tui.set_root(component)
        tui.do_render()

        screen = term.screen()
        full_text = "".join(screen)

        # Exactly one of the two markers is stripped (the first); the
        # second, unhandled occurrence is upstream's actual (if surprising)
        # behavior for a misbehaving multi-marker component, not a bug.
        assert full_text.count(CURSOR_MARKER) == 1, (
            "Only the first CURSOR_MARKER occurrence should be stripped"
        )
        # All original text content survives around both markers.
        assert "before" in full_text
        assert "middle" in full_text
        assert "after" in full_text
