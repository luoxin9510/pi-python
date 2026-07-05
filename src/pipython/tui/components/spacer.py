"""Spacer component — Python port of upstream pi's
``packages/tui/src/components/spacer.ts`` (28 lines, full port; the smallest
of the five task-9 components — no deviations, no simplification needed).

``Spacer(lines: int = 1)``: renders ``lines`` empty strings, ignoring the
render ``width`` entirely (spacer.ts:21 ``render(_width: number)``, the
leading underscore itself upstream's own "unused parameter" convention).
"""

from __future__ import annotations

__all__ = ["Spacer"]


class Spacer:
    """tui.ts ``Component``-compatible: pure vertical whitespace."""

    def __init__(self, lines: int = 1) -> None:
        self.lines = lines

    def set_lines(self, lines: int) -> None:
        """Upstream ``setLines()`` (spacer.ts:13-15)."""
        self.lines = lines

    def invalidate(self) -> None:
        """spacer.ts:17-19: no cached state to invalidate."""

    def render(self, width: int) -> list[str]:
        """spacer.ts:21-26: ``lines`` empty strings, width unused."""
        return [""] * self.lines
