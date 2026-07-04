"""``EditorComponent`` Protocol — Python port of upstream pi's
``packages/tui/src/editor-component.ts`` (74 lines).

"Interface for custom editor components. This allows extensions to provide
their own editor implementation (e.g., vim mode, emacs mode, custom
keybindings) while maintaining compatibility with the core application."
(editor-component.ts:4-9). That is the whole reason this file exists: the
app layer must depend on ``EditorComponent`` (structural, "一切皆可注入" per
this repo's CLAUDE.md design principles), not on the concrete
``components.editor.Editor`` — so a caller can swap in a vim-mode editor, an
emacs-mode editor, etc., without ``pipython.tui`` app code changing at all.

Required vs. optional split (editor-component.ts:11-74), and why only the
required half is a *formal* ``Protocol`` member:

- **Required** (``getText``/``setText``/``handleInput``/``render``/
  ``invalidate`` + the ``Focusable`` mixin's ``focused``) — ported 1:1 below
  as ``EditorComponent``'s six formal members, checked via ``isinstance()``
  against ``@runtime_checkable``.
- **Optional** (``onSubmit``/``onChange``/``addToHistory``/
  ``insertTextAtCursor``/``getExpandedText``/``setAutocompleteProvider``/
  ``borderColor``/``setPaddingX``/``setAutocompleteMaxVisible``) — **not**
  formal Protocol members, following the precedent already established by
  ``engine/tui.py``'s own module docstring (deviation 9: "Python's
  ``typing.Protocol`` has no equivalent [of TypeScript's ``?:`` optional
  member] ... declaring it here would make it a *required* member for every
  ``Component``"). ``@runtime_checkable``'s ``isinstance()`` check has no
  required-vs-optional distinction in Python — it treats every declared
  member as mandatory — so baking the optional hooks into the Protocol
  would make ``isinstance(minimal_editor, EditorComponent)`` falsely reject
  a legitimate minimal implementation that only supports the six required
  members. Callers instead probe for these dynamically via plain
  ``getattr``/``hasattr`` on whatever concrete object they're holding
  (exactly like ``tui.py``'s own ``is_focusable``-style dynamic-probe
  convention), never via ``EditorComponent`` ``isinstance``.

Naming reconciliation (flagged in task-13's RED report, resolved here):
upstream's optional hook is ``addToHistory`` — this port's literal
snake_case target name is therefore ``add_to_history``. ``editor.py``
(task-12) had already shipped a method named ``add_history`` before this
Protocol existed. Rather than rename the shipped method (which would break
the already-green ``tests/tui/components/test_editor_killring_undo_history.py``,
calling ``editor.add_history(...)`` directly), ``Editor`` now exposes
*both*: ``add_to_history`` (the upstream-faithful primary name added by
task 13, matching this Protocol's docstring) as a one-line forwarding alias
of the pre-existing ``add_history`` (kept for backward compatibility with
already-green tests). See ``components/editor.py``'s module docstring
deviation 11 for the full disclosure.

Consumes: nothing (this module has no import-time dependency on
``components.editor`` at all — the whole point is structural typing, not
inheritance).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["EditorComponent"]


@runtime_checkable
class EditorComponent(Protocol):
    """editor-component.ts:11-74 ``EditorComponent``, narrowed to its six
    *required* members (module docstring's required/optional split)."""

    focused: bool
    """The ``Focusable`` mixin's sole attribute (``Component`` base
    interface, editor-component.ts:11 ``extends Component``)."""

    def get_text(self) -> str:
        """editor-component.ts:17 ``getText(): string`` — current text
        content."""
        ...

    def set_text(self, text: str) -> None:
        """editor-component.ts:20 ``setText(text: string): void``."""
        ...

    def handle_input(self, data: str) -> None:
        """editor-component.ts:23 ``handleInput(data: string): void`` — raw
        terminal input (key presses, paste sequences, etc.)."""
        ...

    def render(self, width: int) -> list[str]:
        """``Component``'s ``render`` (editor-component.ts:11's base
        interface)."""
        ...

    def invalidate(self) -> None:
        """``Component``'s ``invalidate`` (editor-component.ts:11's base
        interface)."""
        ...
