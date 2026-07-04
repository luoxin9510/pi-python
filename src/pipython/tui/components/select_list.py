"""SelectList component — Python port of upstream pi's
``packages/tui/src/components/select-list.ts`` (229 lines), narrowed to
task-10 brief's simplified interface: ``SelectItem(value, label,
description=None)`` and ``SelectList(items, max_visible)``. No
``SelectListTheme``/``SelectListLayoutOptions`` constructor parameters —
per the brief's port convention ("theme 参数简化为固定 pi 默认样式，样式常量
集中模块顶"), the theme callbacks are fixed module-level functions instead of
an injectable object.

Deviations from upstream select-list.ts:

1. **No ``SelectListTheme`` parameter.** ``_selected_text``/``_description``/
   ``_no_match``/``_scroll_info`` below are the fixed pi-default styling,
   module-level functions instead of an injected object, per the brief. The
   actual colors are pi's real default (dark) theme, not invented: upstream
   ``getSelectListTheme`` (theme.ts:1259-1267) wires ``selectedPrefix``/
   ``selectedText`` to ``theme.fg("accent", text)`` and ``description``/
   ``scrollInfo``/``noMatch`` to ``theme.fg("muted", text)``. ``theme.fg``
   (theme.ts:351-354) emits the color escape then a *foreground-only* reset
   ``\x1b[39m`` (not the full ``\x1b[0m``). In truecolor mode ``fgAnsi``
   (theme.ts:260-266) renders a hex color as ``\x1b[38;2;R;G;Bm``. The
   default dark theme (theme/dark.json) maps ``colors.accent`` to
   ``vars.accent = "#8abeb7"`` (dark.json:14,23) and ``colors.muted`` to
   ``vars.gray = "#808080"`` (dark.json:11,30) — see the constants below.
2. **No ``SelectListLayoutOptions`` parameter** (``minPrimaryColumnWidth``/
   ``maxPrimaryColumnWidth``/``truncatePrimary``, select-list.ts:34-38) — the
   brief's constructor takes only ``(items, max_visible)``. Upstream's own
   default layout is ``{}``, which makes ``getPrimaryColumnBounds`` resolve
   both ``min`` and ``max`` to ``DEFAULT_PRIMARY_COLUMN_WIDTH`` (32); with
   ``min == max``, ``clamp(widestPrimary, min, max)`` (select-list.ts:184)
   algebraically always returns that same constant regardless of
   ``widestPrimary`` (``max(min, min(x, max))`` with ``min == max`` is a
   constant function of ``x``). So the widest-item scan
   (``getPrimaryColumnWidth``, select-list.ts:178-185) is dead work in the
   no-layout-override case this port always is; it's dropped in favor of the
   plain constant ``_PRIMARY_COLUMN_WIDTH``. Likewise the custom
   ``truncatePrimary`` callback (select-list.ts:199-212) never exists here,
   so ``truncatePrimary``'s defensive *second* ``truncateToWidth`` call
   (guarding against a custom callback that ignores ``maxWidth``,
   select-list.ts:211) collapses to the single call that already produced a
   width-respecting result — ``_truncate_primary`` below does it once.
3. **No ``handleInput``/keybinding integration** (``getKeybindings()``/
   ``"tui.select.up"``/``"tui.select.down"``/``"tui.select.confirm"``/
   ``"tui.select.cancel"``, select-list.ts:112-137) and **no
   ``onSelect``/``onCancel``/``onSelectionChange`` callback hooks**
   (select-list.ts:48-50, 117, 122, 218-223). The brief's Produces list
   exposes ``move_up()``/``move_down()`` as the direct, programmatic
   movement API — downstream (Task 13's editor, for autocomplete) calls
   these directly instead of routing raw key data through this component's
   own key-matching layer.
4. **No ``setFilter``/``setSelectedIndex`` methods** (select-list.ts:60-68) —
   the brief's Produces list calls only for ``set_items(items)``, whose
   reset-to-index-0 behavior is derived from ``setFilter``'s own reset
   semantics (select-list.ts:63). There is no filter-string concept in this
   port at all (upstream's ``items``/``filteredItems`` split collapses to a
   single ``items`` list).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..engine.utils import truncate_to_width, visible_width

__all__ = ["SelectItem", "SelectList"]

# --------------------------------------------------------------------------
# Fixed layout constants — select-list.ts:5-7.
# --------------------------------------------------------------------------

_PRIMARY_COLUMN_WIDTH = 32  # DEFAULT_PRIMARY_COLUMN_WIDTH, see deviation 2.
_PRIMARY_COLUMN_GAP = 2
_MIN_DESCRIPTION_WIDTH = 10

_NO_MATCH_TEXT = "  No matching commands"  # select-list.ts:79 (literal, not themed)

_NORMALIZE_NEWLINES_RE = re.compile(r"[\r\n]+")


def _normalize_to_single_line(text: str) -> str:
    """select-list.ts:9 ``normalizeToSingleLine``: collapse CR/LF runs to a
    single space and trim."""
    return _NORMALIZE_NEWLINES_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------
# Fixed pi-default theme — see module docstring deviation 1.
#
# Values are pi's real default (dark) theme, not invented constants:
#   - getSelectListTheme (theme.ts:1259-1267): selectedPrefix/selectedText use
#     theme.fg("accent", text); description/scrollInfo/noMatch use
#     theme.fg("muted", text).
#   - theme.fg (theme.ts:351-354): f"{ansi}{text}\x1b[39m" — foreground-only
#     reset, not the full "\x1b[0m".
#   - fgAnsi truecolor branch (theme.ts:260-266): hex -> "\x1b[38;2;R;G;Bm".
#   - dark.json vars.accent = "#8abeb7" (line 14), wired to colors.accent
#     (line 23) -> rgb(138, 190, 183).
#   - dark.json vars.gray = "#808080" (line 11), wired to colors.muted
#     (line 30) -> rgb(128, 128, 128).
# --------------------------------------------------------------------------

_ACCENT_FG = "\x1b[38;2;138;190;183m"  # dark.json accent "#8abeb7"
_MUTED_FG = "\x1b[38;2;128;128;128m"  # dark.json muted/gray "#808080"
_FG_RESET = "\x1b[39m"  # theme.ts:354 — foreground-only reset


def _selected_text(text: str) -> str:
    """``theme.fg("accent", text)`` for the selected row (theme.ts:1261)."""
    return f"{_ACCENT_FG}{text}{_FG_RESET}"


def _description(text: str) -> str:
    """``theme.fg("muted", text)`` for description text (theme.ts:1263)."""
    return f"{_MUTED_FG}{text}{_FG_RESET}"


def _no_match(text: str) -> str:
    """``theme.fg("muted", text)`` for the empty-list message (theme.ts:1265)."""
    return f"{_MUTED_FG}{text}{_FG_RESET}"


def _scroll_info(text: str) -> str:
    """``theme.fg("muted", text)`` for the scroll indicator (theme.ts:1264)."""
    return f"{_MUTED_FG}{text}{_FG_RESET}"


@dataclass
class SelectItem:
    """select-list.ts:12-16 ``SelectItem`` interface, ported as a dataclass."""

    value: str
    label: str
    description: str | None = None


def _display_value(item: SelectItem) -> str:
    """select-list.ts:214-216 ``getDisplayValue``: falsy-``label`` fallback
    to ``value``."""
    return item.label or item.value


def _truncate_primary(item: SelectItem, max_width: int) -> str:
    """select-list.ts:199-212 ``truncatePrimary``, minus the customizable
    ``layout.truncatePrimary`` callback (module docstring deviation 2)."""
    return truncate_to_width(_display_value(item), max_width, "")


class SelectList:
    """tui.ts ``Component``-compatible: a scrollable, single-selection list.

    Wrap-around ``move_up()``/``move_down()`` (select-list.ts:115-122),
    centered scroll window (select-list.ts:86-90), highlighted current row
    (select-list.ts:139-176), and width-truncated columns (Task 1's
    ``truncate_to_width``/``visible_width``)."""

    def __init__(self, items: list[SelectItem], max_visible: int) -> None:
        self.items: list[SelectItem] = list(items)
        self.max_visible = max_visible
        self.selected_index = 0

    def invalidate(self) -> None:
        """select-list.ts:70-72: no cached state to invalidate."""

    @property
    def selected(self) -> SelectItem | None:
        """select-list.ts:225-228 ``getSelectedItem``: the item at
        ``selected_index``, or ``None`` if out of range (e.g. empty list)."""
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def move_up(self) -> None:
        """select-list.ts:115-118: wrap to the last item from the top."""
        if not self.items:
            return
        self.selected_index = (
            len(self.items) - 1 if self.selected_index == 0 else self.selected_index - 1
        )

    def move_down(self) -> None:
        """select-list.ts:120-123: wrap to the first item from the bottom."""
        if not self.items:
            return
        self.selected_index = (
            0 if self.selected_index == len(self.items) - 1 else self.selected_index + 1
        )

    def set_items(self, items: list[SelectItem]) -> None:
        """Replace the item list and reset selection to the top, mirroring
        ``setFilter``'s own reset-to-0 behavior (select-list.ts:60-64; see
        module docstring deviation 4)."""
        self.items = list(items)
        self.selected_index = 0

    def render(self, width: int) -> list[str]:
        """select-list.ts:74-110 ``render``."""
        lines: list[str] = []

        if not self.items:
            lines.append(_no_match(_NO_MATCH_TEXT))
            return lines

        start_index = max(
            0,
            min(self.selected_index - self.max_visible // 2, len(self.items) - self.max_visible),
        )
        end_index = min(start_index + self.max_visible, len(self.items))

        for i in range(start_index, end_index):
            item = self.items[i]
            is_selected = i == self.selected_index
            description_single_line = (
                _normalize_to_single_line(item.description) if item.description else None
            )
            lines.append(self._render_item(item, is_selected, width, description_single_line))

        if start_index > 0 or end_index < len(self.items):
            scroll_text = f"  ({self.selected_index + 1}/{len(self.items)})"
            lines.append(_scroll_info(truncate_to_width(scroll_text, width - 2, "")))

        return lines

    def _render_item(
        self,
        item: SelectItem,
        is_selected: bool,
        width: int,
        description_single_line: str | None,
    ) -> str:
        """select-list.ts:139-176 ``renderItem``."""
        prefix = "→ " if is_selected else "  "
        prefix_width = visible_width(prefix)

        if description_single_line and width > 40:
            effective_primary_column_width = max(
                1, min(_PRIMARY_COLUMN_WIDTH, width - prefix_width - 4)
            )
            max_primary_width = max(1, effective_primary_column_width - _PRIMARY_COLUMN_GAP)
            truncated_value = _truncate_primary(item, max_primary_width)
            truncated_value_width = visible_width(truncated_value)
            spacing = " " * max(1, effective_primary_column_width - truncated_value_width)
            description_start = prefix_width + truncated_value_width + len(spacing)
            remaining_width = width - description_start - 2  # -2 for safety

            if remaining_width > _MIN_DESCRIPTION_WIDTH:
                truncated_desc = truncate_to_width(description_single_line, remaining_width, "")
                if is_selected:
                    return _selected_text(f"{prefix}{truncated_value}{spacing}{truncated_desc}")
                return prefix + truncated_value + _description(spacing + truncated_desc)

        max_width = width - prefix_width - 2
        truncated_value = _truncate_primary(item, max_width)
        if is_selected:
            return _selected_text(f"{prefix}{truncated_value}")
        return prefix + truncated_value
