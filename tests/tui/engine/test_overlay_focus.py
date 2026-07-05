"""Test suite for overlay compositing and focus chain (Task 8, Step 1: RED phase).

Overlay and focus-chain behavior tests:
- Overlay display/close with line compositing
- Focus chain: overlay auto-steals focus, close restores prior
- Nested overlays: two-layer stack (open A, B → close B → A → root)
- Out-of-order closes: open A, B → close A first (focus back to root), then B
- Focus restoration follows upstream tui.ts focus-restore state machine
  (tui.ts:366-620, esp. retarget behavior when closing overlays)

RED correction #2 (citations: tui.ts:301 ``private focusedComponent: Component
| null = null;`` and tui.ts:497 ``showOverlay``'s ``preFocus: this.focusedComponent``):
the four focus-chain tests below originally established "root/main already
has focus" by poking the test component's own ``.focused`` attribute directly
(``main.focused = True``) *without* ever calling ``tui.set_focus(main)``.
Upstream's ``showOverlay`` captures ``preFocus`` from its own internal
``focusedComponent`` bookkeeping, not from any component's ``.focused``
flag — a component's ``.focused`` is a write-only *effect* TUI applies, never
a signal TUI reads back. Since ``focusedComponent`` starts ``null`` and only
``setFocus`` (Python: ``TUI.set_focus``) ever assigns it, a test that sets
``.focused`` directly leaves the TUI-side bookkeeping at ``None`` — so
``show_overlay``'s ``pre_focus`` capture silently records "nothing was
focused" instead of "root/main was focused", and the focus-restore-on-close
assertions the tests exist to check would trivially "pass" for the wrong
reason (restoring to ``None`` looks the same as `not root.focused` either
way) or fail outright once ``show_overlay`` actually implements focus-stealing
(the component's own ``.focused`` never got cleared, because TUI never knew
it needed to clear it — this is exactly what was observed: ``main``/``root``
kept ``.focused == True`` even after the overlay opened). Fixed by calling
``tui.set_focus(main)``/``tui.set_focus(root)`` instead, which both flips the
attribute *and* correctly seeds TUI's own ``_focused`` field.
"""

from __future__ import annotations

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


class FocusableComponent:
    """Test component that tracks focus state and optionally emits CURSOR_MARKER."""

    def __init__(self, lines: list[str], has_cursor: bool = False) -> None:
        self.lines = lines
        self.focused = False
        self.has_cursor = has_cursor
        self.invalidated = False

    def render(self, width: int) -> list[str]:
        """Render lines; if focused and has_cursor, embed CURSOR_MARKER in first line."""
        lines = list(self.lines)
        if self.focused and self.has_cursor and lines:
            # Embed marker mid-line (simulating cursor position)
            lines[0] = lines[0][:5] + CURSOR_MARKER + lines[0][5:]
        return lines

    def invalidate(self) -> None:
        self.invalidated = True


@pytest.fixture
def tui(term: RecordingTerm) -> TUI:
    """Fixture: a TUI instance with a RecordingTerm."""
    return TUI(term)


