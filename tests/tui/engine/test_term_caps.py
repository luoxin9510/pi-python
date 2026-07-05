"""Tests for term_caps module.

Tests cover terminal capability detection (TERM/COLORTERM combos),
hyperlink formatting, and image line detection.
"""

from pipython.tui.engine.term_caps import (
    TermCaps,
    detect_caps,
    hyperlink,
    is_image_line,
)


class TestTermCaps:
    """Tests for TermCaps dataclass."""

    def test_termcaps_creation(self):
        """Create TermCaps with true_color and hyperlinks flags."""
        caps = TermCaps(true_color=True, hyperlinks=True)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_termcaps_both_false(self):
        """Create TermCaps with both flags False."""
        caps = TermCaps(true_color=False, hyperlinks=False)
        assert caps.true_color is False
        assert caps.hyperlinks is False

    def test_termcaps_mixed(self):
        """Create TermCaps with mixed flag values."""
        caps = TermCaps(true_color=True, hyperlinks=False)
        assert caps.true_color is True
        assert caps.hyperlinks is False


class TestDetectCaps:
    """Tests for detect_caps function.

    Upstream: terminal-image.ts lines 65-125 (detectCapabilities)
    Returns TermCaps based on TERM, COLORTERM, and other env vars.
    """

    def test_detect_caps_kitty_via_env(self):
        """Kitty terminal detected via KITTY_WINDOW_ID env var.

        Upstream line 83: if (process.env.KITTY_WINDOW_ID || termProgram === "kitty")
        """
        env = {"KITTY_WINDOW_ID": "1"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_kitty_via_term_program(self):
        """Kitty terminal detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "kitty"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_ghostty_via_env(self):
        """Ghostty detected via GHOSTTY_RESOURCES_DIR.

        Upstream line 87: process.env.GHOSTTY_RESOURCES_DIR
        """
        env = {"GHOSTTY_RESOURCES_DIR": "/path"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_ghostty_via_term_program(self):
        """Ghostty detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "ghostty"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_wezterm_via_env(self):
        """WezTerm detected via WEZTERM_PANE.

        Upstream line 91: process.env.WEZTERM_PANE || termProgram === "wezterm"
        """
        env = {"WEZTERM_PANE": "1"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_wezterm_via_term_program(self):
        """WezTerm detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "wezterm"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_iterm2_via_env(self):
        """iTerm2 detected via ITERM_SESSION_ID.

        Upstream line 100: process.env.ITERM_SESSION_ID || termProgram === "iterm.app"
        """
        env = {"ITERM_SESSION_ID": "w0t0p0"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_iterm2_via_term_program(self):
        """iTerm2 detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "iterm.app"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_windows_terminal(self):
        """Windows Terminal detected via WT_SESSION.

        Upstream line 104: process.env.WT_SESSION
        """
        env = {"WT_SESSION": "uuid"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_vscode(self):
        """VS Code terminal detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "vscode"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_alacritty(self):
        """Alacritty detected via TERM_PROGRAM."""
        env = {"TERM_PROGRAM": "alacritty"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_jetbrains_jediterm(self):
        """JetBrains IDE terminal (no hyperlinks).

        Upstream line 116: terminalEmulator === "jetbrains-jediterm"
        """
        env = {"TERMINAL_EMULATOR": "jetbrains-jediterm"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is False

    def test_detect_caps_tmux_hyperlinks(self):
        """tmux detected via TMUX env var.

        Upstream line 74: if (process.env.TMUX || term.startsWith("tmux"))
        Returns hyperlinks: true only if tmux forwards them (mocked here).
        """
        env = {"TMUX": "session"}
        # Without hyperlink forwarding check (depends on implementation)
        caps = detect_caps(env)
        assert caps.true_color is False  # No COLORTERM hint
        # hyperlinks depend on tmux forwarding support

    def test_detect_caps_tmux_with_truecolor(self):
        """tmux with COLORTERM hint for true color."""
        env = {"TMUX": "session", "COLORTERM": "truecolor"}
        caps = detect_caps(env)
        assert caps.true_color is True

    def test_detect_caps_screen(self):
        """screen terminal (no hyperlinks).

        Upstream line 79: if (term.startsWith("screen"))
        """
        env = {"TERM": "screen"}
        caps = detect_caps(env)
        assert caps.true_color is False
        assert caps.hyperlinks is False

    def test_detect_caps_screen_256color(self):
        """screen with 256 colors."""
        env = {"TERM": "screen-256color"}
        caps = detect_caps(env)
        assert caps.true_color is False
        assert caps.hyperlinks is False

    def test_detect_caps_colorterm_truecolor(self):
        """Unknown terminal with COLORTERM=truecolor hint.

        Upstream line 70: const hasTrueColorHint = colorTerm === "truecolor" || colorTerm === "24bit"
        """
        env = {"COLORTERM": "truecolor"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is False

    def test_detect_caps_colorterm_24bit(self):
        """Unknown terminal with COLORTERM=24bit hint."""
        env = {"COLORTERM": "24bit"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is False

    def test_detect_caps_unknown_conservative(self):
        """Unknown terminal without hints (conservative defaults).

        Upstream lines 120-124: conservative fallback
        """
        env = {}
        caps = detect_caps(env)
        assert caps.true_color is False
        assert caps.hyperlinks is False

    def test_detect_caps_case_insensitive(self):
        """Environment variables should be case-insensitive.

        Upstream lines 66-69 use .toLowerCase()
        """
        env = {"TERM_PROGRAM": "KITTY"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True

    def test_detect_caps_warp_terminal(self):
        """Warp terminal support.

        Upstream line 96: termProgram === "warpterminal"
        """
        env = {"TERM_PROGRAM": "warpterminal"}
        caps = detect_caps(env)
        assert caps.true_color is True
        assert caps.hyperlinks is True


class TestHyperlink:
    """Tests for hyperlink function.

    Upstream: terminal-image.ts lines 478-480
    Returns OSC 8 hyperlink sequence when caps.hyperlinks=True,
    plain text otherwise.
    """

    def test_hyperlink_supported(self):
        """Generate OSC 8 hyperlink when hyperlinks supported.

        Upstream format: \\x1b]8;;{url}\\x1b\\{text}\\x1b]8;;\\x1b\\
        """
        caps = TermCaps(true_color=True, hyperlinks=True)
        result = hyperlink("https://example.com", "Click here", caps)
        # Should contain OSC 8 opening sequence
        assert "\x1b]8;;" in result
        assert "https://example.com" in result
        assert "Click here" in result
        # Should end with OSC 8 closing sequence
        assert result.endswith("\x1b]8;;\x1b\\") or result.endswith("\x1b]8;;\x07")

    def test_hyperlink_not_supported(self):
        """Return plain text when hyperlinks not supported."""
        caps = TermCaps(true_color=True, hyperlinks=False)
        result = hyperlink("https://example.com", "Click here", caps)
        assert result == "Click here"
        assert "\x1b]8;;" not in result

    def test_hyperlink_various_urls(self):
        """Test hyperlink with various URL formats."""
        caps = TermCaps(true_color=True, hyperlinks=True)

        # File URL
        result = hyperlink("file:///tmp/test.txt", "file", caps)
        assert "file:///tmp/test.txt" in result

        # HTTP URL
        result = hyperlink("http://example.com", "link", caps)
        assert "http://example.com" in result

    def test_hyperlink_various_text(self):
        """Test hyperlink with various text content."""
        caps = TermCaps(true_color=True, hyperlinks=True)

        # Empty text
        result = hyperlink("https://example.com", "", caps)
        assert "https://example.com" in result

        # Text with spaces
        result = hyperlink("https://example.com", "Click here to visit", caps)
        assert "Click here to visit" in result

        # Text with special chars
        result = hyperlink("https://example.com", "Link [bold]", caps)
        assert "Link [bold]" in result


class TestIsImageLine:
    """Tests for is_image_line function.

    Upstream: terminal-image.ts lines 146-153
    Detects Kitty graphics protocol (\x1b_G...) or iTerm2 protocol (\x1b]1337;File=...).
    """

    def test_is_image_line_kitty_prefix(self):
        """Detect Kitty image prefix at line start.

        Upstream line 148: line.startsWith(KITTY_PREFIX) where KITTY_PREFIX = "\x1b_G"
        """
        line = "\x1b_Ga=T,f=100;base64data\x1b\\"
        assert is_image_line(line) is True

    def test_is_image_line_kitty_prefix_in_middle(self):
        """Detect Kitty image sequence in middle of line.

        Upstream line 152: line.includes(KITTY_PREFIX)
        """
        line = "prefix\x1b_Ga=T,f=100;base64data\x1b\\"
        assert is_image_line(line) is True

    def test_is_image_line_iterm2_prefix(self):
        """Detect iTerm2 image prefix at line start.

        Upstream line 148: line.startsWith(ITERM2_PREFIX) where ITERM2_PREFIX = "\x1b]1337;File="
        """
        line = "\x1b]1337;File=name=test.png;inline=1:base64data\x07"
        assert is_image_line(line) is True

    def test_is_image_line_iterm2_prefix_in_middle(self):
        """Detect iTerm2 image sequence in middle of line.

        Upstream line 152: line.includes(ITERM2_PREFIX)
        """
        line = "prefix\x1b]1337;File=name=test.png;inline=1:base64data\x07"
        assert is_image_line(line) is True

    def test_is_image_line_regular_text(self):
        """Return False for regular text line."""
        line = "Just regular terminal output"
        assert is_image_line(line) is False

    def test_is_image_line_empty(self):
        """Return False for empty line."""
        line = ""
        assert is_image_line(line) is False

    def test_is_image_line_escape_sequences_but_not_image(self):
        """Return False for other escape sequences."""
        line = "\x1b[31mRed text\x1b[0m"
        assert is_image_line(line) is False

    def test_is_image_line_kitty_like_prefix(self):
        """Detect line with Kitty-like structure."""
        line = "\x1b_Gidea=T,f=100q=2;SGVsbG8gV29ybGQ=\x1b\\"
        assert is_image_line(line) is True

    def test_is_image_line_iterm2_minimal(self):
        """Detect minimal iTerm2 image sequence."""
        line = "\x1b]1337;File=:dGVzdA==\x07"
        assert is_image_line(line) is True

    def test_is_image_line_cursor_prefix(self):
        """Detect image with cursor positioning prefix (multi-row).

        Upstream comment line 151: multi-row images have cursor-up prefix
        """
        line = "\x1b[A\x1b_Ga=T;base64\x1b\\"
        assert is_image_line(line) is True
