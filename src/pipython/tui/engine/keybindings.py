"""Keybinding tables — Python port of upstream pi's
``packages/tui/src/keybindings.ts`` (244 lines).

Ports the *default table* half of upstream keybindings.ts: a flat mapping
from a stable "binding name" (e.g. ``"tui.editor.cursorLeft"``) to one or
more upstream ``KeyId`` strings (e.g. ``"left"``, ``["left", "ctrl+b"]``),
plus a minimal lookup wrapper around it. Upstream's ``KeybindingsManager``
class (user-override merging, conflict detection, ``getResolvedBindings``)
is *not* ported here — this task's brief interface only calls for a plain
``KeyBindings(table)`` reader with ``.get(name)``; user-configurable
rebinding is out of scope for phase-3 (see task-5 brief "Produces").

Interface (binding, per task-5 brief):

- ``KeyBindings(table: dict[str, str | list[str]])`` — thin wrapper over a
  raw ``{binding_name: key_id_or_key_ids}`` table with ``.get(name)`` lookup.
- ``DEFAULT_EDITOR_BINDINGS: dict[str, str | list[str]]`` — copied verbatim
  from upstream's ``TUI_KEYBINDINGS`` constant (keybindings.ts:54-134),
  dropping the ``description``/``defaultKeys`` wrapper (this port has no
  user-override layer to justify keeping definitions separate from
  resolved defaults).

Declared deviation (spec §5): ``"tui.input.newLine"`` gains an *additional*
default key, ``"alt+enter"``, not present in upstream (which only binds
``["shift+enter", "ctrl+j"]`` at keybindings.ts:118). This is a deliberate
phase-3 spec ruling, not a translation error — verified against upstream
source before implementing (no upstream default table binds ``alt+enter``
to anything).

Consumes Task 4's ``key_id(event) -> str`` output: a resolved binding's key
list is meant to be compared against a pressed key's canonical ``key_id``
string by a caller (e.g. a future Editor/Input component). Per Task 4's
review heads-up, ``key_id`` can synthesize an out-of-taxonomy single-
character name for unrecognized printables (e.g. ``"Ä"``); such names are
simply absent from every binding's key list here, so :meth:`KeyBindings.matches`
returns ``False`` for them rather than raising — there is nothing to special-
case, an ordinary membership check already has this property.
"""

from __future__ import annotations

__all__ = ["KeyBindings", "DEFAULT_EDITOR_BINDINGS"]


# =============================================================================
# DEFAULT_EDITOR_BINDINGS (keybindings.ts:54-134 TUI_KEYBINDINGS, defaultKeys only)
# =============================================================================

DEFAULT_EDITOR_BINDINGS: dict[str, str | list[str]] = {
    "tui.editor.cursorUp": "up",
    "tui.editor.cursorDown": "down",
    "tui.editor.cursorLeft": ["left", "ctrl+b"],
    "tui.editor.cursorRight": ["right", "ctrl+f"],
    "tui.editor.cursorWordLeft": ["alt+left", "ctrl+left", "alt+b"],
    "tui.editor.cursorWordRight": ["alt+right", "ctrl+right", "alt+f"],
    "tui.editor.cursorLineStart": ["home", "ctrl+a"],
    "tui.editor.cursorLineEnd": ["end", "ctrl+e"],
    "tui.editor.jumpForward": "ctrl+]",
    "tui.editor.jumpBackward": "ctrl+alt+]",
    "tui.editor.pageUp": "pageUp",
    "tui.editor.pageDown": "pageDown",
    "tui.editor.deleteCharBackward": "backspace",
    "tui.editor.deleteCharForward": ["delete", "ctrl+d"],
    "tui.editor.deleteWordBackward": ["ctrl+w", "alt+backspace"],
    "tui.editor.deleteWordForward": ["alt+d", "alt+delete"],
    "tui.editor.deleteToLineStart": "ctrl+u",
    "tui.editor.deleteToLineEnd": "ctrl+k",
    "tui.editor.yank": "ctrl+y",
    "tui.editor.yankPop": "alt+y",
    "tui.editor.undo": "ctrl+-",
    # Deviation (spec §5): "alt+enter" added — not in upstream keybindings.ts:118,
    # which only lists ["shift+enter", "ctrl+j"].
    "tui.input.newLine": ["shift+enter", "ctrl+j", "alt+enter"],
    "tui.input.submit": "enter",
    "tui.input.tab": "tab",
    "tui.input.copy": "ctrl+c",
    "tui.select.up": "up",
    "tui.select.down": "down",
    "tui.select.pageUp": "pageUp",
    "tui.select.pageDown": "pageDown",
    "tui.select.confirm": "enter",
    "tui.select.cancel": ["escape", "ctrl+c"],
}


# =============================================================================
# KeyBindings
# =============================================================================


class KeyBindings:
    """Thin lookup wrapper over a ``{binding_name: key_id_or_key_ids}`` table."""

    def __init__(self, table: dict[str, str | list[str]]) -> None:
        self.table = table

    def get(self, name: str) -> str | list[str] | None:
        """Return the key or keys bound to ``name``, or ``None`` if unbound."""
        return self.table.get(name)

    def matches(self, key_id: str, name: str) -> bool:
        """Whether ``key_id`` (Task 4's canonical key-id string) is one of the
        keys bound to ``name``. Missing bindings and unrecognized ``key_id``
        values both simply return ``False`` — never raise."""
        keys = self.get(name)
        if keys is None:
            return False
        if isinstance(keys, str):
            return key_id == keys
        return key_id in keys
