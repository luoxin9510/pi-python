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

Declared deviation (task-19 acceptance bug 2 fix): ``"app.tools.expand":
"ctrl+o"`` is added here even though it is not a ``tui.*`` editor action.
Upstream keeps ``TUI_KEYBINDINGS`` (this file's actual source, editor-only)
and the coding-agent-level ``KEYBINDINGS`` (``TUI_KEYBINDINGS`` merged with
an ``app.*`` namespace — ``coding-agent/src/core/keybindings.ts:64-85``,
including ``"app.tools.expand": { defaultKeys: "ctrl+o", ... }``) as two
separate tables feeding one shared ``KeybindingsManager``. This port has no
app-level bindings table yet and no user-override merge layer to justify
building one for a single entry, so the one ``app.*`` action this port
currently dispatches through the key pipeline (see ``components/editor.py``'s
``on_app_action``) is folded directly into this table instead. Was
previously wired as a raw ``frame == "\\x0f"`` string comparison in
``app.py``'s ``_on_stdin_frame`` — silently inert on any terminal where
Kitty keyboard-protocol negotiation succeeded, since Ctrl+O then arrives as
CSI-u (``"\\x1b[111;5u"``), never the legacy byte. Routing it through
``parse_key`` → ``key_id`` → this table fixes that: both encodings resolve
to the same ``"ctrl+o"`` key id.

Declared deviation (issue #14, Esc/Ctrl+C parity fix): ``"app.interrupt":
"escape"`` is added for the same reason and via the same mechanism as
``"app.tools.expand"`` above — another ``app.*`` action folded into this
editor-only table for lack of a separate app-level bindings table. Upstream
(``interactive-mode.ts``) binds Escape to interrupt the in-flight turn while
Ctrl+C is reserved for "clear editor / double-tap to exit" — this port used
to have that backwards (Ctrl+C cancelled the turn, Escape did nothing extra
here). ``"escape"`` is already bound to ``"tui.select.cancel"`` above (menu
close); ``components/editor.py``'s ``handle_key`` checks the
autocomplete-menu-open ``"tui.select.cancel"`` branch *first* and returns
before ever reaching the ``"app.interrupt"`` check, so a menu open when Esc
is pressed still closes the menu instead of interrupting a turn — the two
bindings sharing the same key is intentional, not a conflict, since at most
one of their guarding conditions is ever true for a given key press.

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
    # Deviation (task-19 acceptance bug 2): not a "tui.*" editor action —
    # see the module docstring's "Declared deviation (task-19 acceptance
    # bug 2 fix)" note above for why it lives here anyway.
    "app.tools.expand": "ctrl+o",
    # Deviation (issue #14): not a "tui.*" editor action — see the module
    # docstring's "Declared deviation (issue #14, Esc/Ctrl+C parity fix)"
    # note above. Shares the "escape" key with "tui.select.cancel" above by
    # design (editor.py's handle_key checks the menu-open cancel branch
    # first).
    "app.interrupt": "escape",
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
