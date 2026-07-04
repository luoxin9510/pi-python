"""RED-phase tests for Task 13's ``EditorComponent`` Protocol
(``src/pipython/tui/engine/editor_protocol.py`` — does not exist yet, so
every test below fails at collection with ``ImportError`` until GREEN
creates that module).

Upstream source: ``editor-component.ts`` (74 lines) — "Interface for custom
editor components. This allows extensions to provide their own editor
implementation ... while maintaining compatibility with the core
application." (editor-component.ts:4-9). The whole point of this file
existing is the same three design principles this repo's CLAUDE.md
enshrines for the *Python* port ("一切皆可注入" / boundaries as
``typing.Protocol``): the app layer must depend on ``EditorComponent``, not
on the concrete ``Editor`` class, so a caller can swap in a vim-mode editor,
an emacs-mode editor, etc.

Required vs. optional split (editor-component.ts:11-74), and why only the
required half is a *formal* Protocol member here:

- **Required** (``getText``/``setText``/``handleInput``/``render``/
  ``invalidate`` + the ``Focusable`` mixin's ``focused``) — ported 1:1 as
  ``EditorComponent``'s six formal members below, and checked via
  ``isinstance()`` against ``@runtime_checkable``.
- **Optional** (``onSubmit``/``onChange``/``addToHistory``/
  ``insertTextAtCursor``/``getExpandedText``/``setAutocompleteProvider``/
  ``borderColor``/``setPaddingX``/``setAutocompleteMaxVisible``) — **not**
  formal Protocol members, following the precedent already established by
  ``engine/tui.py``'s own module docstring (deviation 9: "Python's
  ``typing.Protocol`` has no equivalent [of TypeScript's ``?:`` optional
  member] ... declaring it here would make it a *required* member for
  every ``Component``"). ``@runtime_checkable``'s ``isinstance()`` check
  has no required-vs-optional distinction in Python — it treats every
  declared member as mandatory — so baking the optional hooks into the
  Protocol would make ``isinstance(minimal_editor, EditorComponent)``
  falsely reject a legitimate minimal implementation that only supports
  the six required members. This file instead checks the optional hooks'
  *presence on this port's concrete ``Editor``* via plain ``getattr``
  probing (matching the job description's "including optional hooks
  presence: insert_text_at_cursor/get_expanded_text/set_autocomplete_provider"
  instruction, and ``tui.py``'s own ``is_focusable``-style dynamic-probe
  convention), never via Protocol ``isinstance``.

Naming note for GREEN (flag, do not silently "fix" by guessing): the
brief's literal Protocol hook name is ``add_to_history`` (snake_case of
upstream's ``addToHistory``), but this port's *already-implemented* method
(task-12, ``editor.py``) is named ``add_history`` — see
``TestEditorComponentOptionalHooks::test_add_to_history_hook_present_and_functional``
below, which exercises the brief's literal name and will only pass once
GREEN adds ``add_to_history`` (as a new method, e.g. an alias of the
existing ``add_history`` — renaming outright would break the already-green
``tests/tui/components/test_editor_killring_undo_history.py``, which calls
``editor.add_history(...)`` directly).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pipython.tui.components.editor import Editor
from pipython.tui.engine.editor_protocol import EditorComponent
from pipython.tui.engine.tui import TUI

if TYPE_CHECKING:
    # Type-hint-only: a real (non-TYPE_CHECKING) `from tests.tui.engine.conftest
    # import RecordingTerm` fails at runtime the same way it does for every
    # other file in this directory (test_overlay_focus.py, test_resize_cursor.py,
    # test_diff_render.py all guard the identical import the same way) —
    # `tests/tui/__init__.py` does not exist, so pytest's rootdir-insertion
    # makes `tests/tui/` itself the sys.path entry and imports this module as
    # plain `engine.test_editor_protocol`, never as `tests.tui.engine....`.
    # The `term` fixture below comes from this directory's own conftest.py
    # (auto-injected by pytest — same-directory conftest fixtures need no
    # import at all), which is the actually-working equivalent.
    from tests.tui.engine.conftest import RecordingTerm


@pytest.fixture
def tui(term: "RecordingTerm") -> TUI:
    """Mirrors test_overlay_focus.py's own local ``tui`` fixture: wraps the
    same-directory conftest.py's ``term`` fixture (auto-injected by
    pytest — no import needed for that one)."""
    return TUI(term)


class _MinimalEditorComponent:
    """A from-scratch class satisfying only ``EditorComponent``'s six
    *required* members — no ``Editor`` inheritance at all. Exists to prove
    the Protocol is genuinely structural (per this repo's "一切皆可注入"
    principle: any object shaped right satisfies it, not just this port's
    own ``Editor``) and that the *optional* hooks are correctly excluded
    from the ``isinstance()``-checked surface (see module docstring)."""

    def __init__(self) -> None:
        self._text = ""
        self.focused = False

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text

    def handle_input(self, data: str) -> None:
        self._text += data

    def render(self, width: int) -> list[str]:
        return [self._text]

    def invalidate(self) -> None:
        pass


class _MissingHandleInput:
    """Same as ``_MinimalEditorComponent`` but missing ``handle_input`` —
    must NOT satisfy ``isinstance(..., EditorComponent)``, proving the
    Protocol actually gates on all six required members rather than
    silently passing anything with a ``focused`` attribute."""

    def __init__(self) -> None:
        self.focused = False

    def get_text(self) -> str:
        return ""

    def set_text(self, text: str) -> None:
        pass

    def render(self, width: int) -> list[str]:
        return []

    def invalidate(self) -> None:
        pass


class TestEditorComponentProtocolShape:
    """The Protocol itself: runtime_checkable, six required members,
    structural (not nominal — no inheritance required)."""

    def test_editor_component_is_runtime_checkable(self) -> None:
        """``isinstance()`` against ``EditorComponent`` must not raise
        ``TypeError`` (which is what a non-``@runtime_checkable`` Protocol
        raises on isinstance checks)."""
        try:
            isinstance(object(), EditorComponent)
        except TypeError as e:
            pytest.fail(
                f"EditorComponent must be @runtime_checkable for isinstance() "
                f"checks to work at all: {e}"
            )

    def test_plain_object_does_not_satisfy_editor_component(self) -> None:
        assert not isinstance(object(), EditorComponent)

    def test_minimal_from_scratch_class_satisfies_editor_component(self) -> None:
        """Structural typing: a class with no relationship to ``Editor``
        whatsoever, but the right six members, must satisfy the Protocol —
        this is the entire reason ``editor_protocol.py`` exists (per
        editor-component.ts's own stated purpose, quoted in the module
        docstring): so the app layer can accept *any* conforming editor,
        not just this port's concrete ``Editor``."""
        assert isinstance(_MinimalEditorComponent(), EditorComponent)

    def test_class_missing_a_required_member_does_not_satisfy_editor_component(self) -> None:
        """Negative control for the test above: dropping just
        ``handle_input`` must flip the isinstance check to False -
        confirms the Protocol actually enforces all six required members
        rather than e.g. only checking for ``focused``."""
        assert not isinstance(_MissingHandleInput(), EditorComponent)


