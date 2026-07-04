"""Box component — Python port of upstream pi's
``packages/tui/src/components/box.ts`` (137 lines), narrowed and reshaped to
task-9 brief's simplified interface:
``Box(child: Component, *, padding: int = 0, border: bool = False)``.

Upstream's ``Box`` is a multi-``children``, background-filling container
(``addChild``/``removeChild``/``clear``, a ``bgFn`` callback, a hand-rolled
render cache keyed on child output + bg sample) with no border concept at
all. Task-9's ``Box`` is a single-``child`` wrapper adding two features
neither of which upstream's ``box.ts`` has: a plain ``border`` box-drawing
frame (``┌─┐``/``│ │``/``└─┘`` — box.ts contains **no** border-drawing code
whatsoever; the only upstream precedent for those exact glyphs is
``markdown.ts``'s table renderer, lines 803-851, a wholly different
component) and a single scalar ``padding`` applied to both axes (collapsing
upstream's separate ``paddingX``/``paddingY``). See the task-9 report's RED
corrections section for why the RED test file's docstring citation ("Border
chars derived from box.ts") is wrong.

Deviations from upstream box.ts:

1. Single ``child``, not a ``children: Component[]`` list — the task-9
   brief's Produces list takes one child; composing multiple children is
   Task 7's ``Container``'s job (nest a ``Container`` as the one child if
   multiple are needed).
2. ``border`` is a new feature with no upstream ``box.ts`` equivalent at all
   (see module docstring above) — a plain single-line box-drawing frame,
   reserving one column/row on each side.
3. One ``padding`` int for both axes, not separate ``paddingX``/``paddingY``.
4. No ``bgFn`` background-callback support, and correspondingly no
   fill-to-width padding when neither ``padding`` nor ``border`` is
   requested — a bare pass-through of the child's own lines in that case
   (matching the RED tests' exact-output assertion for the no-padding/no-
   border case, ``Box(child, padding=0, border=False).render(10) ==
   ["content"]``, which upstream's own unconditional per-line fill
   [box.ts:127-136 ``applyBg``] would break). Padding/border *do* still pad
   each interior line out to the box's own interior width — that padding is
   this port's own structural requirement (every row inside a border must
   be the same width for the frame to line up), not a ported feature.
5. No render-output cache (box.ts:4-9, 20-21, 56-65 ``RenderCache``/
   ``matchCache``) — a pure perf optimization orthogonal to render
   *semantics*, not in the task-9 brief's Produces list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..engine.utils import visible_width

if TYPE_CHECKING:
    from ..engine.tui import Component

__all__ = ["Box"]

_TOP_LEFT = "┌"
_TOP_RIGHT = "┐"
_BOTTOM_LEFT = "└"
_BOTTOM_RIGHT = "┘"
_HORIZONTAL = "─"
_VERTICAL = "│"


class Box:
    """tui.ts ``Component``-compatible: pads and/or frames a single child."""

    def __init__(self, child: Component, *, padding: int = 0, border: bool = False) -> None:
        self.child = child
        self.padding = padding
        self.border = border

    def invalidate(self) -> None:
        """box.ts:67-72 ``invalidate()``: forward to the child (this port has
        no render cache of its own to clear, see module docstring
        deviation 5)."""
        self.child.invalidate()

    def render(self, width: int) -> list[str]:
        border_cols = 2 if self.border else 0
        interior_width = max(1, width - border_cols)
        content_width = max(1, interior_width - 2 * self.padding)

        child_lines = self.child.render(content_width)

        # Bare pass-through: no padding/border requested, so there is no
        # structural reason to touch the child's own output at all (module
        # docstring deviation 4).
        if not self.border and self.padding == 0:
            return child_lines

        h_pad = " " * self.padding
        content_rows = []
        for line in child_lines:
            fill = " " * max(0, content_width - visible_width(line))
            content_rows.append(h_pad + line + fill + h_pad)

        blank_row = " " * interior_width
        rows = [blank_row] * self.padding + content_rows + [blank_row] * self.padding

        if not self.border:
            return rows

        top = _TOP_LEFT + _HORIZONTAL * interior_width + _TOP_RIGHT
        bottom = _BOTTOM_LEFT + _HORIZONTAL * interior_width + _BOTTOM_RIGHT
        return [top, *(_VERTICAL + row + _VERTICAL for row in rows), bottom]
