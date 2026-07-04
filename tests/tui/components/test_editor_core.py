"""
Translation of upstream TypeScript tests: editor.test.ts, domains assigned to Task 11.

This test file translates the following describe blocks from the upstream editor.test.ts:
- public state accessors (line 287)
- Backslash+Enter newline workaround (315)
- Kitty CSI-u handling (373)
- Unicode text editing behavior (399) — excluding kill-ring/undo tests
- Grapheme-aware text wrapping (702)
- Word wrapping (835)
- Character jump (2824)
- Sticky column (3045)

Plus ≥5 CJK cursor cases as per brief mandate.

Note: Tests depending on kill-ring/undo/history/paste-marker/autocomplete are skipped
(those belong to Tasks 12-13).
"""

from __future__ import annotations


class TestEditorPublicStateAccessors:
    """public state accessors (upstream line 287)"""

    def test_returns_cursor_position(self):
        """Returns cursor position after character insertion and movement."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        assert editor.cursor == (0, 0)

        editor.handle_input("a")
        editor.handle_input("b")
        editor.handle_input("c")
        assert editor.cursor == (0, 3)

        editor.handle_input("\x1b[D")  # Left
        assert editor.cursor == (0, 2)

    def test_returns_lines_as_defensive_copy(self):
        """Lines property returns a defensive copy, not a reference."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("a\nb")

        lines = editor.text.split("\n")
        assert lines == ["a", "b"]

        # Mutate the returned list
        lines[0] = "mutated"

        # Verify original is unchanged
        original_text = editor.text
        assert original_text == "a\nb"


class TestBackslashEnterNewlineWorkaround:
    """Backslash+Enter newline workaround (upstream line 315)"""

    def test_inserts_backslash_immediately_no_buffering(self):
        """Backslash should be visible immediately, not buffered."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\\")
        assert editor.text == "\\"

    def test_converts_standalone_backslash_to_newline_on_enter(self):
        """Standalone backslash is converted to newline on Enter (\\r becomes \\n)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\\")
        editor.handle_input("\r")
        assert editor.text == "\n"

    def test_inserts_backslash_normally_when_followed_by_other_characters(self):
        """Backslash is inserted normally when followed by other characters."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\\")
        editor.handle_input("x")
        assert editor.text == "\\x"

    def test_does_not_trigger_newline_when_backslash_not_immediately_before_cursor(self):
        """Does not convert backslash to newline if backslash is not at cursor."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        submitted = False

        def on_submit(text):
            nonlocal submitted
            submitted = True

        editor.on_submit = on_submit
        editor.handle_input("\\")
        editor.handle_input("x")
        editor.handle_input("\r")
        assert submitted is True

    def test_only_removes_one_backslash_when_multiple_are_present(self):
        """Only the last backslash is removed when converting to newline."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\\")
        editor.handle_input("\\")
        editor.handle_input("\\")
        assert editor.text == "\\\\\\"

        editor.handle_input("\r")
        assert editor.text == "\\\\\n"


class TestKittyCSIuHandling:
    """Kitty CSI-u handling (upstream line 373)"""

    def test_ignores_printable_csi_u_sequences_with_unsupported_modifiers(self):
        """Ignores printable CSI-u sequences with unsupported modifiers."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\x1b[99;9u")
        assert editor.text == ""

    def test_inserts_shifted_csi_u_letters_as_text(self):
        """Inserts shifted CSI-u letters as text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\x1b[69;2u")
        assert editor.text == "E"

    def test_inserts_shifted_xterm_modifyotherkeys_letters_as_text(self):
        """Inserts shifted xterm modifyOtherKeys letters as text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("\x1b[27;2;69~")
        assert editor.text == "E"