class TestEditorSatisfiesEditorComponent:
    """This port's concrete ``Editor`` (components/editor.py) must satisfy
    ``EditorComponent`` — the whole point of Task 13's editor_protocol.py
    addition being paired with editor.py changes in the same brief."""

    def test_editor_instance_satisfies_editor_component(self) -> None:
        """This is a genuine, currently-failing assertion even once the
        module exists to import: this port's ``Editor`` currently exposes
        ``text``/``cursor`` as *properties* (task-11 brief's own Produces
        list), not a callable ``get_text()`` method — ``editor-component.ts``
        requires ``getText(): string`` as a *method*. GREEN must add a
        ``get_text()`` method (e.g. a thin ``return self.text`` wrapper) for
        this to pass; the property alone does not make ``callable(editor.get_text)``
        true."""
        editor = Editor()
        assert isinstance(editor, EditorComponent)

    def test_editor_get_text_and_set_text_are_real_methods(self) -> None:
        """Beyond the isinstance check above: get_text()/set_text() must
        actually be *callable methods* (matching editor-component.ts's
        ``getText(): string``/``setText(text: string): void``), and must
        round-trip through the same state as the existing ``.text``
        property / ``.set_text()`` method — not a second, disconnected copy
        of the buffer."""
        editor = Editor()
        assert callable(editor.get_text)
        assert editor.get_text() == ""

        editor.set_text("hello")
        assert editor.get_text() == "hello"
        assert editor.text == "hello", (
            "get_text() must reflect the same state as the .text property"
        )

        editor.handle_input(" world")
        assert editor.get_text() == "hello world"

    def test_editor_render_invalidate_focused_satisfy_component_contract(self) -> None:
        editor = Editor()
        assert editor.focused is False
        editor.focused = True
        assert editor.focused is True

        lines = editor.render(40)
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

        editor.invalidate()  # must not raise


