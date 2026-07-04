"""Terminal background-color parsing and dark/light classification.

Ports upstream pi's ``packages/tui/src/terminal-colors.ts`` (73 lines):
``parseOsc11BackgroundColor`` / ``hexToRgb`` / ``parseOscHexChannel`` become
``parse_osc11_response`` here.

That upstream file has no dark/light classifier and no ``QUERY_BG`` constant
of its own — those two pieces of this module's interface (mandated by the
task-2 brief) have no literal upstream counterpart in ``terminal-colors.ts``.
They are ported instead from the closest genuine upstream precedent in the
same monorepo:

- ``is_dark``: ``getRgbColorLuminance`` / ``getThemeForRgbColor`` in
  ``packages/coding-agent/src/modes/interactive/theme/theme.ts:708-722``
  (WCAG-style relative luminance with sRGB gamma correction, Rec. 709
  coefficients, threshold 0.5) — the actual dark/light decision upstream pi
  uses elsewhere for terminal-background classification.
- ``QUERY_BG``: the literal OSC 11 query string upstream sends at its one
  call site, ``packages/tui/src/tui.ts:1684`` (``"\\x1b]11;?\\x07"``, BEL
  terminator). This port uses the brief-mandated ST-terminated literal
  ``"\\x1b]11;?\\x1b\\\\"`` instead — both terminators are accepted by
  ``parse_osc11_response``'s response pattern, so this is an observable but
  behaviourally inert deviation. See the task-2 GREEN-phase report for
  details on both.
"""

import re

__all__ = ["parse_osc11_response", "is_dark", "QUERY_BG"]

# --------------------------------------------------------------------------
# parse_osc11_response — ported verbatim from terminal-colors.ts:9-65
# --------------------------------------------------------------------------

# terminal-colors.ts:28 OSC11_BACKGROUND_COLOR_RESPONSE_PATTERN.
_OSC11_RESPONSE_RE = re.compile(rb"^\x1b\]11;([^\x07\x1b]*)(?:\x07|\x1b\\)$", re.IGNORECASE)

_HEX6_RE = re.compile(r"^[0-9a-f]{6}$", re.IGNORECASE)
_HEX12_RE = re.compile(r"^[0-9a-f]{12}$", re.IGNORECASE)
_HEX_CHANNEL_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)
_RGBA_PREFIX_RE = re.compile(r"^rgba?:", re.IGNORECASE)


def _hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
    """terminal-colors.ts:9-15 hexToRgb."""
    normalized = hex_value[1:] if hex_value.startswith("#") else hex_value
    r = int(normalized[0:2], 16)
    g = int(normalized[2:4], 16)
    b = int(normalized[4:6], 16)
    return (r, g, b)


def _parse_osc_hex_channel(channel: str) -> int | None:
    """terminal-colors.ts:17-26 parseOscHexChannel."""
    if not _HEX_CHANNEL_RE.match(channel):
        return None
    max_value = 16 ** len(channel) - 1
    if max_value <= 0:
        return None
    return round((int(channel, 16) / max_value) * 255)


def parse_osc11_response(data: bytes) -> tuple[int, int, int] | None:
    """Parse an OSC 11 background-color reply into an ``(r, g, b)`` tuple.

    Accepts BEL (``\\x07``) or ST (``\\x1b\\\\``) terminators and both the
    ``rgb:HHHH/HHHH/HHHH`` and ``#RRGGBB``/``#RRRRGGGGBBBB`` payload forms
    (terminal-colors.ts:35-65 parseOsc11BackgroundColor). Returns ``None``
    for anything that doesn't match.
    """
    match = _OSC11_RESPONSE_RE.match(data)
    if not match:
        return None

    value = match.group(1).decode("latin-1").strip()

    if value.startswith("#"):
        hex_part = value[1:]
        if _HEX6_RE.match(hex_part):
            return _hex_to_rgb(value)
        if _HEX12_RE.match(hex_part):
            r = _parse_osc_hex_channel(hex_part[0:4])
            g = _parse_osc_hex_channel(hex_part[4:8])
            b = _parse_osc_hex_channel(hex_part[8:12])
            if r is None or g is None or b is None:
                return None
            return (r, g, b)
        return None

    rgb_value = _RGBA_PREFIX_RE.sub("", value)
    parts = rgb_value.split("/")
    red = parts[0] if len(parts) > 0 else None
    green = parts[1] if len(parts) > 1 else None
    blue = parts[2] if len(parts) > 2 else None
    if red is None or green is None or blue is None:
        return None

    r = _parse_osc_hex_channel(red)
    g = _parse_osc_hex_channel(green)
    b = _parse_osc_hex_channel(blue)
    if r is None or g is None or b is None:
        return None
    return (r, g, b)


# --------------------------------------------------------------------------
# is_dark — ported from theme.ts:708-722 (see module docstring)
# --------------------------------------------------------------------------


def _to_linear(channel: int) -> float:
    """theme.ts:709-712 toLinear (sRGB gamma correction)."""
    value = channel / 255
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def is_dark(rgb: tuple[int, int, int]) -> bool:
    """Classify an ``(r, g, b)`` color as dark (``True``) or light (``False``).

    Ported from theme.ts's ``getRgbColorLuminance``/``getThemeForRgbColor``:
    WCAG-style relative luminance (Rec. 709 coefficients over gamma-corrected
    channels), dark when luminance < 0.5. Note this threshold sits much
    higher in raw sRGB terms than a naive midpoint: a neutral gray only
    crosses into "light" around sRGB ~187-188, not ~128.
    """
    r, g, b = rgb
    luminance = 0.2126 * _to_linear(r) + 0.7152 * _to_linear(g) + 0.0722 * _to_linear(b)
    return luminance < 0.5


# --------------------------------------------------------------------------
# QUERY_BG — see module docstring for the ST-vs-BEL deviation note.
# --------------------------------------------------------------------------

QUERY_BG = "\x1b]11;?\x1b\\"
