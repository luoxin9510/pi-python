"""TruncatedText component — Python port of upstream pi's
``packages/tui/src/components/truncated-text.ts`` (65 lines), narrowed to
task-9 brief's simplified interface: ``TruncatedText(content: str)`` — no
``paddingX``/``paddingY`` constructor params (upstream's own defaults are
already 0 for both, so this port's constructor shape drops params whose
default value was the *only* value the task-9 brief's Produces list ever
calls for). Single-line, first-line-only, ellipsis-truncated text. Does not
reimplement truncation — delegated entirely to Task 1's ``truncate_to_width``
(utils.ts's own ``truncateToWidth``, ported verbatim in ``engine/utils.py``).

Deviations from upstream truncated-text.ts:

1. No ``paddingX``/``paddingY`` params, and no fill-to-width padding
   (truncated-text.ts:26, 34, 47-54's ``emptyLine``/margin/trailing-space
   bookkeeping) — see above; this port's render is a single bare truncated
   line with no surrounding whitespace, matching the RED tests' exact-output
   assertions (e.g. ``TruncatedText("line1\\nline2\\nline3").render(20)``
   yields exactly ``["line1"]``, not a width-padded string).
"""

from __future__ import annotations

from ..engine.utils import truncate_to_width

__all__ = ["TruncatedText"]


class TruncatedText:
    """tui.ts ``Component``-compatible: single-line, ellipsis-truncated text."""

    def __init__(self, content: str) -> None:
        self.content = content

    def invalidate(self) -> None:
        """truncated-text.ts:18-20: no cached state to invalidate."""

    def render(self, width: int) -> list[str]:
        """truncated-text.ts:22-63's core: first line only (stop at the
        first ``\\n``, truncated-text.ts:36-41), truncated with an ellipsis
        via ``truncate_to_width`` (truncated-text.ts:44) — no padding, see
        module docstring deviation 1."""
        first_line = self.content.split("\n", 1)[0]
        return [truncate_to_width(first_line, max(1, width))]
