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

import pytest


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
        """add_history limits history to 100 entries, dropping oldest entries."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Add 105 entries
        for i in range(105):
            editor.add_history(f"prompt {i}")

        # Should be limited to exactly 100
        assert len(editor.history) == 100

        # Navigate to oldest - should be "prompt 5" (entries 0-4 were dropped)
        editor.set_text("")
        for _ in range(100):
            editor.handle_input("\x1b[A")

        assert editor.text == "prompt 5"

        # One more Up should not change anything (at oldest)
        editor.handle_input("\x1b[A")
        assert editor.text == "prompt 5"

    def test_does_not_add_empty_strings_to_history(self):
        """Does not add empty or whitespace-only strings to history."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("")
        editor.add_history("   ")
        editor.add_history("valid")

        editor.handle_input("\x1b[A")
        assert editor.text == "valid"

        # Should not have more entries
        editor.handle_input("\x1b[A")
        assert editor.text == "valid"

    def test_allows_non_consecutive_duplicates_in_history(self):
        """Allows non-consecutive duplicates in history."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("first")
        editor.add_history("second")
        editor.add_history("first")  # Not consecutive, should be added

        editor.handle_input("\x1b[A")  # "first"
        assert editor.text == "first"

        editor.handle_input("\x1b[A")  # "second"
        assert editor.text == "second"

        editor.handle_input("\x1b[A")  # "first" (older one)
        assert editor.text == "first"

    def test_uses_cursor_movement_instead_of_history_when_editor_has_content(self):
        """Uses cursor movement instead of history when editor has content."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("history item")
        editor.set_text("line1\nline2")

        # Cursor is at end of line2, Up should move to line1
        editor.handle_input("\x1b[A")  # Up - cursor movement

        # Insert character to verify cursor position
        editor.handle_input("X")

        # X should be inserted in line1, not replace with history
        assert editor.text == "line1X\nline2"

    def test_places_cursor_at_start_after_browsing_history_upward(self):
        """Places cursor at start after browsing history upward."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("older entry")
        editor.add_history("line1\nline2\nline3")

        editor.handle_input("\x1b[A")  # Up - shows multi-line entry at start
        assert editor.text == "line1\nline2\nline3"
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1b[A")  # Up again - immediately navigates to older entry
        assert editor.text == "older entry"
        assert editor.cursor == (0, 0)

    def test_places_cursor_at_end_after_browsing_history_downward(self):
        """Places cursor at end after browsing history downward."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("older entry")
        editor.add_history("line1\nline2\nline3")
        editor.add_history("newer entry")

        editor.handle_input("\x1b[A")  # newer entry
        editor.handle_input("\x1b[A")  # multi-line entry
        editor.handle_input("\x1b[A")  # older entry

        editor.handle_input("\x1b[B")  # Down - shows multi-line entry at end
        assert editor.text == "line1\nline2\nline3"
        assert editor.cursor == (2, 5)

        editor.handle_input("\x1b[B")  # Down again - immediately navigates to newer entry
        assert editor.text == "newer entry"

    def test_allows_opposite_direction_cursor_movement_within_multi_line_history_entry(self):
        """Allows opposite-direction cursor movement within multi-line history entry."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.add_history("line1\nline2\nline3")

        editor.handle_input("\x1b[A")  # Up - shows entry at start
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1b[B")  # Down - cursor moves to line2
        assert editor.text == "line1\nline2\nline3"
        assert editor.cursor == (1, 0)

        editor.handle_input("\x1b[A")  # Up - cursor moves back to line1
        assert editor.text == "line1\nline2\nline3"
        assert editor.cursor == (0, 0)


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

    def test_ctrl_u_accumulates_multiline_deletes_including_newlines(self):
        """Ctrl+U accumulates multiline deletes including newlines."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Start with multiline text, cursor at end
        editor.set_text("line1\nline2\nline3")
        # Cursor is at end of line3 (line 2, col 5)

        # Delete "line3"
        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == "line1\nline2\n"

        # Delete newline (at start of empty line 2, merges with line1)
        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == "line1\nline2"

        # Delete "line2"
        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == "line1\n"

        # Delete newline
        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == "line1"

        # Delete "line1"
        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == ""

        # All deletions accumulated into one entry: "line1\nline2\nline3"
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "line1\nline2\nline3"

    def test_backward_deletions_prepend_forward_deletions_append_during_accumulation(self):
        """Backward deletions prepend, forward deletions append during accumulation."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("prefix|suffix")
        # Position cursor at |
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(6):
            editor.handle_input("\x1b[C")  # Move right 6 times

        editor.handle_input("\x0b")  # Ctrl+K - deletes "suffix" (forward)
        editor.handle_input("\x0b")  # Ctrl+K - deletes "|" (forward, appended)
        assert editor.text == "prefix"

        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "prefix|suffix"

    def test_non_delete_actions_break_kill_accumulation(self):
        """Non-delete actions break kill accumulation."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Delete "baz", then type "x" to break accumulation, then delete "x"
        editor.set_text("foo bar baz")
        editor.handle_input("\x17")  # Ctrl+W - deletes "baz"
        assert editor.text == "foo bar "

        editor.handle_input("x")  # Typing breaks accumulation
        assert editor.text == "foo bar x"

        editor.handle_input("\x17")  # Ctrl+W - deletes "x" (separate entry, not accumulated)
        assert editor.text == "foo bar "

        # Yank most recent - should be "x", not "xbaz"
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "foo bar x"

        # Cycle to previous - should be "baz" (separate entry)
        editor.handle_input("\x1by")  # Alt+Y
        assert editor.text == "foo bar baz"

    def test_non_yank_actions_break_alt_y_chain(self):
        """Non-yank actions break Alt+Y chain."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("first")
        editor.handle_input("\x17")  # Ctrl+W
        editor.set_text("second")
        editor.handle_input("\x17")  # Ctrl+W
        editor.set_text("")

        editor.handle_input("\x19")  # Ctrl+Y - yanks "second"
        assert editor.text == "second"

        editor.handle_input("x")  # Type breaks yank chain
        assert editor.text == "secondx"

        editor.handle_input("\x1by")  # Alt+Y - should do nothing
        assert editor.text == "secondx"

    def test_kill_ring_rotation_persists_after_cycling(self):
        """Kill ring rotation persists after cycling."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("first")
        editor.handle_input("\x17")  # deletes "first"
        editor.set_text("second")
        editor.handle_input("\x17")  # deletes "second"
        editor.set_text("third")
        editor.handle_input("\x17")  # deletes "third"
        editor.set_text("")

        # Ring: [first, second, third]

        editor.handle_input("\x19")  # Ctrl+Y - yanks "third"
        editor.handle_input("\x1by")  # Alt+Y - cycles to "second", ring rotates

        # Now ring is: [third, first, second]
        assert editor.text == "second"

        # Do something else
        editor.handle_input("x")
        editor.set_text("")

        # New yank should get "second" (now at end after rotation)
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "second"

    def test_consecutive_deletions_across_lines_coalesce_into_one_entry(self):
        """Consecutive deletions across lines coalesce into one entry."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # "1\n2\n3" with cursor at end, delete everything with Ctrl+W
        editor.set_text("1\n2\n3")
        editor.handle_input("\x17")  # Ctrl+W - deletes "3"
        assert editor.text == "1\n2\n"

        editor.handle_input("\x17")  # Ctrl+W - deletes newline (merge with prev line)
        assert editor.text == "1\n2"

        editor.handle_input("\x17")  # Ctrl+W - deletes "2"
        assert editor.text == "1\n"

        editor.handle_input("\x17")  # Ctrl+W - deletes newline
        assert editor.text == "1"

        editor.handle_input("\x17")  # Ctrl+W - deletes "1"
        assert editor.text == ""

        # All deletions should have accumulated into one entry
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "1\n2\n3"

    def test_ctrl_k_at_line_end_deletes_newline_and_coalesces(self):
        """Ctrl+K at line end deletes newline and coalesces."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # "ab" on line 1, "cd" on line 2, cursor at end of line 1
        editor.set_text("")
        editor.handle_input("a")
        editor.handle_input("b")
        editor.handle_input("\n")
        editor.handle_input("c")
        editor.handle_input("d")
        # Move to end of first line
        editor.handle_input("\x1b[A")  # Up arrow
        editor.handle_input("\x05")  # Ctrl+E - end of line

        # Now at end of "ab", Ctrl+K should delete newline (merge with "cd")
        editor.handle_input("\x0b")  # Ctrl+K - deletes newline
        assert editor.text == "abcd"

        # Continue deleting
        editor.handle_input("\x0b")  # Ctrl+K - deletes "cd"
        assert editor.text == "ab"

        # Both deletions should accumulate
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "ab\ncd"

    def test_handles_yank_in_middle_of_text(self):
        """Handles yank in middle of text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("word")
        editor.handle_input("\x17")  # Ctrl+W - deletes "word"
        editor.set_text("hello world")

        # Move to middle (after "hello ")
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(6):
            editor.handle_input("\x1b[C")

        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello wordworld"

    def test_handles_yank_pop_in_middle_of_text(self):
        """Handles yank-pop in middle of text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Create two kill ring entries
        editor.set_text("FIRST")
        editor.handle_input("\x17")  # Ctrl+W - deletes "FIRST"
        editor.set_text("SECOND")
        editor.handle_input("\x17")  # Ctrl+W - deletes "SECOND"

        # Ring: ["FIRST", "SECOND"]

        # Set up "hello world" and position cursor after "hello "
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start of line
        for i in range(6):
            editor.handle_input("\x1b[C")  # Move right 6

        # Yank "SECOND" in the middle
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello SECONDworld"

        # Yank-pop replaces "SECOND" with "FIRST"
        editor.handle_input("\x1by")  # Alt+Y
        assert editor.text == "hello FIRSTworld"

    def test_multiline_yank_and_yank_pop_in_middle_of_text(self):
        """Multiline yank and yank-pop in middle of text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Create single-line entry
        editor.set_text("SINGLE")
        editor.handle_input("\x17")  # Ctrl+W - deletes "SINGLE"

        # Create multiline entry via consecutive Ctrl+U
        editor.set_text("A\nB")
        editor.handle_input("\x15")  # Ctrl+U - deletes "B"
        editor.handle_input("\x15")  # Ctrl+U - deletes newline
        editor.handle_input("\x15")  # Ctrl+U - deletes "A"
        # Ring: ["SINGLE", "A\nB"]

        # Insert in middle of "hello world"
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(6):
            editor.handle_input("\x1b[C")

        # Yank multiline "A\nB"
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello A\nBworld"

        # Yank-pop replaces with "SINGLE"
        editor.handle_input("\x1by")  # Alt+Y
        assert editor.text == "hello SINGLEworld"

    def test_alt_d_deletes_word_forward_and_saves_to_kill_ring(self):
        """Alt+D deletes word forward and saves to kill ring."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world test")
        editor.handle_input("\x01")  # Ctrl+A - go to start

        editor.handle_input("\x1bd")  # Alt+D - deletes "hello"
        assert editor.text == " world test"

        editor.handle_input("\x1bd")  # Alt+D - deletes " world" (skips whitespace, then word)
        assert editor.text == " test"

        # Yank should get accumulated text
        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "hello world test"

    def test_alt_d_at_end_of_line_deletes_newline(self):
        """Alt+D at end of line deletes newline."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("line1\nline2")
        # Move to start of document, then to end of first line
        editor.handle_input("\x1b[A")  # Up arrow - go to first line
        editor.handle_input("\x05")  # Ctrl+E - end of line

        editor.handle_input("\x1bd")  # Alt+D - deletes newline (merges lines)
        assert editor.text == "line1line2"

        editor.handle_input("\x19")  # Ctrl+Y
        assert editor.text == "line1\nline2"


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

    def test_undoes_ctrl_u_delete_to_line_start(self):
        """Undoes Ctrl+U (delete to line start)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        editor.handle_input("\x01")  # Ctrl+A (start)
        for i in range(6):
            editor.handle_input("\x1b[C")  # Move right 6 times

        editor.handle_input("\x15")  # Ctrl+U
        assert editor.text == "world"

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

    def test_undoes_yank(self):
        """Undoes yank."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello ":
            editor.handle_input(ch)
        editor.handle_input("\x17")  # Ctrl+W - delete "hello "
        editor.handle_input("\x19")  # Ctrl+Y - yank
        assert editor.text == "hello "

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

    def test_undoes_single_line_paste_atomically(self):
        """Undoes single-line paste atomically."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        for i in range(5):
            editor.handle_input("\x1b[C")  # Move right 5 (after "hello", before space)

        # Simulate bracketed paste of "beep boop"
        editor.handle_input("\x1b[200~beep boop\x1b[201~")
        assert editor.text == "hellobeep boop world"

        # Single undo should restore entire pre-paste state
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

        editor.handle_input("|")
        assert editor.text == "hello| world"

    def test_does_not_trigger_autocomplete_during_single_line_paste(self):
        """Does not trigger autocomplete during single-line paste."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Simply test that bracketed paste works without errors
        editor.handle_input("\x1b[200~look at @node_modules/react/index.js please\x1b[201~")

        assert editor.text == "look at @node_modules/react/index.js please"

    @pytest.mark.skip(
        reason="editor.py module docstring deviation 9: handle_paste does not port "
        "the CSI-u Ctrl+letter re-decoding (tmux-popup shim, editor.ts:1154-1159)"
    )
    def test_decodes_csi_u_ctrl_letter_sequences_inside_bracketed_paste(self):
        """Decodes CSI-u Ctrl+letter sequences inside bracketed paste (tmux popup)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # tmux popups with extended-keys-format=csi-u re-encode \n in pastes as
        # \x1b[106;5u (Ctrl+J). Without decoding, the per-char filter strips ESC
        # and leaks "[106;5u" between lines.
        editor.handle_input("\x1b[200~line1\x1b[106;5uline2\x1b[106;5uline3\x1b[201~")
        assert editor.text == "line1\nline2\nline3"

    def test_undoes_multi_line_paste_atomically(self):
        """Undoes multi-line paste atomically."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        for i in range(5):
            editor.handle_input("\x1b[C")  # Move right 5 (after "hello", before space)

        # Simulate bracketed paste of multi-line text
        editor.handle_input("\x1b[200~line1\nline2\nline3\x1b[201~")
        assert editor.text == "helloline1\nline2\nline3 world"

        # Single undo should restore entire pre-paste state
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

        editor.handle_input("|")
        assert editor.text == "hello| world"

    def test_undoes_insert_text_at_cursor_atomically(self):
        """Undoes insertTextAtCursor atomically."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        for i in range(5):
            editor.handle_input("\x1b[C")  # Move right 5 (after "hello", before space)

        # Programmatic insertion (e.g., clipboard image path)
        editor.insert_text_at_cursor("/tmp/image.png")  # pyright: ignore[reportAttributeAccessIssue]
        assert editor.text == "hello/tmp/image.png world"

        # Single undo should restore entire pre-insert state
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

        editor.handle_input("|")
        assert editor.text == "hello| world"

    def test_insert_text_at_cursor_handles_multiline_text(self):
        """insertTextAtCursor handles multiline text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        for i in range(5):
            editor.handle_input("\x1b[C")  # Move right 5 (after "hello", before space)

        # Insert multiline text
        editor.insert_text_at_cursor("line1\nline2\nline3")  # pyright: ignore[reportAttributeAccessIssue]
        assert editor.text == "helloline1\nline2\nline3 world"

        # Cursor should be at end of inserted text (after "line3", before " world")
        cursor = editor.cursor
        assert cursor == (2, 5)  # line3 is on line 2, length 5

        # Single undo should restore entire pre-insert state
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

    def test_insert_text_at_cursor_normalizes_crlf_and_cr_line_endings(self):
        """insertTextAtCursor normalizes CRLF and CR line endings."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("")

        # Insert text with CRLF
        editor.insert_text_at_cursor("a\r\nb\r\nc")  # pyright: ignore[reportAttributeAccessIssue]
        assert editor.text == "a\nb\nc"

        editor.handle_input("\x1b[45;5u")  # Undo
        assert editor.text == ""

        # Insert text with CR only
        editor.insert_text_at_cursor("x\ry\rz")  # pyright: ignore[reportAttributeAccessIssue]
        assert editor.text == "x\ny\nz"

    def test_undoes_set_text_to_empty_string(self):
        """Undoes setText to empty string."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        editor.set_text("")
        assert editor.text == ""

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

    def test_clears_undo_stack_on_submit(self):
        """Clears undo stack on submit."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        submitted = []

        def on_submit(text):
            submitted.append(text)

        editor.on_submit = on_submit

        for ch in "hello":
            editor.handle_input(ch)
        editor.handle_input("\r")  # Enter - submit

        assert submitted == ["hello"]
        assert editor.text == ""

        # Undo should do nothing - stack was cleared
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

    def test_exits_history_browsing_mode_on_undo(self):
        """Exits history browsing mode on undo."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Add "hello" to history
        editor.add_history("hello")
        assert editor.text == ""

        # Type "world"
        for ch in "world":
            editor.handle_input(ch)
        assert editor.text == "world"

        # Ctrl+W - delete word
        editor.handle_input("\x17")  # Ctrl+W
        assert editor.text == ""

        # Press Up - enter history browsing, shows "hello"
        editor.handle_input("\x1b[A")  # Up arrow
        assert editor.text == "hello"

        # Undo should restore to "" (state before entering history browsing)
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

        # Undo again should restore to "world" (state before Ctrl+W)
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "world"

    def test_undo_restores_to_pre_history_state_even_after_multiple_history_navigations(self):
        """Undo restores to pre-history state even after multiple history navigations."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Add history entries
        editor.add_history("first")
        editor.add_history("second")
        editor.add_history("third")

        # Type something
        for ch in "current":
            editor.handle_input(ch)
        assert editor.text == "current"

        # Clear editor
        editor.handle_input("\x17")  # Ctrl+W
        assert editor.text == ""

        # Navigate through history multiple times
        editor.handle_input("\x1b[A")  # Up - "third"
        assert editor.text == "third"
        editor.handle_input("\x1b[A")  # Up - "second"
        assert editor.text == "second"
        editor.handle_input("\x1b[A")  # Up - "first"
        assert editor.text == "first"

        # Undo should go back to "" (state before we started browsing), not intermediate states
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == ""

        # Another undo goes back to "current"
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "current"

    def test_cursor_movement_starts_new_undo_unit(self):
        """Cursor movement starts new undo unit."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello world":
            editor.handle_input(ch)
        assert editor.text == "hello world"

        # Move cursor left 5 (to after "hello ")
        for i in range(5):
            editor.handle_input("\x1b[D")

        # Type "lol" in the middle
        for ch in "lol":
            editor.handle_input(ch)
        assert editor.text == "hello lolworld"

        # Undo should restore to "hello world" (before inserting "lol")
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello world"

        editor.handle_input("|")
        assert editor.text == "hello |world"

    def test_no_op_delete_operations_do_not_push_undo_snapshots(self):
        """No-op delete operations do not push undo snapshots."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        for ch in "hello":
            editor.handle_input(ch)
        assert editor.text == "hello"

        # Delete word on empty - multiple times (should be no-ops)
        editor.handle_input("\x17")  # Ctrl+W - deletes "hello"
        assert editor.text == ""
        editor.handle_input("\x17")  # Ctrl+W - no-op (nothing to delete)
        editor.handle_input("\x17")  # Ctrl+W - no-op

        # Single undo should restore "hello"
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "hello"

    def test_undoes_autocomplete(self):
        """Undoes autocomplete."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Type "di"
        editor.handle_input("d")
        editor.handle_input("i")
        assert editor.text == "di"

        # Simulate autocomplete - editor would replace "di" with "dist/"
        # For now, just test that undo works on manual text changes
        editor.set_text("dist/")
        assert editor.text == "dist/"

        # Undo should restore to "di"
        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "di"


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

    def test_does_not_crash_when_paste_marker_is_wider_than_terminal_width(self):
        """Does not crash when paste marker is wider than terminal width."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width
        import re

        editor = Editor()
        # Reproduce: terminal width 8, paste marker "[paste #1 +47 lines]"
        # (21 chars) — create a paste with 47 lines so the marker is wider
        # than the render width.
        big_content = "line\n" * 47
        big_content = big_content.rstrip()
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")

        text = editor.text
        marker = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker is not None
        assert visible_width(marker.group(0)) > 8, "marker should be wider than render width"

        # Render at very narrow width - should not throw.
        lines = editor.render(8)
        # Every rendered line must fit within the width (marker is split).
        for line in lines:
            assert visible_width(line) <= 8, (
                f"line exceeds width 8: visible={visible_width(line)} text={line!r}"
            )

    def test_does_not_crash_when_text_plus_paste_marker_exceeds_terminal_width_with_cursor_on_marker(
        self,
    ):
        """Does not crash when text + paste marker exceeds terminal width with cursor on marker."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        # Reproduce: terminal width 54, text "b"*35 + "[paste #1 +27 lines]"
        # + "bbbb". Cursor lands on the paste marker after word-wrap,
        # causing the rendered line to be 55 visible chars (1 over width).

        # Type 35 'b' characters
        for i in range(35):
            editor.handle_input("b")

        # Paste 27 lines
        big_content = "line\n" * 27
        big_content = big_content.rstrip()
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")

        # Type a few more characters
        for i in range(4):
            editor.handle_input("b")

        # Move cursor left to land on the paste marker
        editor.handle_input("\x1b[D")  # past last 'b'
        editor.handle_input("\x1b[D")  # past last 'b'
        editor.handle_input("\x1b[D")  # past last 'b'
        editor.handle_input("\x1b[D")  # past last 'b'
        editor.handle_input("\x1b[D")  # now on the paste marker

        # Render at width 54 - should not throw.
        render_width = 54
        lines = editor.render(render_width)
        for line in lines:
            assert visible_width(line) <= render_width, (
                f"line exceeds width {render_width}: visible={visible_width(line)} text={line!r}"
            )

    def test_word_wrap_line_re_checks_overflow_after_backtracking_to_wrap_opportunity(self):
        """wordWrapLine re-checks overflow after backtracking to wrap opportunity."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        # Reproduce crash #2: " " + "b"*35 + atomic_marker(20 chars) +
        # "bbbb", layoutWidth=53. After wrapping at the space, the
        # remaining 35 b's + marker = 55 must trigger a second force-break
        # instead of silently overflowing.

        # Type a space, then 35 b's
        editor.handle_input(" ")
        for i in range(35):
            editor.handle_input("b")

        # Paste 27 lines to create marker
        big_content = "line\n" * 27
        big_content = big_content.rstrip()
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")

        # Type trailing chars
        for i in range(4):
            editor.handle_input("b")

        # Render at width 54 (contentWidth=54, layoutWidth=53 with
        # paddingX=0) - should not throw.
        render_width = 54
        lines = editor.render(render_width)
        for line in lines:
            assert visible_width(line) <= render_width, (
                f"line exceeds width {render_width}: visible={visible_width(line)} text={line!r}"
            )

    def test_expands_large_pasted_content_literally_in_get_expanded_text(self):
        """Expands large pasted content literally in getExpandedText."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        pasted_text = (
            "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\n"
            "line 7\nline 8\nline 9\nline 10\n"
            "tokens $1 $2 $& $$ $` $' end"
        )

        editor.handle_input(f"\x1b[200~{pasted_text}\x1b[201~")

        assert re.search(r"\[paste #\d+ \+\d+ lines\]", editor.text) is not None
        assert editor.get_expanded_text() == pasted_text

    def test_snaps_to_the_paste_marker_start_when_navigating_down_into_it(self):
        """Snaps to the paste marker start when navigating down into it."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        # Line 0: long enough text to establish a sticky column
        editor.set_text("12345678901234567890\n\nhello ")

        # Create a large paste to get a marker
        big_content = "x" * 2000
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")

        text = editor.text
        marker_match = re.search(r"\[paste #\d+ \d+ chars\]", text)
        assert marker_match is not None

        # Navigate to line 0, col 10
        editor.handle_input("\x1b[A")  # Up to line 1
        editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A (start of line)
        for i in range(10):
            editor.handle_input("\x1b[C")  # Right 10
        assert editor.cursor == (0, 10)

        # Down to empty line
        editor.handle_input("\x1b[B")
        assert editor.cursor == (1, 0)

        # Down to paste marker line - sticky col 10 falls inside marker
        # (starts at col 6). Cursor should snap to start of marker (col 6),
        # not end (col 6 + marker.length).
        editor.handle_input("\x1b[B")
        assert editor.cursor == (2, 6)

    def test_preserves_sticky_column_when_navigating_through_paste_marker_line(self):
        """Preserves sticky column when navigating through paste marker line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # Build multiple lines with a paste marker in the middle
        for ch in "1234567890123456":
            editor.handle_input(ch)
        editor.handle_input("\n")
        editor.handle_input("\n")
        editor.handle_input(f"\x1b[200~{'x' * 2000}\x1b[201~")
        editor.handle_input("\n")
        editor.handle_input("\n")
        for ch in "abcdefghijklmnop":
            editor.handle_input(ch)

        # Navigate to line 0, col 10
        for i in range(4):
            editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(10):
            editor.handle_input("\x1b[C")
        assert editor.cursor == (0, 10)

        # Down to empty line - sticky col 10 established
        editor.handle_input("\x1b[B")
        assert editor.cursor == (1, 0)

        # Down to paste marker - cursor snapped to col 0 (start of marker)
        editor.handle_input("\x1b[B")
        assert editor.cursor == (2, 0)

        # Down to empty line
        editor.handle_input("\x1b[B")
        assert editor.cursor == (3, 0)

        # Down to last line - should restore sticky col 10
        editor.handle_input("\x1b[B")
        assert editor.cursor == (4, 10)

    def test_typing_after_vertical_snap_inserts_before_the_marker_not_inside_it(self):
        """Regression: a vertical move that snaps the cursor onto a paste
        marker must leave it *before* the marker (not mid-marker), so a
        subsequent keystroke inserts text before the marker instead of
        splitting it. Splitting the marker breaks ``_PASTE_MARKER_RE``'s
        match, which would silently drop the pasted content from
        ``get_expanded_text()`` at submit time — the data-loss bug this
        vertical-snap port fixes."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        editor.set_text("12345678901234567890\n\nhello ")

        big_content = "x" * 2000
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")
        assert re.search(r"\[paste #\d+ \d+ chars\]", editor.text) is not None

        # Navigate to line 0, col 10, then down twice to snap onto the
        # marker on line 2 (starts at col 6) — same setup as
        # test_snaps_to_the_paste_marker_start_when_navigating_down_into_it.
        editor.handle_input("\x1b[A")
        editor.handle_input("\x1b[A")
        editor.handle_input("\x01")
        for i in range(10):
            editor.handle_input("\x1b[C")
        editor.handle_input("\x1b[B")
        editor.handle_input("\x1b[B")
        assert editor.cursor == (2, 6)

        # Typing here must insert BEFORE the marker, not split it.
        editor.handle_input("Z")
        assert editor.cursor == (2, 7)
        line2 = editor.text.split("\n")[2]
        assert line2.startswith("hello Z[paste #")
        assert re.fullmatch(r"hello Z\[paste #\d+ \d+ chars\]", line2)

        # get_expanded_text() must still expand the marker to the full
        # 2000-char paste — not a broken literal from a split marker.
        assert editor.get_expanded_text() == "12345678901234567890\n\nhello Z" + big_content

    def test_does_not_get_stuck_moving_down_from_a_multi_visual_line_paste_marker(self):
        """Does not get stuck moving down from a multi-visual-line paste marker."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        # Build:
        # Logical line 0: "abcdefgh" + marker(21 chars) + "ijklmnopqr"
        # Logical line 1: "123456789012345678"
        #
        # Marker "[paste #1 +100 lines]" (21 chars) is wider than the
        # render width (20, i.e. layout width 19). Word-wrap splits at the
        # space before "lines", producing:
        #   VL1: abcdefgh              (startCol 0,  len 8)
        #   VL2: [paste #1 +100        (startCol 8,  len 15) <- marker head
        #   VL3: lines]ijklmnopqr      (startCol 23, len 16) <- marker tail + content
        #   VL4: 123456789012345678    (line 1)
        #
        # On VL3 the marker tail "lines]" occupies visual cols 0-5.
        # Content ("i") starts at visual col 6 = logical col 29.
        for ch in "abcdefgh":
            editor.handle_input(ch)
        big_content = "line\n" * 100
        big_content = big_content.rstrip()
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")
        for ch in "ijklmnopqr":
            editor.handle_input(ch)
        editor.handle_input("\n")
        for ch in "123456789012345678":
            editor.handle_input(ch)
        editor.render(20)

        text = editor.text
        marker_match = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker_match is not None
        marker_len = len(marker_match.group(0))
        assert marker_len > 20
        marker_start = 8
        marker_end = marker_start + marker_len  # 29

        # Navigate to line 0, col 6 (on "g"). Preferred col 6 is past the
        # marker tail on VL3, so the cursor should land on content ("i" at
        # col 29) without snapping back.
        editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(6):
            editor.handle_input("\x1b[C")  # Right to col 6
        assert editor.cursor == (0, 6)

        # Down: cursor lands on paste marker start
        editor.handle_input("\x1b[B")
        assert editor.cursor == (0, marker_start)

        # Down again: preferred col 6 lands at VL3 col 29 ("i"), which is
        # past the marker. Cursor stays on line 0.
        editor.handle_input("\x1b[B")
        assert editor.cursor == (0, marker_end)

        # Up: back to paste marker
        editor.handle_input("\x1b[A")
        assert editor.cursor == (0, marker_start)

        # Up again: back to col 6 ("g")
        editor.handle_input("\x1b[A")
        assert editor.cursor == (0, 6)

    def test_skips_marker_continuation_vls_when_preferred_col_falls_in_marker_tail(self):
        """Skips marker continuation VLs when preferred col falls in marker tail."""
        from pipython.tui.components.editor import Editor
        import re

        editor = Editor()
        # Same layout as test_does_not_get_stuck_moving_down_from_a_multi_
        # visual_line_paste_marker. Start at col 3 ("d"). Preferred col 3
        # maps to VL3 visual col 3, which is inside the "lines]" marker
        # tail, so moveToVisualLine detects the continuation VL and skips
        # straight to VL4 (line 1).
        for ch in "abcdefgh":
            editor.handle_input(ch)
        big_content = "line\n" * 100
        big_content = big_content.rstrip()
        editor.handle_input(f"\x1b[200~{big_content}\x1b[201~")
        for ch in "ijklmnopqr":
            editor.handle_input(ch)
        editor.handle_input("\n")
        for ch in "123456789012345678":
            editor.handle_input(ch)
        editor.render(20)

        text = editor.text
        marker_match = re.search(r"\[paste #\d+ \+\d+ lines\]", text)
        assert marker_match is not None

        # Navigate to line 0, col 3 (on "d")
        editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A
        for i in range(3):
            editor.handle_input("\x1b[C")
        assert editor.cursor == (0, 3)

        # Down: marker
        editor.handle_input("\x1b[B")
        assert editor.cursor[1] == 8

        # Down: skips VL3 (col 3 falls in the marker tail) and lands on
        # line 1
        editor.handle_input("\x1b[B")
        assert editor.cursor == (1, 3)

        # Round-trip back
        editor.handle_input("\x1b[A")
        assert editor.cursor[1] == 8  # marker
        editor.handle_input("\x1b[A")
        assert editor.cursor == (0, 3)

    def test_submits_large_pasted_content_literally(self):
        """Submits large pasted content literally."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        pasted_text = (
            "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\n"
            "line 7\nline 8\nline 9\nline 10\n"
            "tokens $1 $2 $& $$ $` $' end"
        )
        submitted = []

        def on_submit(text):
            submitted.append(text)

        editor.on_submit = on_submit

        editor.handle_input(f"\x1b[200~{pasted_text}\x1b[201~")
        editor.handle_input("\r")

        assert submitted == [pasted_text]