class TestOverlayCompositing:
    """Overlay display/close and line compositing behavior tests."""

    def test_overlay_shown_composites_over_main(self, term: RecordingTerm, tui: TUI) -> None:
        """Opening an overlay should composite its lines over the main content."""
        main = StaticComponent(["main line 1", "main line 2", "main line 3"])
        tui.set_root(main)
        tui.do_render()

        # Now open an overlay at row 1
        overlay = StaticComponent(["overlay line 1", "overlay line 2"])
        try:
            tui.show_overlay(overlay, anchor_row=1)
        except AttributeError as e:
            pytest.fail(f"show_overlay not implemented: {e}")

        tui.do_render()
        screen = term.screen()
        full_text = "".join(screen)

        # Both main and overlay content should be present
        assert "main line 1" in full_text
        assert "overlay line 1" in full_text
        assert "overlay line 2" in full_text

    def test_overlay_close_removes_overlay_lines(self, term: RecordingTerm, tui: TUI) -> None:
        """Closing an overlay should remove it from screen (no longer composited)."""
        main = StaticComponent(["main line 1", "main line 2", "main line 3"])
        tui.set_root(main)
        tui.do_render()

        overlay = StaticComponent(["overlay line X"])
        try:
            handle = tui.show_overlay(overlay, anchor_row=1)
        except AttributeError as e:
            pytest.fail(f"show_overlay not implemented: {e}")

        tui.do_render()
        screen_with_overlay = term.screen()
        overlay_text = "".join(screen_with_overlay)
        assert "overlay line X" in overlay_text

        # Close the overlay
        try:
            handle.close()
        except AttributeError as e:
            pytest.fail(f"OverlayHandle.close not implemented: {e}")

        tui.do_render()
        screen_without_overlay = term.screen()
        final_text = "".join(screen_without_overlay)
        assert "overlay line X" not in final_text
        assert "main line 1" in final_text


