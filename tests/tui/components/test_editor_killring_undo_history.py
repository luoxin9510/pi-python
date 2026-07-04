"""
Translation of upstream TypeScript tests: editor.test.ts, domains assigned to Task 12.

This test file translates the following describe blocks from the upstream editor.test.ts:
- Prompt history navigation (line 42)
- Kill ring (line 1158)
- Undo (line 1555)
- Paste marker atomic behavior (line 3547)

These tests exercise kill-ring/undo/history/paste-marker features that Task 12 adds
to the editor component.
"""

from __future__ import annotations


class TestPromptHistoryNavigation:
    """Prompt history navigation (upstream line 42)"""

    def test_does_nothing_on_up_arrow_when_history_is_empty(self):
        """Up arrow does nothing when history is empty."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\x1b[A")  # Up arrow
        assert editor.text == ""

    def test_shows_most_recent_history_entry_on_up_arrow_when_editor_is_empty(self):
        """Shows most recent history entry on Up arrow when editor is empty."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("first prompt")
        editor.add_history("second prompt")

        editor.handle_input("\x1b[A")  # Up arrow
        assert editor.text == "second prompt"

    def test_cycles_through_history_entries_on_repeated_up_arrow(self):
        """Cycles through history entries on repeated Up arrow."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("first")
        editor.add_history("second")
        editor.add_history("third")

        editor.handle_input("\x1b[A")  # Up - shows "third"
        assert editor.text == "third"

        editor.handle_input("\x1b[A")  # Up - shows "second"
        assert editor.text == "second"

        editor.handle_input("\x1b[A")  # Up - shows "first"
        assert editor.text == "first"

        editor.handle_input("\x1b[A")  # Up - stays at "first" (oldest)
        assert editor.text == "first"

    def test_jumps_to_start_before_entering_history_from_a_non_empty_draft(self):
        """Jumps to start before entering history from a non-empty draft."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("prompt")
        editor.set_text("draft")
        editor.handle_input("\x1b[D")  # Left twice
        editor.handle_input("\x1b[D")

        editor.handle_input("\x1b[A")  # Up - jumps to start before history browsing
        assert editor.text == "draft"
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1b[A")  # Up at start - shows "prompt"
        assert editor.text == "prompt"

        editor.handle_input("\x1b[B")  # Down - restores draft
        assert editor.text == "draft"
        assert editor.cursor == (0, 0)

    def test_navigates_forward_through_history_with_down_arrow(self):
        """Navigates forward through history with Down arrow."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("first")
        editor.add_history("second")
        editor.add_history("third")
        editor.set_text("draft")

        # Go to oldest
        editor.handle_input("\x1b[A")  # start of draft
        editor.handle_input("\x1b[A")  # third
        editor.handle_input("\x1b[A")  # second
        editor.handle_input("\x1b[A")  # first

        # Navigate back
        editor.handle_input("\x1b[B")  # second
        assert editor.text == "second"

        editor.handle_input("\x1b[B")  # third
        assert editor.text == "third"

        editor.handle_input("\x1b[B")  # draft
        assert editor.text == "draft"

    def test_exits_history_mode_when_typing_a_character(self):
        """Exits history mode when typing a character."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("old prompt")

        editor.handle_input("\x1b[A")  # Up - shows "old prompt"
        editor.handle_input("x")  # Type a character - exits history mode

        assert editor.text == "xold prompt"

    def test_exits_history_mode_on_set_text(self):
        """Exits history mode on setText."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("history")

        editor.handle_input("\x1b[A")  # Enter history browsing
        assert editor.text == "history"

        editor.set_text("new draft")
        editor.handle_input("\x1b[A")  # Should not navigate history (browsing exited)
        assert editor.text == "new draft"

    def test_history_list_property(self):
        """history list property contains all added entries."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        assert editor.history == []

        editor.add_history("first")
        editor.add_history("second")
        assert editor.history == ["second", "first"]  # Most recent first

    def test_add_history_trims_whitespace(self):
        """add_history trims whitespace from entries."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("  trimmed  ")
        assert editor.history == ["trimmed"]

    def test_add_history_does_not_add_duplicate_as_most_recent(self):
        """add_history does not add duplicate if same as most recent."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("item")
        editor.add_history("item")
        assert editor.history == ["item"]

    def test_add_history_limits_history_size(self):
        """add_history limits history to reasonable size (e.g., 100)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for i in range(150):
            editor.add_history(f"item {i}")
        # Should be limited to at most 100
        assert len(editor.history) <= 100


class TestKillRing:
    """Kill ring (upstream line 1158)"""

    def test_ctrl_w_saves_deleted_text_to_kill_ring_and_ctrl_y_yanks_it(self):
        """Ctrl+W saves deleted text to kill ring and Ctrl+Y yanks it."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("foo bar baz")
        editor.handle_input("\x17")  # Ctrl+W - deletes "baz"
        assert editor.text == "foo bar "

        # Move to beginning and yank
        editor.handle_input("\x01")  # Ctrl+A
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "bazfoo bar "

    def test_ctrl_u_saves_deleted_text_to_kill_ring(self):
        """Ctrl+U saves deleted text to kill ring."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        # Move cursor to middle
        editor.handle_input("\x01")  # Ctrl+A (start)
        for _ in range(6):
            editor.handle_input("\x1b[C")  # Right 6 times to after "hello "

        editor.handle_input("\x15")  # Ctrl+U - deletes "hello "
        assert editor.text == "world"

        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello world"

    def test_ctrl_k_saves_deleted_text_to_kill_ring(self):
        """Ctrl+K saves deleted text to kill ring."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A (start)
        editor.handle_input("\x0b")  # Ctrl+K - deletes "hello world"

        assert editor.text == ""

        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello world"

    def test_ctrl_y_does_nothing_when_kill_ring_is_empty(self):
        """Ctrl+Y does nothing when kill ring is empty."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("test")
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "test"

    def test_alt_y_cycles_through_kill_ring_after_ctrl_y(self):
        """Alt+Y cycles through kill ring after Ctrl+Y."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        # Create kill ring with multiple entries
        editor.set_text("first")
        editor.handle_input("\x17")  # Ctrl+W - deletes "first"
        editor.set_text("second")
        editor.handle_input("\x17")  # Ctrl+W - deletes "second"
        editor.set_text("third")
        editor.handle_input("\x17")  # Ctrl+W - deletes "third"

        # Kill ring now has: [first, second, third]
        assert editor.text == ""

        editor.handle_input("\x19")  # Ctrl+Y - yanks "third" (most recent)
        assert editor.text == "third"

        editor.handle_input("\x1by")  # Alt+Y - cycles to "second"
        assert editor.text == "second"

        editor.handle_input("\x1by")  # Alt+Y - cycles to "first"
        assert editor.text == "first"

        editor.handle_input("\x1by")  # Alt+Y - cycles back to "third"
        assert editor.text == "third"

    def test_alt_y_does_nothing_if_not_preceded_by_yank(self):
        """Alt+Y does nothing if not preceded by yank."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("test")
        editor.handle_input("\x17")  # Ctrl+W - deletes "test"
        editor.set_text("other")

        # Type something to break the yank chain
        editor.handle_input("x")
        assert editor.text == "otherx"

        # Alt+Y should do nothing
        editor.handle_input("\x1by")  # Alt+Y
        assert editor.text == "otherx"

    def test_alt_y_does_nothing_if_kill_ring_has_one_or_fewer_entries(self):
        """Alt+Y does nothing if kill ring has ≤1 entry."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("only")
        editor.handle_input("\x17")  # Ctrl+W - deletes "only"

        editor.handle_input("\x19")  # Ctrl+Y - yanks "only"
        assert editor.text == "only"

        editor.handle_input("\x1by")  # Alt+Y - should do nothing (only 1 entry)
        assert editor.text == "only"

    def test_consecutive_ctrl_w_accumulates_into_one_kill_ring_entry(self):
        """Consecutive Ctrl+W accumulates into one kill ring entry."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("one two three")
        editor.handle_input("\x17")  # Ctrl+W - deletes "three"
        editor.handle_input("\x17")  # Ctrl+W - deletes "two " (prepended)
        editor.handle_input("\x17")  # Ctrl+W - deletes "one " (prepended)

        assert editor.text == ""

        # Should be one combined entry
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "one two three"


class TestUndo:
    """Undo (upstream line 1555)"""

    def test_does_nothing_when_undo_stack_is_empty(self):
        """Undo does nothing when undo stack is empty."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

    def test_coalesces_consecutive_word_characters_into_one_undo_unit(self):
        """Coalesces consecutive word characters into one undo unit."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        # Undo removes " world" (space captured state before it, so we restore to "hello")
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello"

        # Undo removes "hello"
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

    def test_undoes_spaces_one_at_a_time(self):
        """Undoes spaces one at a time."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello  ":
            editor.handle_input(ch)
        assert editor.text == "hello  "

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo) - removes second " "
        assert editor.text == "hello "

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo) - removes first " "
        assert editor.text == "hello"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo) - removes "hello"
        assert editor.text == ""

    def test_undoes_newlines_and_signals_next_word_to_capture_state(self):
        """Undoes newlines and signals next word to capture state."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello\nworld":
            editor.handle_input(ch)
        assert editor.text == "hello\nworld"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello\n"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

    def test_undoes_backspace(self):
        """Undoes backspace."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello":
            editor.handle_input(ch)
        editor.handle_input("\x7f")  # Backspace
        assert editor.text == "hell"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello"

    def test_undoes_forward_delete(self):
        """Undoes forward delete."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello":
            editor.handle_input(ch)
        editor.handle_input("\x01")  # Ctrl+A - go to start
        editor.handle_input("\x1b[C")  # Right arrow
        editor.handle_input("\x1b[3~")  # Delete key
        assert editor.text == "hllo"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello"

    def test_undoes_ctrl_w_delete_word_backward(self):
        """Undoes Ctrl+W (delete word backward)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        editor.handle_input("\x17")  # Ctrl+W
        assert editor.text == "hello "

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

    def test_undoes_ctrl_k_delete_to_line_end(self):
        """Undoes Ctrl+K (delete to line end)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        editor.handle_input("\x01")  # Ctrl+A (start)
        editor.handle_input("\x0b")  # Ctrl+K - deletes "hello world"
        assert editor.text == ""

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"


class TestPasteMarkerAtomicBehavior:
    """Paste marker atomic behavior (upstream line 3547)"""

    @staticmethod
    def paste_with_marker(editor) -> str:
        """Helper: simulate a large paste that creates a marker."""
        big_content = "line\n" * 20
        big_content = big_content.rstrip()  # Remove trailing newline
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")
        return editor.text

    def test_creates_a_paste_marker_for_large_pastes(self):
        """Creates a paste marker for large pastes."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        text = self.paste_with_marker(editor)
        assert re.search(r"\[paste #\d+ \+\d+ lines\]", text) is not None

    def test_treats_paste_marker_as_single_unit_for_right_arrow(self):
        """Treats paste marker as single unit for right arrow."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")
        # Text: "A[paste #1 +20 lines]B", cursor at end

        # Go to start
        editor.handle_input("\x01")  # Ctrl+A
        assert editor.cursor == (0, 0)

        # Right arrow: should move past "A"
        editor.handle_input("\x1b[C")
        assert editor.cursor == (0, 1)

        # Right arrow: should skip the entire marker
        editor.handle_input("\x1b[C")
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", editor.text)
        assert marker is not None
        assert editor.cursor == (0, 1 + len(marker.group(0)))

        # Right arrow: should move past "B"
        editor.handle_input("\x1b[C")
        assert editor.cursor == (0, 1 + len(marker.group(0)) + 1)

    def test_treats_paste_marker_as_single_unit_for_left_arrow(self):
        """Treats paste marker as single unit for left arrow."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")
        # Cursor at end

        # Left arrow: past "B"
        editor.handle_input("\x1b[D")
        text = editor.text
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker is not None
        assert editor.cursor == (0, 1 + len(marker.group(0)))

        # Left arrow: skip the entire marker
        editor.handle_input("\x1b[D")
        assert editor.cursor == (0, 1)

        # Left arrow: past "A"
        editor.handle_input("\x1b[D")
        assert editor.cursor == (0, 0)

    def test_treats_paste_marker_as_single_unit_for_backspace(self):
        """Treats paste marker as single unit for backspace."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")

        text = editor.text
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker is not None
        marker_len = len(marker.group(0))

        # Position cursor right after the marker (before "B")
        editor.handle_input("\x01")  # Ctrl+A
        # Move past "A" and the marker
        editor.handle_input("\x1b[C")  # past "A"
        editor.handle_input("\x1b[C")  # past marker
        assert editor.cursor == (0, 1 + marker_len)

        # Backspace: should delete the entire marker at once
        editor.handle_input("\x7f")
        assert editor.text == "AB"
        assert editor.cursor == (0, 1)

    def test_treats_paste_marker_as_single_unit_for_forward_delete(self):
        """Treats paste marker as single unit for forward delete."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")

        # Position cursor on "A" (col 0) then move right once to be just before marker
        editor.handle_input("\x01")  # Ctrl+A
        editor.handle_input("\x1b[C")  # past "A", now at col 1 (start of marker)

        # Forward delete: should delete the entire marker at once
        editor.handle_input("\x1b[3~")  # Delete key
        assert editor.text == "AB"
        assert editor.cursor == (0, 1)

    def test_treats_paste_marker_as_single_unit_for_word_movement(self):
        """Treats paste marker as single unit for word movement."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.handle_input("X")
        editor.handle_input(" ")
        self.paste_with_marker(editor)
        editor.handle_input(" ")
        editor.handle_input("Y")
        # Text: "X [paste #1 +20 lines] Y"

        text = editor.text
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker is not None
        marker_len = len(marker.group(0))

        # Go to start
        editor.handle_input("\x01")  # Ctrl+A

        # Ctrl+Right: skip "X"
        editor.handle_input("\x1b[1;5C")
        assert editor.cursor == (0, 1)

        # Ctrl+Right: skip whitespace + marker (marker treated as single non-ws, non-punct unit)
        editor.handle_input("\x1b[1;5C")
        assert editor.cursor == (0, 2 + marker_len)

    def test_undo_restores_marker_after_backspace_deletion(self):
        """Undo restores marker after backspace deletion."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")

        text_before = editor.text

        # Position after marker
        editor.handle_input("\x01")
        editor.handle_input("\x1b[C")  # past A
        editor.handle_input("\x1b[C")  # past marker

        # Delete marker
        editor.handle_input("\x7f")
        assert editor.text == "AB"

        # Undo
        editor.handle_input("\x1b[45;5u")
        assert editor.text == text_before

    def test_handles_multiple_paste_markers_in_same_line(self):
        """Handles multiple paste markers in same line."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        self.paste_with_marker(editor)
        editor.handle_input(" ")
        self.paste_with_marker(editor)

        text = editor.text
        markers = list(re.finditer(r"\[paste #\d+ \+\d+ lines\]", text))
        assert len(markers) == 2

        # Go to start
        editor.handle_input("\x01")

        # Right arrow: should skip first marker atomically
        editor.handle_input("\x1b[C")
        assert editor.cursor == (0, len(markers[0].group(0)))

        # Right arrow: past space
        editor.handle_input("\x1b[C")
        assert editor.cursor == (0, len(markers[0].group(0)) + 1)

        # Right arrow: should skip second marker atomically
        editor.handle_input("\x1b[C")
        assert editor.cursor == (
            0,
            len(markers[0].group(0)) + 1 + len(markers[1].group(0)),
        )

    def test_does_not_treat_manually_typed_marker_like_text_as_atomic(self):
        """Does not treat manually typed marker-like text as atomic (no valid paste ID)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Type text that matches the pattern but was typed manually (no paste entry)
        fake_marker = "[paste #99 +5 lines]"
        for ch in fake_marker:
            editor.handle_input(ch)

        assert editor.text == fake_marker

        # No paste with ID 99 exists, so the marker is NOT treated atomically.
        # Right arrow should move one grapheme at a time.
        editor.handle_input("\x01")  # Ctrl+A
        editor.handle_input("\x1b[C")  # Right
        assert editor.cursor == (0, 1)  # Just past "["

    def test_paste_marker_preserved_in_get_expanded_text(self):
        """Paste marker is preserved in text but expanded in get_expanded_text()."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.handle_input("X")
        self.paste_with_marker(editor)
        editor.handle_input("Y")

        text = editor.text
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker is not None

        # text should contain the marker
        assert "[paste #" in text

        # get_expanded_text should expand the marker back to original content
        expanded = editor.get_expanded_text()
        assert "[paste #" not in expanded
        assert "line\n" in expanded
        assert expanded.startswith("X")
        assert expanded.endswith("Y")

    def test_paste_is_single_undo_unit(self):
        """Paste (including large paste marker) is single undo unit.

        RED correction (task-12 GREEN phase): the original assertion
        sequence here (undo -> "AB", i.e. removing the marker while
        keeping "B") does not match a plain LIFO full-state undo stack
        (undo-stack.ts / Task 5's ``UndoStack`` — push before every edit,
        pop restores the exact prior snapshot, no diffing). Given pushes
        happen in order [before "A", before paste, before "B"], the first
        undo must restore the state captured just before "B" was typed —
        i.e. remove only "B", leaving "A" + marker intact — and the
        *second* undo is the one that removes the entire paste marker in
        one shot (the actual "single undo unit" behavior this test is
        about). Corrected to that sequence; still exercises the same
        invariant (a full undo of the paste never partially unwinds the
        marker character-by-character).
        """
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("A")
        self.paste_with_marker(editor)
        editor.handle_input("B")

        text_with_paste = editor.text

        # Undo the "B" typed after the paste — the paste's own undo unit
        # (the marker) is still intact underneath it.
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == text_with_paste[:-1]

        # Undo the entire paste marker in one shot (single undo unit) —
        # not character by character.
        editor.handle_input("\x1b[45;5u")
        assert editor.text == "A"

        # Undo the "A"
        editor.handle_input("\x1b[45;5u")
        assert editor.text == ""