class TestEditorComponentOptionalHooks:
    """Optional hooks, checked by plain attribute presence on the concrete
    ``Editor`` (never via Protocol isinstance — see module docstring)."""

    def test_on_submit_hook_present(self) -> None:
        """Uses a functional round-trip rather than ``is``-identity: a
        bound method of a built-in type (``list.append``) is rebuilt on
        every attribute access in CPython, so ``calls.append is
        calls.append`` is itself ``False`` even though both wrap the same
        underlying list - an ``is`` comparison here would be a test bug,
        not a real assertion about ``on_submit``."""
        calls: list[str] = []
        editor = Editor(on_submit=calls.append)
        assert hasattr(editor, "on_submit")
        assert callable(editor.on_submit)
        editor.on_submit("submitted text")
        assert calls == ["submitted text"]

    def test_add_to_history_hook_present_and_functional(self) -> None:
        """Brief's literal Protocol hook name is ``add_to_history`` (see
        module docstring's "Naming note for GREEN") - this deliberately
        exercises that exact name, not the already-implemented
        ``add_history``."""
        editor = Editor()
        assert hasattr(editor, "add_to_history"), (
            "EditorComponent's optional 'add_to_history' hook "
            "(editor-component.ts:40 addToHistory) is missing from Editor - "
            "see this file's module docstring naming note"
        )
        editor.add_to_history("remembered prompt")
        assert "remembered prompt" in editor.history

    def test_insert_text_at_cursor_hook_present_and_functional(self) -> None:
        """editor-component.ts:47 ``insertTextAtCursor``. This port already
        has a *private* ``_insert_text_at_cursor`` (task-12); the brief
        requires a *public* hook of this exact name for the Protocol's
        optional-hooks surface — also the un-skip trigger for the three
        ``pending Task 13 insert_text_at_cursor hook`` tests in
        ``tests/tui/components/test_editor_killring_undo_history.py``
        (lines 935-997)."""
        editor = Editor()
        editor.set_text("hello world")
        editor.handle_input("\x01")  # Ctrl+A - start of line
        for _ in range(5):
            editor.handle_input("\x1b[C")  # Right, to just after "hello"

        assert hasattr(editor, "insert_text_at_cursor")
        editor.insert_text_at_cursor("/tmp/image.png")
        assert editor.text == "hello/tmp/image.png world"

    def test_set_autocomplete_provider_hook_present(self, tui: TUI) -> None:
        """editor-component.ts:60 ``setAutocompleteProvider`` - Task 13's
        own headline addition."""
        editor = Editor()
        assert hasattr(editor, "set_autocomplete_provider")

        class _StubProvider:
            async def get_suggestions(
                self, lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
            ):
                return [], ""

            def apply_completion(self, lines, cursor_line, cursor_col, item, prefix):
                return list(lines), cursor_line, cursor_col

        editor.set_autocomplete_provider(_StubProvider(), tui)  # must not raise

    def test_get_expanded_text_hook_present(self) -> None:
        """editor-component.ts:53 ``getExpandedText`` - already implemented
        (task-12); listed here for completeness of the optional-hooks
        enumeration the job description asks for, and because the whole
        file fails at collection today regardless (module doesn't exist
        yet), so this assertion is still part of the RED signal."""
        editor = Editor()
        assert hasattr(editor, "get_expanded_text")
        assert editor.get_expanded_text() == editor.text

    def test_minimal_editor_component_lacking_optional_hooks_still_satisfies_protocol(self) -> None:
        """Confirms the optional hooks are genuinely *not* part of the
        ``isinstance()``-checked surface: ``_MinimalEditorComponent`` has
        none of on_submit/on_change/add_to_history/insert_text_at_cursor/
        set_autocomplete_provider/get_expanded_text, yet must still satisfy
        ``EditorComponent`` (it already does per
        ``TestEditorComponentProtocolShape`` above; this test names *why*
        explicitly, as a guard against a future edit accidentally
        promoting an optional hook into a required Protocol member)."""
        minimal = _MinimalEditorComponent()
        for optional_hook in (
            "on_submit",
            "on_change",
            "add_to_history",
            "insert_text_at_cursor",
            "set_autocomplete_provider",
            "get_expanded_text",
        ):
            assert not hasattr(minimal, optional_hook), (
                f"test fixture bug: _MinimalEditorComponent should not define {optional_hook!r}"
            )
        assert isinstance(minimal, EditorComponent)