class TestFocusChain:
    """Focus chain behavior: overlay auto-steals focus, close restores prior."""

    def test_overlay_steals_focus(self, term: RecordingTerm, tui: TUI) -> None:
        """Opening an overlay should set its .focused to True and steal focus from root."""
        main = FocusableComponent(["main content"], has_cursor=True)
        tui.set_focus(main)  # Root starts with focus (RED correction #2, see below)
        tui.set_root(main)
        tui.do_render()

        overlay = FocusableComponent(["overlay content"], has_cursor=True)
        try:
            tui.show_overlay(overlay, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        # After opening overlay, it should have focus and main should not
        assert overlay.focused, "Overlay should steal focus"
        assert not main.focused, "Root should lose focus when overlay opens"

    def test_close_restores_previous_focus(self, term: RecordingTerm, tui: TUI) -> None:
        """Closing an overlay should restore focus to the component that had it before."""
        main = FocusableComponent(["main content"], has_cursor=True)
        tui.set_focus(main)  # RED correction #2, see module docstring
        tui.set_root(main)
        tui.do_render()

        overlay = FocusableComponent(["overlay content"], has_cursor=True)
        try:
            handle = tui.show_overlay(overlay, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        assert overlay.focused and not main.focused

        # Close the overlay
        try:
            handle.close()
        except AttributeError:
            pytest.fail("OverlayHandle.close not implemented")

        # Focus should restore to main
        assert not overlay.focused, "Overlay should lose focus after close"
        assert main.focused, "Root should regain focus when overlay closes"

    def test_nested_overlays_two_layer_fifo_close(self, term: RecordingTerm, tui: TUI) -> None:
        """Two-layer overlay stack: open A, B → close B (focus back to A) → close A (back to root).

        Tests nested overlay stack behavior per tui.ts focus-restore state machine.
        """
        root = FocusableComponent(["root"], has_cursor=True)
        tui.set_focus(root)  # RED correction #2, see module docstring
        tui.set_root(root)
        tui.do_render()

        # Open overlay A
        overlay_a = FocusableComponent(["overlay A"], has_cursor=True)
        try:
            handle_a = tui.show_overlay(overlay_a, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        assert overlay_a.focused and not root.focused, "A should have focus after open"

        # Open overlay B (on top of A)
        overlay_b = FocusableComponent(["overlay B"], has_cursor=True)
        try:
            handle_b = tui.show_overlay(overlay_b, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        assert overlay_b.focused, "B should have focus after open"
        assert not overlay_a.focused, "A should lose focus when B opens"
        assert not root.focused, "Root should still not have focus"

        # Close B (top of stack) — focus should restore to A
        try:
            handle_b.close()
        except AttributeError:
            pytest.fail("OverlayHandle.close not implemented")

        assert not overlay_b.focused, "B should lose focus after close"
        assert overlay_a.focused, "A should regain focus when B closes"
        assert not root.focused, "Root should still not have focus"

        # Close A — focus should restore to root
        try:
            handle_a.close()
        except AttributeError:
            pytest.fail("OverlayHandle.close not implemented")

        assert not overlay_a.focused, "A should lose focus after close"
        assert root.focused, "Root should regain focus when A closes"

    def test_nested_overlays_out_of_order_close(self, term: RecordingTerm, tui: TUI) -> None:
        """Out-of-order close: open A, B → close A first → close B.

        Per tui.ts focus-restore state machine (lines 366-620), closing A (the
        bottom overlay, not the top of stack) should retarget focus based on the
        state machine's prior-focus chain: since B is still open when A closes,
        focus remains on B (the current top of stack). When B closes, focus goes
        to root.

        Derivation from tui.ts:
        - Overlay state machine maintains a focus-chain stack (lines 406-414).
        - When an overlay closes, it pops from the chain.
        - If the closing overlay had focus and there's a prior focusable in the
          chain, focus transfers to it; else to root (lines 502-515, focus-restore
          logic in retarget/collapse operations).
        - Closing a non-top overlay (like A when B is on top) should not crash;
          the focus remains on the current focus holder (B) because B is still
          active (lines 366-380, stack invariant).
        """
        root = FocusableComponent(["root"], has_cursor=True)
        tui.set_focus(root)  # RED correction #2, see module docstring
        tui.set_root(root)
        tui.do_render()

        # Open overlay A
        overlay_a = FocusableComponent(["overlay A"], has_cursor=True)
        try:
            handle_a = tui.show_overlay(overlay_a, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        assert overlay_a.focused and not root.focused

        # Open overlay B (on top of A)
        overlay_b = FocusableComponent(["overlay B"], has_cursor=True)
        try:
            handle_b = tui.show_overlay(overlay_b, anchor_row=0)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        assert overlay_b.focused and not overlay_a.focused and not root.focused

        # Close A first (out of order — A is below B)
        # Per the state machine, since B is still on top, focus stays on B
        try:
            handle_a.close()
        except AttributeError:
            pytest.fail("OverlayHandle.close not implemented")

        # After closing A, focus should remain on B (still top of stack)
        assert overlay_b.focused, "B should retain focus when A (below it) closes"
        assert not overlay_a.focused, "A should be gone"
        assert not root.focused, "Root should not regain focus yet"

        # Close B
        try:
            handle_b.close()
        except AttributeError:
            pytest.fail("OverlayHandle.close not implemented")

        # Now focus should go to root
        assert not overlay_b.focused, "B should lose focus"
        assert root.focused, "Root should regain focus when all overlays close"


class TestNonCapturingOverlay:
    """Fix round 1 (Critical finding 1, citing upstream tui.ts:171-207
    ``OverlayOptions.nonCapturing`` / tui.ts:503 ``if (!options?.nonCapturing
    && this.isOverlayVisible(entry)) { this.setFocus(component); }``):
    ``show_overlay`` must support a way to display an overlay *without*
    stealing TUI-level focus from whatever was focused before — the
    mechanism Task 13's autocomplete overlay needs (its passive
    ``SelectList`` has no ``handle_input`` of its own; the real upstream
    editor never uses an overlay for its autocomplete list at all, so this
    port's own choice to route it through ``show_overlay`` — module
    docstring deviation 10 in ``editor.py`` — needs this port's own
    equivalent of ``nonCapturing`` to avoid a real deadlock: with focus
    silently stolen onto a component with no ``handle_input``,
    ``TUI.handle_input`` forwards every subsequent keystroke nowhere at
    all, forever)."""

    def test_non_capturing_overlay_does_not_steal_focus(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        main = FocusableComponent(["main content"], has_cursor=True)
        tui.set_focus(main)
        tui.set_root(main)
        tui.do_render()

        overlay = FocusableComponent(["overlay content"], has_cursor=True)
        tui.show_overlay(overlay, anchor_row=0, non_capturing=True)

        assert main.focused, "main must keep focus — a non-capturing overlay must not steal it"
        assert not overlay.focused, "a non-capturing overlay never receives focus at all"

    def test_non_capturing_overlay_still_composites_onto_screen(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        """Losing focus-stealing must not lose rendering — the overlay
        still needs to actually appear on screen, just without owning
        keyboard input."""
        main = StaticComponent(["main line 1", "main line 2"])
        tui.set_root(main)
        tui.do_render()

        overlay = StaticComponent(["overlay content"])
        tui.show_overlay(overlay, anchor_row=1, non_capturing=True)
        tui.do_render()

        full_text = "".join(term.screen())
        assert "overlay content" in full_text
        assert "main line 1" in full_text

    def test_handle_input_still_reaches_main_while_non_capturing_overlay_open(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        """The actual production bug this fix closes: with focus stolen
        onto an overlay that has no ``handle_input`` at all,
        ``TUI.handle_input`` silently no-ops forever — every keystroke
        after the overlay opens vanishes, deadlocking real input. A
        non-capturing overlay must leave ``tui.handle_input`` routing to
        whatever was already focused, completely unaffected by the
        overlay's own presence."""

        class InputCapturingComponent(FocusableComponent):
            def __init__(self, lines: list[str]) -> None:
                super().__init__(lines)
                self.received: list[str] = []

            def handle_input(self, data: str) -> None:
                self.received.append(data)

        main = InputCapturingComponent(["main content"])
        tui.set_focus(main)
        tui.set_root(main)
        tui.do_render()

        # An overlay with NO handle_input at all (like SelectList) — this
        # is exactly the shape that deadlocks tui.handle_input if focus is
        # stolen onto it.
        overlay = StaticComponent(["overlay content"])
        tui.show_overlay(overlay, anchor_row=0, non_capturing=True)

        tui.handle_input("x")
        assert main.received == ["x"], (
            "tui.handle_input must still reach main — a non-capturing "
            "overlay must never intercept focus/input routing"
        )

    def test_closing_non_capturing_overlay_does_not_disturb_focus(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        main = FocusableComponent(["main content"], has_cursor=True)
        tui.set_focus(main)
        tui.set_root(main)
        tui.do_render()

        overlay = FocusableComponent(["overlay content"], has_cursor=True)
        handle = tui.show_overlay(overlay, anchor_row=0, non_capturing=True)
        assert main.focused

        handle.close()
        assert main.focused, "closing a non-capturing overlay must not touch focus at all"
        assert not overlay.focused

    def test_capturing_is_still_the_default(self, term: RecordingTerm, tui: TUI) -> None:
        """Backward compatibility: omitting ``non_capturing`` entirely must
        preserve every existing capturing-overlay test in this file
        (``TestFocusChain`` above) — the default must remain ``False``."""
        main = FocusableComponent(["main content"], has_cursor=True)
        tui.set_focus(main)
        tui.set_root(main)
        tui.do_render()

        overlay = FocusableComponent(["overlay content"], has_cursor=True)
        tui.show_overlay(overlay, anchor_row=0)

        assert overlay.focused, "default show_overlay behavior must still steal focus"
        assert not main.focused


class TestOverlayAnchor:
    """Overlay anchor positioning."""

    def test_overlay_anchor_row_none_default(self, term: RecordingTerm, tui: TUI) -> None:
        """anchor_row=None should default to a sensible position (e.g., row 0 or centered)."""
        main = StaticComponent(["main line 1", "main line 2"])
        tui.set_root(main)
        tui.do_render()

        overlay = StaticComponent(["overlay content"])
        try:
            tui.show_overlay(overlay)  # anchor_row=None
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        tui.do_render()
        screen = term.screen()
        full_text = "".join(screen)

        # Overlay should appear somewhere on screen
        assert "overlay content" in full_text

    def test_overlay_anchor_row_explicit(self, term: RecordingTerm, tui: TUI) -> None:
        """anchor_row set explicitly should position overlay at that row."""
        main = StaticComponent(["main 1", "main 2", "main 3", "main 4"])
        tui.set_root(main)
        tui.do_render()

        overlay = StaticComponent(["OVERLAY"])
        try:
            tui.show_overlay(overlay, anchor_row=2)
        except AttributeError:
            pytest.fail("show_overlay not implemented")

        tui.do_render()
        screen = term.screen()

        # The overlay should appear at or near row 2
        # (exact positioning logic is implementation-defined, but it should be present)
        full_text = "".join(screen)
        assert "OVERLAY" in full_text

    def test_overlay_visible_when_content_exceeds_height(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        """``anchor_row`` is *screen-relative* (row 0 = top of the visible
        viewport), not a bare buffer index — ``_composite_overlays`` must
        translate it through the same scroll offset the rest of ``do_render``
        already uses (``viewport_top = max(0, buffer_length - height)``),
        exactly like upstream's ``compositeOverlays`` does via its own
        ``viewportStart`` (tui.ts:1074 ``Math.max(0, workingHeight -
        termHeight)``, tui.ts:1079 ``idx = viewportStart + row + i``).

        Regression scenario (citation: reviewer-verified bug report): 100
        lines of root content, a 24-row terminal, ``show_overlay(anchor_row=0)``.
        ``viewport_top`` is 100 - 24 = 76 — the overlay must land at buffer
        row 76 (the top of what's actually visible), not at bare buffer row 0
        (76 rows *above* the visible viewport — on a real terminal, already
        scrolled into scrollback and gone).

        This is asserted via the exact terminal op sequence rather than
        ``term.screen()``: ``RecordingTerm`` (see conftest.py) is a *fixed*
        24-slot array that cannot represent 100 distinct buffer rows the way
        a real scrolled terminal's visible-window/scrollback split would, so
        it can't itself distinguish "landed at buffer row 0" from "landed at
        buffer row 76" — but the exact cursor-relocation op it takes to get
        there can, because upstream's diff algorithm treats "changed row is
        above ``prev_viewport_top``" as an "unreachable, needs a full
        redraw" signal (tui.ts:1452-1456 / this port's own
        ``if first_changed < prev_viewport_top: full_render(True)``): with
        the bug, the (mis-)composited row 0 change forces a full
        clear-and-redraw of all 100 lines; with the fix, the correctly
        composited row-76 change is recognized as already visible and
        produces a single, small, targeted rewrite of just that one row —
        no clear sequence, no full repaint of the other 99 lines.
        """
        content = [f"line {i}" for i in range(100)]
        main = StaticComponent(content)
        tui.set_root(main)
        tui.do_render()  # first render: writes all 100 lines, no overlay yet.

        term.ops.clear()

        overlay = StaticComponent(["OVERLAY"])
        tui.show_overlay(overlay, anchor_row=0)
        tui.do_render()

        clear_sequence = "\x1b[2J\x1b[H\x1b[3J"
        assert clear_sequence not in term.ops, (
            "a correctly viewport-translated anchor_row=0 overlay only "
            "touches a row within the visible viewport (buffer row "
            "viewport_top=76) — that never requires a full clear-and-redraw "
            "of all 100 lines the way a bare buffer-index-0 placement would"
        )

        # Exact op sequence: the last full render left the (clamped) cursor
        # at RecordingTerm's row 23 (100 lines >> 24 rows). viewport_top =
        # max(0, 100 - 24) = 76; the overlay's target buffer row is
        # viewport_top + anchor_row = 76 + 0 = 76, i.e. target_screen_row =
        # 76 - 76 = 0. current_screen_row (hardware_cursor_row=99 from the
        # first render) - viewport_top(76) = 23. The single relative move
        # is therefore target_screen_row - current_screen_row = 0 - 23 =
        # -23 rows (up), landing exactly on the one changed row.
        assert term.ops == ["\x1b[23A", "\r", "\x1b[2K", "OVERLAY"], (
            "expected a single targeted row rewrite at buffer row "
            "viewport_top + anchor_row (76 + 0), derived from the exact "
            "-23 relative cursor move"
        )