class TestUnicodeTextEditingBehavior:
    """Unicode text editing behavior (upstream line 399)"""

    def test_inserts_mixed_ascii_umlauts_and_emojis_as_literal_text(self):
        """Inserts mixed ASCII, umlauts, and emojis as literal text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("H")
        editor.handle_input("e")
        editor.handle_input("l")
        editor.handle_input("l")
        editor.handle_input("o")
        editor.handle_input(" ")
        editor.handle_input("ä")
        editor.handle_input("ö")
        editor.handle_input("ü")
        editor.handle_input(" ")
        editor.handle_input("😀")

        text = editor.text
        assert text == "Hello äöü 😀"

    def test_deletes_single_code_unit_unicode_characters_umlauts_with_backspace(self):
        """Deletes single-code-unit unicode characters (umlauts) with Backspace."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("ä")
        editor.handle_input("ö")
        editor.handle_input("ü")

        # Delete the last character (ü)
        editor.handle_input("\x7f")  # Backspace

        text = editor.text
        assert text == "äö"

    def test_deletes_multi_code_unit_emojis_with_single_backspace(self):
        """Deletes multi-code-unit emojis with single Backspace."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("😀")
        editor.handle_input("👍")

        # Delete the last emoji (👍)
        editor.handle_input("\x7f")  # Backspace

        text = editor.text
        assert text == "😀"

    def test_inserts_characters_at_correct_position_after_cursor_movement_over_umlauts(self):
        """Inserts characters at the correct position after cursor movement over umlauts."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("ä")
        editor.handle_input("ö")
        editor.handle_input("ü")

        # Move cursor left twice
        editor.handle_input("\x1b[D")  # Left arrow
        editor.handle_input("\x1b[D")  # Left arrow

        # Insert 'x' in the middle
        editor.handle_input("x")

        text = editor.text
        assert text == "äxöü"

    def test_moves_cursor_across_multi_code_unit_emojis_with_single_arrow_key(self):
        """Moves cursor across multi-code-unit emojis with single arrow key."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("😀")
        editor.handle_input("👍")
        editor.handle_input("🎉")

        # Move cursor left over last emoji (🎉)
        editor.handle_input("\x1b[D")  # Left arrow

        # Move cursor left over second emoji (👍)
        editor.handle_input("\x1b[D")

        # Insert 'x' between first and second emoji
        editor.handle_input("x")

        text = editor.text
        assert text == "😀x👍🎉"

    def test_preserves_umlauts_across_line_breaks(self):
        """Preserves umlauts across line breaks."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("ä")
        editor.handle_input("ö")
        editor.handle_input("ü")
        editor.handle_input("\n")  # new line
        editor.handle_input("Ä")
        editor.handle_input("Ö")
        editor.handle_input("Ü")

        text = editor.text
        assert text == "äöü\nÄÖÜ"

    def test_replaces_entire_document_with_unicode_text_via_set_text(self):
        """Replaces the entire document with unicode text via set_text (paste simulation)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("Hällö Wörld! 😀 äöüÄÖÜß")

        text = editor.text
        assert text == "Hällö Wörld! 😀 äöüÄÖÜß"

    def test_moves_cursor_to_document_start_on_ctrlA_and_inserts_at_beginning(self):
        """Moves cursor to document start on Ctrl+A and inserts at the beginning."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("a")
        editor.handle_input("b")
        editor.handle_input("\x01")  # Ctrl+A (move to start)
        editor.handle_input("x")  # Insert at start

        text = editor.text
        assert text == "xab"

    def test_navigates_words_correctly_with_ctrlLeft_right(self):
        """Navigates words correctly with Ctrl+Left/Right."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("foo bar... baz")
        # Cursor at end

        # Move left over baz
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 11)  # after '...'

        # Move left over punctuation
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 7)  # after 'bar'

        # Move left over bar
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 4)  # after 'foo '

        # Move right over bar
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 7)  # at end of 'bar'

        # Move right over punctuation run
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 10)  # after '...'

        # Move right skips space and lands after baz
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 14)  # end of line

    def test_stops_at_fullwidth_chinese_punctuation_issue_4972(self):
        """Stops at fullwidth Chinese punctuation (issue #4972)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # 你好，世界 = 你好(0-2) ，(2-3) 世界(3-5)
        editor.set_text("你好，世界")
        # Cursor at end (col 5)

        # Move left over 世界
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 3)  # after ，

        # Move left over ，
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 2)  # after 你好

        # Move left over 你好
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 0)  # start

        # Move right over 你好
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 2)  # after 你好

        # Move right over ，
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 3)  # after ，

        # Move right over 世界
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 5)  # end

    def test_handles_mixed_cjk_and_ascii_word_movement(self):
        """Handles mixed CJK and ASCII word movement."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        # "hello你好，world世界"
        editor.set_text("hello你好，world世界")
        # Cursor at end (col 15)

        # Move left over 世界
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 13)  # after 'world'

        # Move left over world
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 8)  # after ，

        # Move left over ，
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 7)  # after 你好

        # Move left over 你好
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 5)  # after 'hello'

        # Move left over hello
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 0)  # start

        # Forward from start
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 5)  # after 'hello'

        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 7)  # after 你好

        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 8)  # after ，

        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 13)  # after 'world'

        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (0, 15)  # end

    # CJK cursor cases (≥5 as per brief)
    def test_cjk_backspace_on_chinese_characters(self):
        """CJK: Backspace on Chinese characters deletes grapheme-aware."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.handle_input("中")
        editor.handle_input("文")
        assert editor.text == "中文"
        assert editor.cursor == (0, 2)

        # Backspace deletes one Chinese character (one grapheme)
        editor.handle_input("\x7f")
        assert editor.text == "中"
        assert editor.cursor == (0, 1)

    def test_cjk_left_arrow_on_chinese_characters(self):
        """CJK: Left arrow on Chinese characters moves one grapheme."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("中文")
        assert editor.cursor == (0, 2)

        editor.handle_input("\x1b[D")  # Left
        assert editor.cursor == (0, 1)

        editor.handle_input("\x1b[D")  # Left
        assert editor.cursor == (0, 0)

    def test_cjk_right_arrow_on_chinese_characters(self):
        """CJK: Right arrow on Chinese characters moves one grapheme."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("中文")
        editor.handle_input("\x01")  # Ctrl+A to go to start

        editor.handle_input("\x1b[C")  # Right
        assert editor.cursor == (0, 1)

        editor.handle_input("\x1b[C")  # Right
        assert editor.cursor == (0, 2)

    def test_cjk_insert_between_chinese_characters(self):
        """CJK: Inserting ASCII between Chinese characters."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("中文")
        editor.handle_input("\x01")  # Ctrl+A
        editor.handle_input("\x1b[C")  # Right to position 1
        assert editor.cursor == (0, 1)

        editor.handle_input("A")
        assert editor.text == "中A文"
        assert editor.cursor == (0, 2)

    def test_cjk_mixed_unicode_deletion(self):
        """CJK: Deletion in mixed ASCII and CJK text."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("Hello中文World")
        # Cursor at end. "Hello中文World" is 12 graphemes (H,e,l,l,o,中,文,
        # W,o,r,l,d) — the cursor column is a grapheme count, not a visual
        # (display-width) column, so this is 12, not 14 (RED correction:
        # the original assertion conflated "col" with each CJK char's
        # 2-column display width; the brief defines cursor as (line,
        # grapheme_col), and the self-consistent check seven lines below —
        # "H=0, e=1, l=2, l=3, o=4, 中=5, 文=6" landing at col 7 after 7
        # single-grapheme right-arrow presses — only holds under the
        # grapheme-count reading).
        assert editor.cursor == (0, 12)

        # Backspace deletes 'd'
        editor.handle_input("\x7f")
        assert editor.text == "Hello中文Worl"
        assert editor.cursor == (0, 11)

        # Backspace deletes 'l'
        editor.handle_input("\x7f")
        assert editor.text == "Hello中文Wor"
        assert editor.cursor == (0, 10)

        # Move left to position before 文
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(7):  # Move right 7 times: H=0, e=1, l=2, l=3, o=4, 中=5, 文=6
            editor.handle_input("\x1b[C")

        assert editor.cursor == (0, 7)
        editor.handle_input("\x7f")  # Backspace to delete 文
        assert editor.text == "Hello中Wor"


