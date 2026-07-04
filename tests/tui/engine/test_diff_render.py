"""Test suite for differential rendering engine (Task 7, Step 1: RED phase).

Six named tests per brief, exercising the core diff behavior:
- First render writes all lines
- Unchanged rerender writes nothing
- Single middle line change rewrites only that line
- Growth appends without clearing old lines
- Shrink erases tail lines
- Coalesced render on multiple request_render calls
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

# These imports are expected to fail with ModuleNotFoundError on first run
# (until the implementation is written in tui.py).
try:
    from pipython.tui.engine.tui import (
        CURSOR_MARKER,
        Component,
        Container,
        TUI,
    )
except ModuleNotFoundError as e:
    # Capture the error for reporting in the brief's Step 2 confirmation.
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
        """Return a *copy* of the stored lines (width is unused for this test
        helper).

        RED correction: this originally returned ``self.lines`` directly —
        the same mutable list object the tests then mutate in place (e.g.
        ``component.lines[1] = ...``, ``component.lines.extend(...)``).
        Since ``TUI.do_render`` stores whatever ``render()`` returns as its
        "previous frame" snapshot (``self._previous_lines = new_lines``),
        aliasing meant that snapshot silently mutated out from under the
        diff algorithm too: the very next ``render()`` call would see
        "previous" and "new" as the *same* already-mutated object, finding
        zero differences no matter what actually changed. This broke
        ``test_single_middle_line_change_rewrites_only_that_line`` and
        ``test_growth_appends_without_clearing`` outright (both produced
        empty ops — not because the implementation was wrong, but because
        the diff had nothing to compare against). Every real ``Component``
        implementation builds and returns a fresh list each ``render()``
        call (e.g. upstream's own ``Container.render()``, tui.ts:280-288,
        pushes into a brand new local array); this test double now does
        the same.
        """
        return list(self.lines)

    def invalidate(self) -> None:
        """Mark as invalidated."""
        self.invalidated = True


@pytest.fixture
def tui(term: RecordingTerm) -> TUI:
    """Fixture: a TUI instance with a RecordingTerm."""
    return TUI(term)


class TestDiffRender:
    """Differential rendering behavior tests."""

    def test_first_render_writes_all_lines(self, term: RecordingTerm, tui: TUI) -> None:
        """First render should write all lines of the component."""
        component = StaticComponent(["line 1", "line 2", "line 3"])
        tui.set_root(component)
        tui.do_render()

        # Should have written all 3 lines
        # Exact format depends on impl, but ops should not be empty
        assert len(term.ops) > 0, "First render should produce ops"

        # Screen should contain all three lines
        screen = term.screen()
        assert "line 1" in "".join(screen)
        assert "line 2" in "".join(screen)
        assert "line 3" in "".join(screen)

    def test_unchanged_rerender_writes_nothing(self, term: RecordingTerm, tui: TUI) -> None:
        """Re-rendering identical tree should produce no new ops."""
        component = StaticComponent(["line 1", "line 2"])
        tui.set_root(component)

        tui.do_render()
        ops_after_first = len(term.ops)

        # Re-render the exact same tree
        tui.do_render()

        # Should not have added any new ops
        assert len(term.ops) == ops_after_first, (
            "Second render of unchanged tree should not add ops"
        )

    def test_single_middle_line_change_rewrites_only_that_line(
        self, term: RecordingTerm, tui: TUI
    ) -> None:
        """Changing one middle line should rewrite only that line, no others."""
        component = StaticComponent(["line 1", "line 2", "line 3"])
        tui.set_root(component)
        tui.do_render()

        term.ops.clear()

        # Change line 2
        component.lines[1] = "line 2 MODIFIED"
        component.invalidate()
        tui.do_render()

        # Should have:
        # 1. Move cursor to line 2 (row 1)
        # 2. Erase that line (or rewrite it)
        # 3. Write the new content
        # Should NOT move to other rows or erase unrelated lines
        assert len(term.ops) > 0, "Changing one line should produce ops"

        # Verify the modified line is in the final screen
        screen = term.screen()
        final_text = "".join(screen)
        assert "MODIFIED" in final_text

    def test_growth_appends_without_clearing(self, term: RecordingTerm, tui: TUI) -> None:
        """Growing from 3 to 5 lines should append new lines without rewriting old ones."""
        component = StaticComponent(["line 1", "line 2", "line 3"])
        tui.set_root(component)
        tui.do_render()

        term.ops.clear()

        # Grow to 5 lines (lines 0-2 unchanged, lines 3-4 new)
        component.lines.extend(["line 4", "line 5"])
        component.invalidate()
        tui.do_render()

        # The key invariant (task-7-brief.md step 1, test_growth_appends_without_clearing
        # comment: "断言旧 3 行未被擦除重写、只新增 2 行"): old lines 1-3 must NOT
        # appear in the new ops (they must not be rewritten/erased). Only new
        # lines 4-5 should be written.
        # RED correction: the original assertion here only checked that the
        # *new* lines appear (a heuristic comment claimed rewritten old lines
        # "would appear in ops" but nothing actually asserted their absence) —
        # this didn't verify the brief's stated "key" invariant at all. Fixed
        # by asserting old lines 1-3 are absent from the post-clear ops too.
        ops_text = "".join(term.ops)

        assert "line 4" in ops_text or "line 5" in ops_text, "Growth should write new lines"
        assert "line 1" not in ops_text, "Growth must not rewrite unchanged line 1"
        assert "line 2" not in ops_text, "Growth must not rewrite unchanged line 2"
        assert "line 3" not in ops_text, "Growth must not rewrite unchanged line 3"

        # Final screen should have all 5 lines
        screen = term.screen()
        final_text = "".join(screen)
        for i in range(1, 6):
            assert f"line {i}" in final_text

    def test_shrink_erases_tail_lines(self, term: RecordingTerm, tui: TUI) -> None:
        """Shrinking from 5 to 3 lines should erase the tail lines (4-5)."""
        component = StaticComponent(["line 1", "line 2", "line 3", "line 4", "line 5"])
        tui.set_root(component)
        tui.do_render()

        term.ops.clear()

        # Shrink to 3 lines
        component.lines = component.lines[:3]
        component.invalidate()
        tui.do_render()

        # Should have erased lines 4-5
        assert len(term.ops) > 0, "Shrinking should produce erase/move ops"

        # The final screen should only have 3 lines with content
        screen = term.screen()
        final_text = "".join(screen)
        assert "line 1" in final_text
        assert "line 2" in final_text
        assert "line 3" in final_text
        # RED correction: the original test computed `ops_text` but never
        # asserted anything with it, and never actually verified this test's
        # own docstring claim ("should erase the tail lines (4-5)") — only
        # that rows 1-3 survive, not that rows 4-5 are gone. Fixed by
        # asserting lines 4-5 are absent from the final screen.
        assert "line 4" not in final_text, "Shrink must erase tail line 4"
        assert "line 5" not in final_text, "Shrink must erase tail line 5"

    @pytest.mark.asyncio
    async def test_request_render_coalesces(self, term: RecordingTerm, tui: TUI) -> None:
        """Multiple request_render calls should coalesce into one do_render."""
        component = StaticComponent(["line 1"])
        tui.set_root(component)

        # Track how many times the component is actually rendered
        render_count = 0
        original_render = component.render

        def counting_render(width: int) -> list[str]:
            nonlocal render_count
            render_count += 1
            return original_render(width)

        component.render = counting_render  # type: ignore

        # Request render 5 times
        for _ in range(5):
            tui.request_render()

        # Run the event loop to let request_render coalesce
        await asyncio.sleep(0.01)

        # Only one actual render should have happened (or very few, depending
        # on loop scheduling). The key is that it's coalesced, not 5 separate
        # renders.
        assert render_count <= 2, (
            f"5 request_render calls should coalesce, got {render_count} renders"
        )

    def test_request_render_force_clears_and_redraws(self, term: RecordingTerm, tui: TUI) -> None:
        """``request_render(force=True)`` must clear-and-redraw like upstream.

        Upstream's ``requestRender(force=true)`` sets ``previousWidth``/
        ``previousHeight = -1`` (tui.ts:715-716), which routes the *next*
        ``doRender`` into the ``widthChanged`` branch (tui.ts:1343-1345) —
        ``fullRender(true)``: clear screen + scrollback + cursor home
        (``"\\x1b[2J\\x1b[H\\x1b[3J"``, tui.ts:1289), then repaint every line
        fresh. It is NOT upstream's plain first-render path (tui.ts:1336-1339,
        ``fullRender(false)`` — no clear), which is what a force that only
        resets ``previousLines`` would fall into instead: since
        ``previousLines`` is now empty, ``do_render`` would take the
        "first render" branch and skip the clear sequence entirely, leaving
        old on-screen content behind the fresh repaint (overlapping/corrupted
        output) instead of a clean redraw.
        """
        component = StaticComponent(["line 1", "line 2", "line 3"])
        tui.set_root(component)
        tui.do_render()

        term.ops.clear()

        # No running event loop in this synchronous test, so
        # request_render() degrades to an immediate do_render() call
        # (module docstring deviation 6) — the explicit do_render() below is
        # a harmless no-op second call, included per the brief's wording.
        tui.request_render(force=True)
        tui.do_render()

        assert len(term.ops) > 0, "Forced render should produce ops"

        # The clear sequence must be the very first thing written — before
        # any repainted content — exactly matching fullRender(true)'s own
        # buffer order (tui.ts:1287-1289).
        assert term.ops[0] == "\x1b[2J\x1b[H\x1b[3J", (
            "Forced render must clear screen+scrollback+home before repainting"
        )

        # All lines rewritten fresh after the clear (a full repaint, not a
        # partial diff).
        ops_text = "".join(term.ops)
        assert "line 1" in ops_text
        assert "line 2" in ops_text
        assert "line 3" in ops_text

        screen = term.screen()
        final_text = "".join(screen)
        assert "line 1" in final_text
        assert "line 2" in final_text
        assert "line 3" in final_text


class TestComponentProtocol:
    """Verify Component and Container protocol conformance."""

    def test_cursor_marker_constant_exists(self) -> None:
        """CURSOR_MARKER constant should exist and be the zero-width APC marker."""
        assert CURSOR_MARKER == "\x1b_pi:c\x07"

    def test_component_duck_typing(self) -> None:
        """A minimal class with render/invalidate should work as a Component.

        RED correction: `Component` was imported but never referenced,
        tripping ruff's F401 (unused import). Rather than drop the import,
        annotate `comp` with it here — this doubles as a real pyright-level
        check that `StaticComponent` structurally satisfies the `Component`
        Protocol (the same structural fit `TUI.set_root`/`Container.add_child`
        rely on throughout this test file).
        """
        comp: Component = StaticComponent(["test"])
        # Should have the required methods
        assert hasattr(comp, "render")
        assert hasattr(comp, "invalidate")
        assert callable(comp.render)
        assert callable(comp.invalidate)

    def test_container_add_remove_clear(self, tui: TUI) -> None:
        """Container should support add_child, remove_child, clear."""
        container = Container()
        child1 = StaticComponent(["child 1"])
        child2 = StaticComponent(["child 2"])

        container.add_child(child1)
        container.add_child(child2)
        # Render should concatenate children
        lines = container.render(80)
        assert "child 1" in "".join(lines)
        assert "child 2" in "".join(lines)

        container.remove_child(child1)
        lines = container.render(80)
        assert "child 2" in "".join(lines)

        container.clear()
        lines = container.render(80)
        assert len(lines) == 0 or all(not line.strip() for line in lines)

    def test_tui_set_focus(self, tui: TUI) -> None:
        """TUI.set_focus should flip .focused on old/new components."""
        comp1 = StaticComponent(["comp1"])
        comp1.focused = False  # type: ignore

        comp2 = StaticComponent(["comp2"])
        comp2.focused = False  # type: ignore

        tui.set_focus(comp1)
        assert comp1.focused is True  # type: ignore

        tui.set_focus(comp2)
        assert comp1.focused is False  # type: ignore
        assert comp2.focused is True  # type: ignore

        tui.set_focus(None)
        assert comp2.focused is False  # type: ignore


class HandlingComponent:
    """Minimal Component with an optional ``handle_input`` that records every
    frame it receives, exactly as passed (no parsing/copying)."""

    focused = False

    def __init__(self) -> None:
        self.received: list[str] = []

    def render(self, width: int) -> list[str]:
        return []

    def invalidate(self) -> None:
        pass

    def handle_input(self, data: str) -> None:
        self.received.append(data)


class TestHandleInputDispatch:
    """``TUI.handle_input``'s dispatch core (tui.ts's ``handleInput``, minus
    overlay/debug-key routing — a later task's job, see module docstring
    deviation 9): forward the raw frame to the focused component's optional
    ``handle_input``, verbatim, or no-op if there is none/no focus."""

    def test_focused_component_receives_exact_frame(self, tui: TUI) -> None:
        """A plain input frame reaches the focused component's handle_input
        unmodified."""
        component = HandlingComponent()
        tui.set_focus(component)

        tui.handle_input("x")

        assert component.received == ["x"]

    def test_focused_component_receives_paste_marker_frame_verbatim(self, tui: TUI) -> None:
        """A bracketed-paste frame — markers preserved, per
        ``stdin_buffer.py``'s single-channel-paste contract (``ESC[200~`` ...
        ``ESC[201~``, with the markers kept in the frame content) — passes
        through ``handle_input`` exactly as received. ``TUI.handle_input``
        does no parsing or stripping of its own; that is the component's job
        (module docstring: "Parsing the frame into a ``KeyEvent`` is the
        component's own responsibility")."""
        component = HandlingComponent()
        tui.set_focus(component)

        paste_frame = "\x1b[200~pasted text\x1b[201~"
        tui.handle_input(paste_frame)

        assert component.received == [paste_frame]

    def test_focused_component_without_handle_input_is_noop(self, tui: TUI) -> None:
        """A focused component with no ``handle_input`` at all (an entirely
        valid, render-only ``Component`` — see module docstring deviation 9)
        must not crash ``TUI.handle_input``."""
        component = StaticComponent(["line 1"])
        component.focused = False  # type: ignore[attr-defined]
        tui.set_focus(component)

        tui.handle_input("x")  # must not raise

    def test_no_focus_is_noop(self, tui: TUI) -> None:
        """No focused component at all: handle_input is a no-op."""
        tui.handle_input("x")  # must not raise

    @pytest.mark.asyncio
    async def test_handle_input_requests_a_coalesced_render(self, tui: TUI) -> None:
        """Task 16 fix round 1 (Important finding 1): dispatching to the
        focused component's ``handle_input`` must itself request a render
        (upstream parity, tui.ts:827-834: ``this.focusedComponent.
        handleInput(data); this.requestRender();`` — both inside the same
        "a handler exists" guard this method already has). Before this fix,
        callers (``app2.py``) had to remember their own follow-up
        ``request_render()`` after every ``handle_input()`` call; this test
        pins the render request into ``TUI.handle_input`` itself so no
        caller has to.

        Also verifies the coalescing behavior ``request_render`` already
        provides (``test_request_render_coalesces`` above) still holds when
        triggered indirectly through repeated ``handle_input`` calls within
        the same event-loop turn: three frames in a row should still
        collapse into a single ``do_render()``, not three."""
        component = HandlingComponent()
        tui.set_focus(component)

        render_count = 0
        original_do_render = tui.do_render

        def counting_do_render() -> None:
            nonlocal render_count
            render_count += 1
            original_do_render()

        tui.do_render = counting_do_render  # type: ignore[method-assign]

        for ch in "abc":
            tui.handle_input(ch)

        await asyncio.sleep(0.01)

        assert component.received == ["a", "b", "c"]
        assert render_count == 1, (
            f"3 handle_input calls should coalesce into 1 render, got {render_count}"
        )
