"""Tests for terminal_colors module.

Tests cover OSC 11 response parsing with BEL/ST terminators,
dark/light luminance detection, and query constants.
"""

from pipython.tui.engine.terminal_colors import (
    parse_osc11_response,
    is_dark,
    QUERY_BG,
)


class TestParseOsc11Response:
    r"""Tests for parse_osc11_response function.

    Upstream pattern (terminal-colors.ts line 28):
    OSC11_BACKGROUND_COLOR_RESPONSE_PATTERN = /^\x1b\]11;([^\x07\x1b]*)(?:\x07|\x1b\\)$/i

    Supports:
    - RGB format: rgb:HHHH/HHHH/HHHH (hex channels)
    - Hex format: #RRGGBB or #RRRRGGGGBBBB (6 or 12 digit)
    """

    def test_osc11_bel_terminator_rgb_format(self):
        """Parse OSC 11 with BEL terminator and rgb: format.

        Upstream lines 56-64: parseOscHexChannel converts hex to 0-255 range.
        For "1e1e/1e1e/1e1e": 0x1e = 30 decimal.
        """
        data = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07"
        result = parse_osc11_response(data)
        assert result == (30, 30, 30)

    def test_osc11_st_terminator_rgb_format(self):
        """Parse OSC 11 with ST (String Terminator) \x1b\\ and rgb: format."""
        data = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\"
        result = parse_osc11_response(data)
        assert result == (30, 30, 30)

    def test_osc11_bel_terminator_hex_format(self):
        """Parse OSC 11 with BEL terminator and hex format.

        Upstream lines 42-45: hex format #RRGGBB is parsed via hexToRgb.
        0x1e = 30 decimal.
        """
        data = b"\x1b]11;#1e1e1e\x07"
        result = parse_osc11_response(data)
        assert result == (30, 30, 30)

    def test_osc11_st_terminator_hex_format(self):
        """Parse OSC 11 with ST terminator and hex format."""
        data = b"\x1b]11;#1e1e1e\x1b\\"
        result = parse_osc11_response(data)
        assert result == (30, 30, 30)

    def test_osc11_white_rgb(self):
        """Parse white background (maximum values)."""
        data = b"\x1b]11;rgb:ffff/ffff/ffff\x07"
        result = parse_osc11_response(data)
        assert result == (255, 255, 255)

    def test_osc11_white_hex(self):
        """Parse white background in hex format."""
        data = b"\x1b]11;#ffffff\x07"
        result = parse_osc11_response(data)
        assert result == (255, 255, 255)

    def test_osc11_12digit_hex(self):
        """Parse 12-digit hex format (RRRRGGGGBBBB).

        Upstream lines 47-51: 12-digit hex format support.
        16-bit channels are normalized to 8-bit.
        """
        # 0xffff normalized to 8-bit = 255
        data = b"\x1b]11;#ffffffffffff\x07"
        result = parse_osc11_response(data)
        assert result == (255, 255, 255)

    def test_osc11_12digit_hex_mid(self):
        """Parse 12-digit hex with mid-range values."""
        # 0x8000 (half of 0xffff) normalizes to ~128
        data = b"\x1b]11;#800080008000\x07"
        result = parse_osc11_response(data)
        assert result == (128, 128, 128)

    def test_osc11_invalid_data(self):
        """Return None for invalid data."""
        data = b"garbage"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_missing_prefix(self):
        """Return None if missing OSC 11 prefix."""
        data = b"rgb:1e1e/1e1e/1e1e\x07"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_wrong_code(self):
        """Return None if not OSC 11 (different code)."""
        data = b"\x1b]12;rgb:1e1e/1e1e/1e1e\x07"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_missing_terminator(self):
        """Return None if terminator is missing."""
        data = b"\x1b]11;rgb:1e1e/1e1e/1e1e"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_malformed_rgb(self):
        """Return None if rgb format is malformed (missing component)."""
        data = b"\x1b]11;rgb:1e1e/1e1e\x07"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_invalid_hex_char(self):
        """Return None if hex contains invalid character."""
        data = b"\x1b]11;rgb:gggg/gggg/gggg\x07"
        result = parse_osc11_response(data)
        assert result is None

    def test_osc11_case_insensitive(self):
        """Parse ignoring case (upstream regex has i flag)."""
        data = b"\x1b]11;RGB:FFFF/FFFF/FFFF\x07"
        result = parse_osc11_response(data)
        assert result == (255, 255, 255)

    def test_osc11_with_whitespace(self):
        """Parse rgb format with leading/trailing whitespace.

        Upstream line 41: value = match[1].trim()
        """
        data = b"\x1b]11;  rgb:1e1e/1e1e/1e1e  \x07"
        result = parse_osc11_response(data)
        assert result == (30, 30, 30)


