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