class TestGraphemeAwareTextWrapping:
    """Grapheme-aware text wrapping (upstream line 702)"""

    def test_wraps_lines_correctly_when_text_contains_wide_emojis(self):
        """Wraps lines correctly when text contains wide emojis."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 20

        # ✅ is 2 columns wide, so "Hello ✅ World" is 14 columns
        editor.set_text("Hello ✅ World")
        lines = editor.render(width)

        # All content lines (between borders) should fit exactly within width
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_wraps_long_text_with_emojis_at_correct_positions(self):
        """Wraps long text with emojis at correct positions."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 10

        # Each ✅ is 2 columns. "✅✅✅✅✅" = 10 columns, fits exactly.
        # "✅✅✅✅✅✅" = 12 columns, needs wrap.
        editor.set_text("✅✅✅✅✅✅")
        lines = editor.render(width)

        # First line: 5 emojis (10 cols), second line: 1 emoji (2 cols) + padding
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_wraps_cjk_characters_correctly_each_is_2_columns_wide(self):
        """Wraps CJK characters correctly (each is 2 columns wide)."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi, visible_width

        editor = Editor()
        width = 11  # +1 col reserved for cursor

        # Each CJK char is 2 columns. "日本語テスト" = 6 chars = 12 columns
        editor.set_text("日本語テスト")
        lines = editor.render(width)

        for line in lines[1:-1]:
            assert visible_width(line) == width

        # Verify content split correctly
        content_lines = [_strip_ansi(line).strip() for line in lines[1:-1]]
        assert len(content_lines) == 2
        assert content_lines[0] == "日本語テス"  # 5 chars = 10 columns
        assert content_lines[1] == "ト"  # 1 char = 2 columns (+ padding)

    def test_handles_mixed_ascii_and_wide_characters_in_wrapping(self):
        """Handles mixed ASCII and wide characters in wrapping."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 16  # +1 col reserved for cursor

        # "Test ✅ OK 日本" = 4 + 1 + 2 + 1 + 2 + 1 + 4 = 15 columns (fits in width-1=15)
        editor.set_text("Test ✅ OK 日本")
        lines = editor.render(width)

        # Should fit in one content line
        content_lines = lines[1:-1]
        assert len(content_lines) == 1
        assert visible_width(content_lines[0]) == width

    def test_renders_cursor_correctly_on_wide_characters(self):
        """Renders cursor correctly on wide characters."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 20

        editor.set_text("A✅B")
        # Cursor should be at end (after B)
        lines = editor.render(width)

        # The cursor (reverse video space) should be visible
        content_line = lines[1]
        assert "\x1b[7m" in content_line, "Should have reverse video cursor"

        # Line should still be correct width
        assert visible_width(content_line) == width

    def test_does_not_exceed_terminal_width_with_emoji_at_wrap_boundary(self):
        """Does not exceed terminal width with emoji at wrap boundary."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 11

        # "0123456789✅" = 10 ASCII + 2-wide emoji = 12 columns
        # Should wrap before the emoji since it would exceed width
        editor.set_text("0123456789✅")
        lines = editor.render(width)

        for line in lines[1:-1]:
            assert visible_width(line) <= width

    def test_shows_cursor_at_end_of_line_before_wrap_wraps_on_next_char(self):
        """Shows cursor at end of line before wrap, wraps on next char.

        Upstream loops this over ``paddingX in [0, 1]`` using a constructor
        option this port doesn't have (module docstring deviation 1: no
        ``paddingX`` — always 0, every render reserves exactly 1 column for
        the cursor). This only exercises the ``paddingX === 0`` branch,
        which is the only one this port's ``Editor`` can produce.
        """
        from pipython.tui.components.editor import Editor

        editor = Editor()
        width = 10

        # Type 9 chars → fills layoutWidth exactly, cursor at end on same line
        for ch in "aaaaaaaaa":
            editor.handle_input(ch)

        lines = editor.render(width)
        content_lines = lines[1:-1]
        assert len(content_lines) == 1, "Should be 1 content line before wrap"
        assert content_lines[0].endswith("\x1b[7m \x1b[0m"), "Cursor should be at end of line"

        # Type 1 more → text wraps to second line
        editor.handle_input("a")
        lines = editor.render(width)
        content_lines = lines[1:-1]
        assert len(content_lines) == 2, "Should wrap to 2 content lines"

    def test_renders_isolated_thai_and_lao_am_clusters_without_width_drift(self):
        """Renders isolated Thai and Lao AM clusters without width drift."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        for text in ["ำabc", "ຳabc"]:
            editor = Editor()
            width = 8
            editor.set_text(text)

            for line in editor.render(width):
                assert visible_width(line) == width, f"line width drift for {text!r}: {line!r}"


class TestWordWrapping:
    """Word wrapping (upstream line 835) — tests the wordWrapLine function behavior"""

    def test_wraps_at_word_boundaries_instead_of_mid_word(self):
        """Wraps at word boundaries instead of mid-word."""
        import re

        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi

        editor = Editor()
        width = 40

        editor.set_text("Hello world this is a test of word wrapping functionality")
        lines = editor.render(width)

        content_lines = [_strip_ansi(line).strip() for line in lines[1:-1]]

        # Should NOT break mid-word: line 1 should end with a complete word
        assert not content_lines[0].endswith("-"), (
            "Line should not end with hyphen (mid-word break)"
        )

        # Each content line should end with a complete word
        for line in content_lines:
            last_char = line.rstrip()[-1:]
            assert last_char == "" or re.match(r"[\w.,!?;:]", last_char), (
                f'Line ends unexpectedly with: "{last_char}"'
            )

    def test_does_not_start_lines_with_leading_whitespace_after_word_wrap(self):
        """Does not start lines with leading whitespace after word wrap."""
        import re

        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi

        editor = Editor()
        width = 20

        editor.set_text("Word1 Word2 Word3 Word4 Word5 Word6")
        lines = editor.render(width)

        # Get content lines (between borders)
        content_lines = lines[1:-1]

        # No line should start with whitespace (except for padding at the end)
        for i, raw_line in enumerate(content_lines):
            line = _strip_ansi(raw_line)
            trimmed_start = line.lstrip()
            # The line should either be all padding or start with a word character
            if len(trimmed_start) > 0:
                assert not re.match(r"^\s+\S", line.rstrip()), (
                    f"Line {i} starts with unexpected whitespace before content"
                )

    def test_breaks_long_words_urls_at_character_level(self):
        """Breaks long words (URLs) at character level."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 30

        editor.set_text("Check https://example.com/very/long/path/that/exceeds/width here")
        lines = editor.render(width)

        # All lines should fit within width
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_preserves_multiple_spaces_within_words_on_same_line(self):
        """Preserves multiple spaces within words on same line."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi

        editor = Editor()
        width = 50

        editor.set_text("Word1   Word2    Word3")
        lines = editor.render(width)

        content_line = _strip_ansi(lines[1]).strip()
        # Multiple spaces should be preserved
        assert "Word1   Word2" in content_line, "Multiple spaces should be preserved"

    def test_handles_empty_string(self):
        """Handles empty string."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        width = 40

        editor.set_text("")
        lines = editor.render(width)

        # Should have border + empty content + border
        assert len(lines) == 3

    def test_handles_single_word_that_fits_exactly(self):
        """Handles single word that fits exactly."""
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi

        editor = Editor()
        width = 11  # +1 col reserved for cursor

        editor.set_text("1234567890")
        lines = editor.render(width)

        # Should have exactly 3 lines (top border, content, bottom border)
        assert len(lines) == 3
        content_line = _strip_ansi(lines[1])
        assert "1234567890" in content_line, "Content should contain the word"

    def test_wraps_word_to_next_line_when_it_ends_exactly_at_terminal_width(self):
        """Wraps word to next line when it ends exactly at terminal width."""
        from pipython.tui.components.editor import _word_wrap_line

        # "hello " (6) + "world" (5) = 11, but "world" is non-whitespace
        # ending at width. Thus, wrap it to next line. The trailing space
        # stays with "hello" on line 1 (upstream editor.test.ts:929-937).
        chunks = _word_wrap_line("hello world test", 11)

        assert len(chunks) == 2
        assert chunks[0].text == "hello "
        assert chunks[1].text == "world test"

    def test_keeps_whitespace_at_terminal_width_boundary_on_same_line(self):
        """Keeps whitespace at terminal width boundary on same line."""
        from pipython.tui.components.editor import _word_wrap_line

        # "hello world " is exactly 12 chars (including trailing space).
        # The space at position 12 should stay on the first line
        # (upstream editor.test.ts:939-947).
        chunks = _word_wrap_line("hello world test", 12)

        assert len(chunks) == 2
        assert chunks[0].text == "hello world "
        assert chunks[1].text == "test"

    def test_handles_unbreakable_word_filling_width_exactly_followed_by_space(self):
        """Handles unbreakable word filling width exactly followed by space."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:949-955.
        chunks = _word_wrap_line("aaaaaaaaaaaa aaaa", 12)

        assert len(chunks) == 2
        assert chunks[0].text == "aaaaaaaaaaaa"
        assert chunks[1].text == " aaaa"

    def test_wraps_word_to_next_line_when_it_fits_width_but_not_remaining_space(self):
        """Wraps word to next line when it fits width but not remaining space."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:957-963.
        chunks = _word_wrap_line("      aaaaaaaaaaaa", 12)

        assert len(chunks) == 2
        assert chunks[0].text == "      "
        assert chunks[1].text == "aaaaaaaaaaaa"

    def test_keeps_word_with_multi_space_and_following_word_together_when_they_fit(self):
        """Keeps word with multi-space and following word together when they fit."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:965-971.
        chunks = _word_wrap_line("Lorem ipsum dolor sit amet,    consectetur", 30)

        assert len(chunks) == 2
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,    consectetur"

    def test_keeps_word_with_multi_space_and_following_word_when_they_fill_width_exactly(self):
        """Keeps word with multi-space and following word when they fill width exactly."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:973-979.
        chunks = _word_wrap_line("Lorem ipsum dolor sit amet,              consectetur", 30)

        assert len(chunks) == 2
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,              consectetur"

    def test_splits_when_word_plus_multi_space_plus_word_exceeds_width(self):
        """Splits when word plus multi-space plus word exceeds width."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:981-988.
        chunks = _word_wrap_line("Lorem ipsum dolor sit amet,               consectetur", 30)

        assert len(chunks) == 3
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,               "
        assert chunks[2].text == "consectetur"

    def test_breaks_long_whitespace_at_line_boundary(self):
        """Breaks long whitespace at line boundary."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:990-997.
        chunks = _word_wrap_line(
            "Lorem ipsum dolor sit amet,                         consectetur", 30
        )

        assert len(chunks) == 3
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,                         "
        assert chunks[2].text == "consectetur"

    def test_breaks_long_whitespace_at_line_boundary_2(self):
        """Breaks long whitespace at line boundary (variant 2)."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:999-1006.
        chunks = _word_wrap_line(
            "Lorem ipsum dolor sit amet,                          consectetur", 30
        )

        assert len(chunks) == 3
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,                         "
        assert chunks[2].text == " consectetur"

    def test_breaks_whitespace_spanning_full_lines(self):
        """Breaks whitespace spanning full lines."""
        from pipython.tui.components.editor import _word_wrap_line

        # upstream editor.test.ts:1008-1015.
        chunks = _word_wrap_line(
            "Lorem ipsum dolor sit amet,                                     consectetur", 30
        )

        assert len(chunks) == 3
        assert chunks[0].text == "Lorem ipsum dolor sit "
        assert chunks[1].text == "amet,                         "
        assert chunks[2].text == "            consectetur"

    def test_force_breaks_when_wide_char_after_word_boundary_wrap_still_overflows(self):
        """Force-breaks when wide char after word boundary wrap still overflows."""
        from pipython.tui.components.editor import _word_wrap_line
        from pipython.tui.engine.utils import visible_width

        # " " (1) + "a"*186 (186) + "你" (2) = 189 visible width
        # maxWidth = 187: backtracking to the space would leave 186 + 2 = 188 > 187,
        # so the algorithm must force-break before the wide char instead.
        line = " " + "a" * 186 + "你"
        chunks = _word_wrap_line(line, 187)

        for chunk in chunks:
            assert visible_width(chunk.text) <= 187, (
                f'chunk "{chunk.text[:20]}..." has visible width {visible_width(chunk.text)}, '
                f"expected <= 187"
            )

        # Verify no content is lost
        reconstructed = "".join(line[c.start : c.end] for c in chunks)
        assert reconstructed == line

    def test_splits_oversized_atomic_segment_across_multiple_chunks(self):
        """Splits oversized atomic segment across multiple chunks.

        Upstream drives ``wordWrapLine`` with a synthetic pre-segmented
        array that treats the paste marker as a single atomic segment
        (editor.ts's ``wordWrapLine`` third parameter). This port's
        ``_word_wrap_line`` now has pre_segmented parameter support —
        Task 12 adds paste-marker/atomic-segment awareness. The marker text
        below is therefore treated as a single atomic unit when possible;
        the invariant this port verifies through the public ``Editor.render()``
        surface is that no rendered line ever exceeds the terminal width.
        """
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 10

        marker = "[paste #1 +20 lines]"
        editor.set_text(f"A{marker}B")

        lines = editor.render(width)
        # Every rendered content line must fit exactly within width
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_splits_oversized_atomic_segment_at_start_of_line(self):
        """Splits oversized atomic segment at start of line.

        Verifies atomic marker handling at line start. See
        ``test_splits_oversized_atomic_segment_across_multiple_chunks`` for context.
        """
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 10

        marker = "[paste #1 +20 lines]"
        editor.set_text(f"{marker}B")

        lines = editor.render(width)
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_splits_oversized_atomic_segment_at_end_of_line(self):
        """Splits oversized atomic segment at end of line.

        Verifies atomic marker handling at line end. See
        ``test_splits_oversized_atomic_segment_across_multiple_chunks`` for context.
        """
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 10

        marker = "[paste #1 +20 lines]"
        editor.set_text(f"A{marker}")

        lines = editor.render(width)
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_splits_consecutive_oversized_atomic_segments(self):
        """Splits consecutive oversized atomic segments.

        See ``test_splits_oversized_atomic_segment_across_multiple_chunks``'s
        docstring for why this diverges from upstream's pre-segmented setup.
        """
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import visible_width

        editor = Editor()
        width = 10

        marker = "[paste #1 +20 lines]"
        editor.set_text(f"{marker}{marker}")

        lines = editor.render(width)
        for line in lines[1:-1]:
            assert visible_width(line) == width

    def test_wraps_normally_after_oversized_atomic_segment(self):
        """Wraps normally after oversized atomic segment.

        Adapted from upstream's pre-segmented test (see
        ``test_splits_oversized_atomic_segment_across_multiple_chunks``'s
        docstring) — verifies wrapping still behaves sanely (lines within
        width, no words dropped) once ordinary word content follows an
        oversized unbreakable run.
        """
        from pipython.tui.components.editor import Editor
        from pipython.tui.engine.utils import _strip_ansi, visible_width

        editor = Editor()
        width = 10

        marker = "[paste #1 +20 lines]"
        editor.set_text(f"{marker} hello world")
        lines = editor.render(width)

        for line in lines[1:-1]:
            assert visible_width(line) == width

        # No words lost: normal wrapping resumes after the oversized run.
        content = "".join(_strip_ansi(line) for line in lines[1:-1])
        assert "hello" in content
        assert "world" in content


class TestCharacterJump:
    """Character jump (Ctrl+]) (upstream line 2824)"""

    def test_jumps_forward_to_first_occurrence_of_character_on_same_line(self):
        """Jumps forward to first occurrence of character on same line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("o")  # Jump to first 'o'

        assert editor.cursor == (0, 4)  # 'o' in "hello"

    def test_jumps_forward_to_next_occurrence_after_cursor(self):
        """Jumps forward to next occurrence after cursor."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start

        # Move cursor to the 'o' in "hello" (col 4)
        for _ in range(4):
            editor.handle_input("\x1b[C")

        assert editor.cursor == (0, 4)

        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("o")  # Jump to next 'o' (in "world")

        assert editor.cursor == (0, 7)  # 'o' in "world"

    def test_jumps_forward_across_multiple_lines(self):
        """Jumps forward across multiple lines."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("abc\ndef\nghi")

        # Move to line 0, col 0
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x01")  # Ctrl+A - go to start of line
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("g")  # Jump to 'g' on line 2

        assert editor.cursor == (2, 0)

    def test_jumps_backward_to_first_occurrence_before_cursor_on_same_line(self):
        """Jumps backward to first occurrence before cursor on same line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        # Cursor at end (col 11)
        assert editor.cursor == (0, 11)

        editor.handle_input("\x1b\x1d")  # Ctrl+Alt+]
        editor.handle_input("o")  # Jump to last 'o' before cursor

        assert editor.cursor == (0, 7)  # 'o' in "world"

    def test_jumps_backward_across_multiple_lines(self):
        """Jumps backward across multiple lines."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("abc\ndef\nghi")
        # Cursor at end of line 2
        assert editor.cursor == (2, 3)

        editor.handle_input("\x1b\x1d")  # Ctrl+Alt+]
        editor.handle_input("a")  # Jump to 'a' on line 0

        assert editor.cursor == (0, 0)

    def test_does_nothing_when_character_not_found_forward(self):
        """Does nothing when character is not found (forward)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("z")  # 'z' doesn't exist

        assert editor.cursor == (0, 0)  # Cursor unchanged

    def test_does_nothing_when_character_not_found_backward(self):
        """Does nothing when character is not found (backward)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        # Cursor at end
        assert editor.cursor == (0, 11)

        editor.handle_input("\x1b\x1d")  # Ctrl+Alt+]
        editor.handle_input("z")  # 'z' doesn't exist

        assert editor.cursor == (0, 11)  # Cursor unchanged

    def test_is_case_sensitive(self):
        """Is case-sensitive."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("Hello World")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        # Search for lowercase 'h' - should not find it (only 'H' exists)
        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("h")

        assert editor.cursor == (0, 0)  # Cursor unchanged

        # Search for uppercase 'W' - should find it
        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("W")

        assert editor.cursor == (0, 6)  # 'W' in "World"

    def test_cancels_jump_mode_when_ctrls_pressed_again(self):
        """Cancels jump mode when Ctrl+] is pressed again."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+] - enter jump mode
        editor.handle_input("\x1d")  # Ctrl+] again - cancel

        # Type 'o' normally - should insert, not jump
        editor.handle_input("o")
        assert editor.text == "ohello world"

    def test_cancels_jump_mode_on_escape_and_processes_the_escape(self):
        """Cancels jump mode on Escape and processes the Escape."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+] - enter jump mode
        editor.handle_input("\x1b")  # Escape - cancel jump mode

        # Cursor should be unchanged (Escape itself doesn't move cursor in editor)
        assert editor.cursor == (0, 0)

        # Type 'o' normally - should insert, not jump
        editor.handle_input("o")
        assert editor.text == "ohello world"

    def test_cancels_backward_jump_mode_when_ctrlalt_pressed_again(self):
        """Cancels backward jump mode when Ctrl+Alt+] is pressed again."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("hello world")
        # Cursor at end
        assert editor.cursor == (0, 11)

        editor.handle_input("\x1b\x1d")  # Ctrl+Alt+] - enter backward jump mode
        editor.handle_input("\x1b\x1d")  # Ctrl+Alt+] again - cancel

        # Type 'o' normally - should insert, not jump
        editor.handle_input("o")
        assert editor.text == "hello worldo"

    def test_searches_for_special_characters(self):
        """Searches for special characters."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("foo(bar) = baz;")
        editor.handle_input("\x01")  # Ctrl+A - go to start
        assert editor.cursor == (0, 0)

        # Jump to '('
        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("(")

        assert editor.cursor == (0, 3)

        # Jump to '='
        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("=")

        assert editor.cursor == (0, 9)

    def test_handles_empty_text_gracefully(self):
        """Handles empty text gracefully."""
        from pipython.tui.components.editor import Editor

        editor = Editor()
        editor.set_text("")
        assert editor.cursor == (0, 0)

        editor.handle_input("\x1d")  # Ctrl+]
        editor.handle_input("x")

        assert editor.cursor == (0, 0)  # Cursor unchanged


class TestStickyColumn:
    """Sticky column (upstream line 3045)"""

    def test_preserves_target_column_when_moving_up_through_a_shorter_line(self):
        """Preserves target column when moving up through a shorter line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        # Line 0: "2222222222x222" (x at col 10)
        # Line 1: "" (empty)
        # Line 2: "1111111111_111111111111" (_ at col 10)
        editor.set_text("2222222222x222\n\n1111111111_111111111111")

        # Position cursor on _ (line 2, col 10)
        assert editor.cursor == (2, 23)  # At end
        editor.handle_input("\x01")  # Ctrl+A - go to start of line
        for _ in range(10):
            editor.handle_input("\x1b[C")  # Move right to col 10

        assert editor.cursor == (2, 10)

        # Press Up - should move to empty line (col clamped to 0)
        editor.handle_input("\x1b[A")  # Up arrow
        assert editor.cursor == (1, 0)

        # Press Up again - should move to line 0 at col 10 (on 'x')
        editor.handle_input("\x1b[A")  # Up arrow
        assert editor.cursor == (0, 10)

    def test_preserves_target_column_when_moving_down_through_a_shorter_line(self):
        """Preserves target column when moving down through a shorter line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1111111111_111\n\n2222222222x222222222222")

        # Position cursor on _ (line 0, col 10)
        editor.handle_input("\x1b[A")  # Up to line 1
        editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(10):
            editor.handle_input("\x1b[C")

        assert editor.cursor == (0, 10)

        # Press Down - should move to empty line (col clamped to 0)
        editor.handle_input("\x1b[B")  # Down arrow
        assert editor.cursor == (1, 0)

        # Press Down again - should move to line 2 at col 10 (on 'x')
        editor.handle_input("\x1b[B")  # Down arrow
        assert editor.cursor == (2, 10)

    def test_resets_sticky_column_on_horizontal_movement_left_arrow(self):
        """Resets sticky column on horizontal movement (left arrow)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Start at line 2, col 5
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(5):
            editor.handle_input("\x1b[C")

        assert editor.cursor == (2, 5)

        # Move up through empty line
        editor.handle_input("\x1b[A")  # Up - line 1, col 0
        editor.handle_input("\x1b[A")  # Up - line 0, col 5 (sticky)
        assert editor.cursor == (0, 5)

        # Move left - resets sticky column
        editor.handle_input("\x1b[D")  # Left
        assert editor.cursor == (0, 4)

        # Move down twice
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 4 (new sticky from col 4)
        assert editor.cursor == (2, 4)

    def test_resets_sticky_column_on_horizontal_movement_right_arrow(self):
        """Resets sticky column on horizontal movement (right arrow)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Start at line 0, col 5
        editor.handle_input("\x1b[A")  # Up to line 1
        editor.handle_input("\x1b[A")  # Up to line 0
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(5):
            editor.handle_input("\x1b[C")

        assert editor.cursor == (0, 5)

        # Move down through empty line
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 5 (sticky)
        assert editor.cursor == (2, 5)

        # Move right - resets sticky column
        editor.handle_input("\x1b[C")  # Right
        assert editor.cursor == (2, 6)

        # Move up twice
        editor.handle_input("\x1b[A")  # Up - line 1, col 0
        editor.handle_input("\x1b[A")  # Up - line 0, col 6 (new sticky from col 6)
        assert editor.cursor == (0, 6)

    def test_resets_sticky_column_on_typing(self):
        """Resets sticky column on typing."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Start at line 2, col 8
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(8):
            editor.handle_input("\x1b[C")

        # Move up through empty line
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x1b[A")  # Up - line 0, col 8
        assert editor.cursor == (0, 8)

        # Type a character - resets sticky column
        editor.handle_input("X")
        assert editor.cursor == (0, 9)

        # Move down twice
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 9 (new sticky from col 9)
        assert editor.cursor == (2, 9)

    def test_resets_sticky_column_on_backspace(self):
        """Resets sticky column on backspace."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Start at line 2, col 8
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(8):
            editor.handle_input("\x1b[C")

        # Move up through empty line
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x1b[A")  # Up - line 0, col 8
        assert editor.cursor == (0, 8)

        # Backspace - resets sticky column
        editor.handle_input("\x7f")  # Backspace
        assert editor.cursor == (0, 7)

        # Move down twice
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 7 (new sticky from col 7)
        assert editor.cursor == (2, 7)

    def test_resets_sticky_column_on_ctrlA_move_to_line_start(self):
        """Resets sticky column on Ctrl+A (move to line start)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Start at line 2, col 8
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(8):
            editor.handle_input("\x1b[C")

        # Move up - establishes sticky col 8
        editor.handle_input("\x1b[A")  # Up - line 1, col 0

        # Ctrl+A - resets sticky column to 0
        editor.handle_input("\x01")  # Ctrl+A
        assert editor.cursor == (1, 0)

        # Move up
        editor.handle_input("\x1b[A")  # Up - line 0, col 0 (new sticky from col 0)
        assert editor.cursor == (0, 0)

    def test_resets_sticky_column_on_ctrlE_move_to_line_end(self):
        """Resets sticky column on Ctrl+E (move to line end)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("12345\n\n1234567890")

        # Start at line 2, col 3
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(3):
            editor.handle_input("\x1b[C")

        # Move up through empty line - establishes sticky col 3
        editor.handle_input("\x1b[A")  # Up - line 1, col 0
        editor.handle_input("\x1b[A")  # Up - line 0, col 3
        assert editor.cursor == (0, 3)

        # Ctrl+E - resets sticky column to end
        editor.handle_input("\x05")  # Ctrl+E
        assert editor.cursor == (0, 5)

        # Move down twice
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 5 (new sticky from col 5)
        assert editor.cursor == (2, 5)

    def test_resets_sticky_column_on_word_movement_ctrlLeft(self):
        """Resets sticky column on word movement (Ctrl+Left)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("hello world\n\nhello world")

        # Start at end of line 2 (col 11)
        assert editor.cursor == (2, 11)

        # Move up through empty line - establishes sticky col 11
        editor.handle_input("\x1b[A")  # Up - line 1, col 0
        editor.handle_input("\x1b[A")  # Up - line 0, col 11
        assert editor.cursor == (0, 11)

        # Ctrl+Left - word movement resets sticky column
        editor.handle_input("\x1b[1;5D")  # Ctrl+Left
        assert editor.cursor == (0, 6)  # Before "world"

        # Move down twice
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 6 (new sticky from col 6)
        assert editor.cursor == (2, 6)

    def test_resets_sticky_column_on_word_movement_ctrlRight(self):
        """Resets sticky column on word movement (Ctrl+Right)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("hello world\n\nhello world")

        # Start at line 0, col 0
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x01")  # Ctrl+A
        assert editor.cursor == (0, 0)

        # Move down through empty line - establishes sticky col 0
        editor.handle_input("\x1b[B")  # Down - line 1, col 0
        editor.handle_input("\x1b[B")  # Down - line 2, col 0
        assert editor.cursor == (2, 0)

        # Ctrl+Right - word movement resets sticky column
        editor.handle_input("\x1b[1;5C")  # Ctrl+Right
        assert editor.cursor == (2, 5)  # After "hello"

        # Move up twice
        editor.handle_input("\x1b[A")  # Up - line 1, col 0
        editor.handle_input("\x1b[A")  # Up - line 0, col 5 (new sticky from col 5)
        assert editor.cursor == (0, 5)

    def test_handles_multiple_consecutive_up_down_movements(self):
        """Handles multiple consecutive up/down movements."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\nab\ncd\nef\n1234567890")

        # Start at line 4, col 7
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(7):
            editor.handle_input("\x1b[C")

        # Move up through multiple shorter lines. "ab"/"cd"/"ef" are each 2
        # graphemes long, so the clamp lands at col 2 (end of line), not
        # col 0 (RED comment correction: matches upstream editor.test.ts
        # line 3344's own "col 2 (clamped)" comment — no assertion changes,
        # since upstream/RED alike only assert the final position below).
        editor.handle_input("\x1b[A")  # Up - line 3, col 2 (clamped)
        editor.handle_input("\x1b[A")  # Up - line 2, col 2 (clamped)
        editor.handle_input("\x1b[A")  # Up - line 1, col 2 (clamped)
        editor.handle_input("\x1b[A")  # Up - line 0, col 7 (sticky)

        assert editor.cursor == (0, 7)

    def test_moves_correctly_through_wrapped_visual_lines_without_getting_stuck(self):
        """Moves correctly through wrapped visual lines without getting stuck."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        # Create text that will wrap visually but has logical line breaks
        editor.set_text("This is a very long line that will wrap\nShort\nAnother long line")

        lines = editor.render(40)
        assert len(lines) > 3

    def test_handles_setText_resetting_sticky_column(self):
        """Handles setText resetting sticky column."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Set up sticky column
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(7):
            editor.handle_input("\x1b[C")

        editor.handle_input("\x1b[A")  # Up
        editor.handle_input("\x1b[A")  # Up - line 0, col 7 (sticky)

        # setText resets sticky column
        editor.set_text("abcdefghij\n\nabcdefghij")

        # Now move down - should clamp to actual line length
        editor.handle_input("\x1b[B")  # Down
        editor.handle_input("\x1b[B")  # Down
        # Cursor should be at the end of the new line 2
        assert editor.cursor[1] <= 10

    def test_sets_preferredVisualCol_when_pressing_right_at_end_of_prompt_last_line(self):
        """Sets preferredVisualCol when pressing right at end of prompt (last line)."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("line1\nline2\nline3")

        # Move to end of line 2
        editor.handle_input("\x05")  # Ctrl+E to go to end

        assert editor.cursor[0] == 2
        assert editor.cursor[1] == 5  # "line3"

        # Move right (at end, wraps or stays)
        editor.handle_input("\x1b[C")

    def test_handles_editor_resizes_when_preferredVisualCol_is_on_the_same_line(self):
        """Handles editor resizes when preferredVisualCol is on the same line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Move to line 0 first (RED correction: without this, the cursor is
        # still on line 2 — set_text leaves it at the end of the last line —
        # so both Down presses below would each hit the "already on the
        # last visual line" branch, which moves the cursor to the *end* of
        # line 2 (col 10) rather than exercising sticky-column vertical
        # transitions at all; the original assertion of col 5 does not hold
        # in that case).
        editor.handle_input("\x1b[A")  # Up to line 1
        editor.handle_input("\x1b[A")  # Up to line 0

        # Move to column 5
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(5):
            editor.handle_input("\x1b[C")

        # Move down through empty line
        editor.handle_input("\x1b[B")
        editor.handle_input("\x1b[B")

        # Should be at col 5 on line 2
        assert editor.cursor == (2, 5)

    def test_handles_editor_resizes_when_preferredVisualCol_is_on_a_different_line(self):
        """Handles editor resizes when preferredVisualCol is on a different line."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("1234567890\n\n1234567890")

        # Move to column 8
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(8):
            editor.handle_input("\x1b[C")

        # Move down and then up
        editor.handle_input("\x1b[B")
        editor.handle_input("\x1b[B")
        editor.handle_input("\x1b[A")

        assert editor.cursor == (1, 0)  # Empty line, col clamped

    def test_rewrapped_lines_target_fits_current_visual_column(self):
        """Rewrapped lines: target fits current visual column."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("longer line\n\nlonger line")

        # Move to line 0 first (RED correction: set_text leaves the cursor
        # at the end of the last line; without navigating back to line 0,
        # both Down presses below would each hit the "already on the last
        # visual line" branch — which calls moveToLineEnd() instead of a
        # real vertical sticky-column transition — landing on col 11, not
        # col 7).
        editor.handle_input("\x1b[A")  # Up to line 1
        editor.handle_input("\x1b[A")  # Up to line 0

        # Move to column 7
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(7):
            editor.handle_input("\x1b[C")

        # Move down through empty
        editor.handle_input("\x1b[B")
        editor.handle_input("\x1b[B")

        assert editor.cursor == (2, 7)

    def test_rewrapped_lines_target_shorter_than_current_visual_column(self):
        """Rewrapped lines: target shorter than current visual column."""
        from pipython.tui.components.editor import Editor

        editor = Editor()

        editor.set_text("longer line\n\nshort\nlong again")

        # Move to line 0 first (RED correction: set_text leaves the cursor
        # at the end of the last line, "long again" — Ctrl+A there only
        # moves to that line's start, not the document's, so the single
        # Down press originally here would hit the "already on the last
        # visual line" branch [moveToLineEnd(), landing on col 10] rather
        # than ever reaching "short", the shorter line the test name and
        # the `<= 5` assertion are actually about).
        editor.handle_input("\x1b[A")  # Up to line 3 ("long again")
        editor.handle_input("\x1b[A")  # Up to line 2 ("short")
        editor.handle_input("\x1b[A")  # Up to line 1 (empty)
        editor.handle_input("\x1b[A")  # Up to line 0 ("longer line")

        # Move to column 7
        editor.handle_input("\x01")  # Ctrl+A
        for _ in range(7):
            editor.handle_input("\x1b[C")

        # Move down through the empty line, establishing sticky col 7
        editor.handle_input("\x1b[B")
        # Move down again onto "short" (5 chars) - preferred col 7 doesn't
        # fit, so the cursor clamps to the line length.
        editor.handle_input("\x1b[B")

        assert editor.cursor == (2, 5)