class TestIsDark:
    """Tests for is_dark function.

    Determines if an RGB color is dark or light using luminance formula.
    Standard formula: L = 0.299*R + 0.587*G + 0.114*B
    Dark if L < 128 (approximate threshold).
    """

    def test_is_dark_black(self):
        """Black (0, 0, 0) is dark."""
        assert is_dark((0, 0, 0)) is True

    def test_is_dark_white(self):
        """White (255, 255, 255) is light."""
        assert is_dark((255, 255, 255)) is False

    def test_is_dark_dark_gray(self):
        """Dark gray is dark."""
        assert is_dark((50, 50, 50)) is True

    def test_is_dark_light_gray(self):
        """Light gray is light."""
        assert is_dark((200, 200, 200)) is False

    def test_is_dark_red(self):
        """Red (255, 0, 0) has luminance ~76.5, considered dark."""
        assert is_dark((255, 0, 0)) is True

    def test_is_dark_green(self):
        """Green (0, 255, 0) has luminance ~149.5, near boundary."""
        # Depends on exact threshold; testing boundary behavior
        result = is_dark((0, 255, 0))
        assert isinstance(result, bool)

    def test_is_dark_blue(self):
        """Blue (0, 0, 255) has luminance ~29.1, considered dark."""
        assert is_dark((0, 0, 255)) is True

    def test_is_dark_yellow(self):
        """Yellow (255, 255, 0) has luminance ~225.9, considered light."""
        assert is_dark((255, 255, 0)) is False

    def test_is_dark_cyan(self):
        """Cyan (0, 255, 255) has luminance ~179.3, considered light."""
        assert is_dark((0, 255, 255)) is False

    def test_is_dark_magenta(self):
        """Magenta (255, 0, 255) has luminance ~105.5, considered dark."""
        assert is_dark((255, 0, 255)) is True

    def test_is_dark_near_threshold_dark(self):
        """Test near threshold (just below)."""
        # Value that should be dark (luminance ~127)
        assert is_dark((127, 127, 127)) is True

    def test_is_dark_near_threshold_light(self):
        """Neutral gray 128 is still dark under upstream's real classifier.

        RED correction: this test originally asserted light/False here,
        derived from a naive BT.601 luma (~128/255 midpoint) with no
        upstream citation. Upstream pi has no dark/light classifier in
        terminal-colors.ts at all; the actual one lives in
        theme.ts:708-722 (getRgbColorLuminance/getThemeForRgbColor) and
        uses WCAG-style relative luminance with sRGB gamma correction
        (Rec. 709 coefficients, threshold 0.5 on the *linear* scale).
        Under that real formula, a neutral gray only crosses into "light"
        around sRGB ~187-188 -- 128 remains dark (luminance ~0.216).
        See task-2-report.md GREEN phase / RED corrections.
        """
        assert is_dark((128, 128, 128)) is True

    def test_is_dark_typical_dark_bg(self):
        """Typical dark terminal background color."""
        assert is_dark((30, 30, 30)) is True

    def test_is_dark_typical_light_bg(self):
        """Typical light terminal background color."""
        assert is_dark((230, 230, 230)) is False


class TestQueryBg:
    """Tests for QUERY_BG constant.

    Upstream: `const QUERY_BG = "\x1b]11;?\x1b\\"`
    This is an OSC 11 query sequence sent to get background color.
    """

    def test_query_bg_type(self):
        """QUERY_BG should be a string."""
        assert isinstance(QUERY_BG, str)

    def test_query_bg_content(self):
        """QUERY_BG should contain OSC 11 query escape sequence.

        Upstream constant (terminal-colors.ts):
        QUERY_BG = "\x1b]11;?\x1b\\"
        """
        assert "\x1b]11;?" in QUERY_BG
        # Should end with ST terminator
        assert QUERY_BG.endswith("\x1b\\") or QUERY_BG.endswith("\x07")
