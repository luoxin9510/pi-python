"""Box component — Python port of upstream pi's
``packages/tui/src/components/box.ts`` (137 lines), narrowed and reshaped to
the plan's Task 9 interface: ``Box(child: Component, *, padding: int = 0)``.

Upstream's ``Box`` is a multi-``children``, background-filling container
(``addChild``/``removeChild``/``clear``, a ``bgFn`` callback, a hand-rolled
render cache keyed on child output + bg sample). Task-9's ``Box`` is a
single-``child`` wrapper that keeps only the one feature this port actually
needs: a single scalar ``padding`` applied to both axes (collapsing
upstream's separate ``paddingX``/``paddingY``).

**No ``border`` parameter.** An earlier revision of this port invented a
``border: bool`` param drawing a ``┌─┐``/``│ │``/``└─┘`` frame — upstream
``box.ts`` contains **no** border-drawing code whatsoever (the only
precedent for those exact glyphs anywhere in the reference tree is
``markdown.ts``'s table renderer, lines 803-851, a wholly different
component), and nothing in this plan's task graph ever constructed
``Box(..., border=True)``. Per the maintainer's ruling (plan Task 9
Produces, updated), that invented parameter has been removed along with its
glyph-drawing code and its tests. Bordered UI belongs to phase-4's
dynamic-border components, not this static ``Box``.

Deviations from upstream box.ts:

1. Single ``child``, not a ``children: Component[]`` list — the task-9
   brief's Produces list takes one child; composing multiple children is
   Task 7's ``Container``'s job (nest a ``Container`` as the one child if
   multiple are needed).
2. One ``padding`` int for both axes, not separate ``paddingX``/``paddingY``.
3. No ``bgFn`` background-callback support, and correspondingly no
   fill-to-width padding when ``padding`` is 0 — a bare pass-through of the
   child's own lines in that case (matching the RED tests' exact-output
   assertion for the no-padding case, ``Box(child, padding=0).render(10) ==
   ["content"]``, which upstream's own unconditional per-line fill
   [box.ts:127-136 ``applyBg``] would break). Padding *does* still pad each
   interior line out to the box's own content width — that padding is this
   port's own structural requirement (every padded row must be the same
   width), not a ported feature.
4. No render-output cache (box.ts:4-9, 20-21, 56-65 ``RenderCache``/
   ``matchCache``) — a pure perf optimization orthogonal to render
   *semantics*, not in the task-9 brief's Produces list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..engine.utils import visible_width

if TYPE_CHECKING:
    from ..engine.tui import Component

__all__ = ["Box"]


class Box:
    """tui.ts ``Component``-compatible: pads a single child."""

    def __init__(self, child: Component, *, padding: int = 0) -> None:
        self.child = child
        self.padding = padding

    def invalidate(self) -> None:
        """box.ts:67-72 ``invalidate()``: forward to the child (this port has
        no render cache of its own to clear, see module docstring
        deviation 4)."""
        self.child.invalidate()

    def render(self, width: int) -> list[str]:
        width = max(1, width)
        content_width = max(1, width - 2 * self.padding)

        child_lines = self.child.render(content_width)

        # Bare pass-through: no padding requested, so there is no
        # structural reason to touch the child's own output at all (module
        # docstring deviation 3).
        if self.padding == 0:
            return child_lines

        h_pad = " " * self.padding
        content_rows = []
        for line in child_lines:
            fill = " " * max(0, content_width - visible_width(line))
            content_rows.append(h_pad + line + fill + h_pad)

        blank_row = " " * width
        return [blank_row] * self.padding + content_rows + [blank_row] * self.padding
