"""RED-phase tests for Task 13: editor autocomplete hooks + SelectList
overlay integration.

Translation of upstream TypeScript tests:
``~/Developer/nukcole-pi/packages/tui/test/editor.test.ts``,
``describe("Autocomplete")`` (lines 2092-2822) — all 18 ``it()`` blocks
ported 1:1 below in ``TestAutocomplete`` (see the enumeration table in
``.superpowers/sdd/task-13-report.md``, "RED phase round 2" section).

Plus this port's own extensions (``TestAutocompleteKeyRerouting``,
``TestAutocompleteOverlayIntegration``) covering ground the 18 upstream
cases never exercise: menu-open Up/Down navigation actually changing which
item gets applied, ``apply_completion``'s cursor write-back, the
Enter-on-slash-command-name-then-fall-through-to-submit branch
(editor.ts:701-708), the ``is_cancelled`` callable itself flipping True
(not just an abort side-effect counter), and the real-TUI overlay
(``tui.show_overlay``) compositing/focus contract per the brief.

Target surface under test (task-13-brief.md's "Produces" list) — **does
not exist yet**, so every test in this file fails at collection
(``ImportError``) until GREEN adds it to
``src/pipython/tui/components/editor.py``:

- ``AutocompleteItem`` — re-exported alias of ``select_list.SelectItem``
  (dataclass: ``value: str``, ``label: str``, ``description: str | None =
  None``).
- ``AutocompleteProvider`` (``Protocol``, structural — this file never
  needs to import it; every mock provider below just duck-types it):
  ``async def get_suggestions(self, lines, cursor_line, cursor_col, *,
  force=False, is_cancelled=lambda: False) -> tuple[list[AutocompleteItem],
  str]``; ``def apply_completion(self, lines, cursor_line, cursor_col,
  item, prefix) -> tuple[list[str], int, int]``; optional
  ``trigger_characters: str``.
- ``Editor.set_autocomplete_provider(provider, tui)`` and
  ``Editor.is_showing_autocomplete() -> bool`` (Python name for upstream's
  ``isShowingAutocomplete()``).

Translation notes / deliberate adaptations (cite these before assuming a
mismatch is a translation error):

1. **``get_suggestions`` never returns ``None``.** Upstream's
   ``getSuggestions`` returns ``AutocompleteSuggestions | null``
   (autocomplete.ts:247-252); the brief's literal Python signature is
   ``-> tuple[list[AutocompleteItem], str]`` with no ``| None``. Every mock
   provider below returns ``([], "")`` wherever upstream would ``return
   null`` — an empty items list is this port's "no suggestions" sentinel,
   not ``Optional``.

2. **``is_cancelled`` is a polling callable, not an event-driven
   ``AbortSignal``.** Upstream mocks call
   ``options.signal.addEventListener("abort", ...)``; the brief's Python
   signature instead threads a plain ``Callable[[], bool]``. Every mock
   below that needs to observe cancellation polls ``is_cancelled()`` in a
   bounded loop with short ``asyncio.sleep`` increments, which is the
   direct behavioral equivalent (an abort becomes observable on the mock's
   next poll instead of instantaneously), not a simplification of *when*
   cancellation must take effect.

3. **The debounce seam this file's tests rely on** (GREEN must implement
   this contract): ``Editor.AUTOCOMPLETE_DEBOUNCE_MS`` is a plain class
   attribute, consulted exactly like upstream's module-level
   ``ATTACHMENT_AUTOCOMPLETE_DEBOUNCE_MS = 20`` (editor.ts:236) for natural
   (non-force, non-explicit-Tab) trigger-character-driven requests only —
   slash-command requests are never debounced in upstream either (``/`` is
   permanently excluded from ``autocompleteTriggerCharacters``, so
   ``buildDebouncePattern``'s pattern never matches slash text — see
   editor.ts:2175-2185's ``character === "/"`` skip). Tests that must
   observe debounce behavior ``monkeypatch.setattr(Editor,
   "AUTOCOMPLETE_DEBOUNCE_MS", 5)`` and then use a *bounded* real wait an
   order of magnitude longer (``await asyncio.sleep(0.05)``) — mirroring
   upstream's own ratio (20ms debounce, 50ms test wait), just scaled down
   so the whole suite stays fast. This is a manual, deterministic-enough
   seam (the wait margin makes the ordering guaranteed by construction),
   not an unbounded sleep.

4. **Tests 16-18 do not construct upstream's ``CombinedAutocompleteProvider``**
   (autocomplete.ts:273-786, a large file/slash-command completion engine)
   — it is not this task's Produces surface (task-13-brief.md's "Consumes"
   list only names Task 10's ``SelectList``/Task 8's overlay/Task 11-12's
   Editor; ``CombinedAutocompleteProvider`` belongs to a future slash-
   command task). Each of those three tests instead uses a small
   hand-written mock ``AutocompleteProvider`` that reproduces the exact
   *observable behavior* upstream's test exercises through
   ``CombinedAutocompleteProvider`` (async argument completions; a
   non-list "invalid" result being ignored; a command with no argument
   completer never producing a menu) — see each test's own docstring for
   the specific one-branch stand-in used (e.g. test 18's
   ``_apply_slash_command_name`` mimics only
   ``CombinedAutocompleteProvider.applyCompletion``'s slash-command-name
   branch, autocomplete.ts:391-405).

5. **``RecordingTerm`` import.** ``tests/tui/components/`` has no
   ``tests/__init__.py``/``tests/tui/__init__.py`` ancestor (only
   ``tests/tui/components/__init__.py`` and ``tests/tui/engine/__init__.py``
   exist), so pytest's rootdir-insertion makes ``tests/tui/`` itself the
   sys.path entry and imports this file's own package as plain
   ``components`` — meaning ``tests.tui.engine.conftest`` is *not*
   importable as such (verified: a real, non-``TYPE_CHECKING`` import of
   that dotted path raises ``ModuleNotFoundError: No module named
   'tests'``). ``engine.conftest`` (the sibling top-level package sharing
   the same ``tests/tui/`` sys.path entry) *is* importable, and reliably so
   regardless of collection order — verified directly, since importing
   this file already requires ``tests/tui/`` on sys.path in the first
   place. Hence ``from engine.conftest import RecordingTerm`` below, not
   the dotted path other same-directory (``tests/tui/engine/``) test files
   use under ``TYPE_CHECKING`` only.
"""

from __future__ import annotations

import asyncio
import gc
import re
from typing import TYPE_CHECKING, Awaitable, Callable

import pytest

from pipython.tui.components.editor import AutocompleteItem, Editor
from pipython.tui.engine.tui import TUI

# See module docstring note 5 for why this is `engine.conftest`, not
# `tests.tui.engine.conftest`.
from engine.conftest import RecordingTerm

if TYPE_CHECKING:
    pass


# =============================================================================
# Shared test helpers (module-level, mirroring editor.test.ts's own
# module-level `applyCompletion`/`flushAutocomplete` helpers, lines 16-39).
# =============================================================================


def apply_completion(
    lines: list[str],
    cursor_line: int,
    cursor_col: int,
    item: AutocompleteItem,
    prefix: str,
) -> tuple[list[str], int, int]:
    """editor.test.ts:17-34's shared ``applyCompletion`` helper: replace the
    ``prefix`` immediately before the cursor with ``item.value``."""
    line = lines[cursor_line] if cursor_line < len(lines) else ""
    before = line[: cursor_col - len(prefix)]
    after = line[cursor_col:]
    new_lines = list(lines)
    new_lines[cursor_line] = before + item.value + after
    return new_lines, cursor_line, cursor_col - len(prefix) + len(item.value)


async def flush_autocomplete() -> None:
    """editor.test.ts:36-39's ``flushAutocomplete``: yield control back to
    the event loop long enough for an *undebounced* (force-Tab, explicit
    Tab, or slash-command) autocomplete request to run to completion.
    Insufficient for the debounced (@/#/custom-trigger-char) path — see
    module docstring note 3 for that seam instead."""
    for _ in range(5):
        await asyncio.sleep(0)


GetSuggestionsFn = Callable[..., Awaitable[tuple[list[AutocompleteItem], str]]]


class _Provider:
    """Adapts a plain async ``get_suggestions`` callable (plus optional
    ``apply_completion``/``trigger_characters``) into an object structurally
    satisfying the ``AutocompleteProvider`` Protocol — the Python stand-in
    for upstream's inline ``{ getSuggestions, applyCompletion,
    triggerCharacters }`` object literals (JS object-literal-with-methods
    has no single-expression Python equivalent; this tiny adapter carries
    no behavior of its own beyond forwarding)."""

    def __init__(
        self,
        get_suggestions: GetSuggestionsFn,
        *,
        apply_completion: Callable[..., tuple[list[str], int, int]] = apply_completion,
        trigger_characters: str | None = None,
    ) -> None:
        self._get_suggestions = get_suggestions
        self.apply_completion = apply_completion
        if trigger_characters is not None:
            self.trigger_characters = trigger_characters

    async def get_suggestions(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
    ):
        return await self._get_suggestions(
            lines, cursor_line, cursor_col, force=force, is_cancelled=is_cancelled
        )


def _apply_slash_command_name(
    lines: list[str],
    cursor_line: int,
    cursor_col: int,
    item: AutocompleteItem,
    prefix: str,
) -> tuple[list[str], int, int]:
    """Mimics *only* upstream's ``CombinedAutocompleteProvider.applyCompletion``
    slash-command-name branch (autocomplete.ts:391-405): replaces the whole
    ``/<partial>`` prefix with ``/<value> `` (trailing space). Used solely by
    test 18's translation, which stands in for
    ``CombinedAutocompleteProvider`` — see module docstring note 4."""
    line = lines[cursor_line] if cursor_line < len(lines) else ""
    before = line[: cursor_col - len(prefix)]
    after = line[cursor_col:]
    new_line = f"{before}/{item.value} {after}"
    new_lines = list(lines)
    new_lines[cursor_line] = new_line
    return new_lines, cursor_line, len(before) + len(item.value) + 2


def _make_tui() -> TUI:
    """A real ``TUI`` over a real ``RecordingTerm`` — never a mock/stub —
    per this repo's "no mocks for our own engine" testing convention. Most
    of the 18 ported tests never call ``tui.do_render()`` at all (upstream
    itself only calls ``.render(80)`` directly in test 5); ``tui`` still
    has to be a real ``TUI`` instance because ``set_autocomplete_provider``'s
    signature requires one (this port's ``Editor`` holds no ``tui``
    reference of its own — task-11 module docstring deviation 1)."""
    return TUI(RecordingTerm())


def _make_wired_tui(editor: Editor) -> TUI:
    """Fix round 1: a real ``TUI`` with ``editor`` set as *both* root and
    focus, so a test can drive input through the actual production path
    (``tui.handle_input``) instead of calling ``editor.handle_input``
    directly. Before the Critical-1 fix (``show_overlay``'s
    ``non_capturing`` option), routing through ``tui.handle_input`` while
    an autocomplete overlay was open would silently no-op forever — every
    test in ``TestAutocompleteViaTuiHandleInput`` below, and every
    conversion of an existing ``TestAutocomplete``/``TestAutocompleteKeyRerouting``
    case to this helper, is a real regression guard against that exact
    deadlock reappearing (calling ``editor.handle_input`` directly, as
    every pre-fix-round-1 test in this file did, bypasses ``TUI`` entirely
    and so could never have caught it)."""
    tui = TUI(RecordingTerm())
    tui.set_root(editor)
    tui.set_focus(editor)
    return tui


# =============================================================================
# The 18 upstream `it()` blocks, editor.test.ts:2092-2822, ported 1:1.
# =============================================================================


class TestAutocomplete:
    async def test_auto_applies_single_force_file_suggestion_without_showing_menu(self) -> None:
        """editor.test.ts:2093."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            if prefix == "Work":
                return [AutocompleteItem(value="Workspace/", label="Workspace/")], "Work"
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "Work":
            editor.handle_input(ch)
        assert editor.text == "Work"

        editor.handle_input("\t")
        await flush_autocomplete()
        assert editor.text == "Workspace/"
        assert editor.is_showing_autocomplete() is False

        editor.handle_input("\x1b[45;5u")  # Ctrl+- (undo)
        assert editor.text == "Work"

    async def test_shows_menu_when_force_file_has_multiple_suggestions(self) -> None:
        """editor.test.ts:2134. Converted (fix round 1) to drive input
        through ``tui.handle_input`` rather than ``editor.handle_input``
        directly — see ``_make_wired_tui``'s docstring: this is a real
        regression guard for the Critical-1 focus-stealing deadlock (before
        the fix, ``tui.handle_input`` would have silently no-op'd the
        moment the menu opened, since focus would have been stolen onto
        the passive ``SelectList`` overlay)."""
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            if prefix == "src":
                return [
                    AutocompleteItem(value="src/", label="src/"),
                    AutocompleteItem(value="src.txt", label="src.txt"),
                ], "src"
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "src":
            tui.handle_input(ch)
        assert editor.text == "src"

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.text == "src"
        assert editor.is_showing_autocomplete() is True
        assert editor.focused is True, "the editor must stay focused while the menu is open"

        tui.handle_input("\t")
        assert editor.text == "src/"
        assert editor.is_showing_autocomplete() is False

    async def test_keeps_suggestions_open_when_typing_in_force_mode_tab_triggered(self) -> None:
        """editor.test.ts:2178."""
        tui = _make_tui()
        editor = Editor()

        all_files = [
            AutocompleteItem(value="readme.md", label="readme.md"),
            AutocompleteItem(value="package.json", label="package.json"),
            AutocompleteItem(value="src/", label="src/"),
            AutocompleteItem(value="dist/", label="dist/"),
        ]

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            should_match = force or "/" in prefix or prefix.startswith(".")
            if not should_match:
                return [], ""
            filtered = [f for f in all_files if f.value.lower().startswith(prefix.lower())]
            if filtered:
                return filtered, prefix
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("r")
        await flush_autocomplete()
        assert editor.text == "r"
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("e")
        await flush_autocomplete()
        assert editor.text == "re"
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\t")
        assert editor.text == "readme.md"
        assert editor.is_showing_autocomplete() is False

    async def test_debounces_at_autocomplete_while_typing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """editor.test.ts:2230. See module docstring note 3 for the
        debounce seam this test relies on."""
        monkeypatch.setattr(Editor, "AUTOCOMPLETE_DEBOUNCE_MS", 5)
        tui = _make_tui()
        editor = Editor()
        suggestion_calls = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal suggestion_calls
            suggestion_calls += 1
            text = (lines[0] if lines else "")[:cursor_col]
            return [AutocompleteItem(value="@main.ts", label="main.ts")], text

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("@")
        editor.handle_input("m")
        editor.handle_input("a")
        editor.handle_input("i")

        assert suggestion_calls == 0
        assert editor.is_showing_autocomplete() is False

        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert suggestion_calls == 1
        assert editor.is_showing_autocomplete() is True

    async def test_requeries_autocomplete_picker_when_cursor_moves_back_into_command_name(
        self,
    ) -> None:
        """editor.test.ts:2263 (regression earendil-works/pi#5496). Upstream
        calls ``editor.render(80)`` directly (its ``autocompleteList``
        renders inline as part of Editor's own component tree, editor.ts:
        578-581); this port routes the menu through ``tui.show_overlay``
        instead (per the task-13 brief), so the equivalent content check
        goes through the full TUI pipeline (``tui.do_render()`` +
        ``term.screen()``) rather than ``editor.render()`` alone — see
        module docstring's architecture note and
        ``TestAutocompleteOverlayIntegration`` below."""
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before = (lines[0] if lines else "")[:cursor_col]
            if not before.startswith("/"):
                return [], ""
            if " " in before:
                prefix = before[before.index(" ") + 1 :]
                return [
                    AutocompleteItem(value="repo", label="repo"),
                    AutocompleteItem(value="message", label="message"),
                    AutocompleteItem(value="help", label="help"),
                ], prefix
            return [AutocompleteItem(value="cmd", label="cmd")], before

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/cmd ":
            editor.handle_input(ch)
            await flush_autocomplete()
        assert editor.text == "/cmd "
        assert editor.is_showing_autocomplete() is True

        tui.do_render()
        at_arg = "\n".join(term.screen())
        assert "repo" in at_arg, "argument menu should be visible at `/cmd `"

        editor.handle_input("\x1b[D")  # Left
        await flush_autocomplete()

        tui.do_render()
        after_move = "\n".join(term.screen())
        assert "repo" not in after_move, "stale argument menu must not survive the cursor move"
        assert "message" not in after_move, "stale argument menu must not survive the cursor move"

    async def test_debounces_hash_autocomplete_while_typing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """editor.test.ts:2322."""
        monkeypatch.setattr(Editor, "AUTOCOMPLETE_DEBOUNCE_MS", 5)
        tui = _make_tui()
        editor = Editor()
        suggestion_calls = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal suggestion_calls
            suggestion_calls += 1
            text = (lines[0] if lines else "")[:cursor_col]
            return [AutocompleteItem(value="#2983", label="#2983")], text

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("#")
        editor.handle_input("2")
        editor.handle_input("9")
        editor.handle_input("8")

        assert suggestion_calls == 0
        assert editor.is_showing_autocomplete() is False

        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert suggestion_calls == 1
        assert editor.is_showing_autocomplete() is True

    async def test_debounces_custom_trigger_characters_autocomplete_while_typing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """editor.test.ts:2355."""
        monkeypatch.setattr(Editor, "AUTOCOMPLETE_DEBOUNCE_MS", 5)
        tui = _make_tui()
        editor = Editor()
        suggestion_calls = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal suggestion_calls
            suggestion_calls += 1
            prefix = (lines[0] if lines else "")[:cursor_col]
            return [AutocompleteItem(value="$skill-name", label="skill-name")], prefix

        editor.set_autocomplete_provider(_Provider(get_suggestions, trigger_characters="$"), tui)

        editor.handle_input("$")
        editor.handle_input("s")
        editor.handle_input("k")

        assert suggestion_calls == 0
        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert suggestion_calls == 1
        assert editor.is_showing_autocomplete() is True

    async def test_resets_custom_trigger_characters_when_provider_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """editor.test.ts:2381."""
        monkeypatch.setattr(Editor, "AUTOCOMPLETE_DEBOUNCE_MS", 5)
        tui = _make_tui()
        editor = Editor()
        suggestion_calls = 0

        async def first_get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            return [AutocompleteItem(value="$skill-name", label="skill-name")], "$"

        async def second_get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal suggestion_calls
            suggestion_calls += 1
            return [AutocompleteItem(value="$skill-name", label="skill-name")], "$"

        editor.set_autocomplete_provider(
            _Provider(first_get_suggestions, trigger_characters="$"), tui
        )
        editor.set_autocomplete_provider(_Provider(second_get_suggestions), tui)

        editor.handle_input("$")
        editor.handle_input("s")
        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert suggestion_calls == 0
        assert editor.is_showing_autocomplete() is False

    async def test_aborts_active_at_autocomplete_when_typing_continues(self) -> None:
        """editor.test.ts:2407. See module docstring note 2: ``is_cancelled``
        is polled (bounded loop), not an event-driven ``AbortSignal``."""
        tui = _make_tui()
        editor = Editor()
        aborts = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal aborts
            for _ in range(200):
                if is_cancelled():
                    aborts += 1
                    return [], ""
                await asyncio.sleep(0.005)
            return [AutocompleteItem(value="@main.ts", label="main.ts")], "@main"

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("@")
        editor.handle_input("m")
        editor.handle_input("a")
        editor.handle_input("i")
        await asyncio.sleep(0.25)
        editor.handle_input("n")
        await asyncio.sleep(0.05)

        assert aborts == 1

    async def test_hides_autocomplete_when_backspacing_slash_command_to_empty(self) -> None:
        """editor.test.ts:2444."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            if prefix.startswith("/"):
                commands = [
                    AutocompleteItem(value="/model", label="model", description="Change model"),
                    AutocompleteItem(value="/help", label="help", description="Show help"),
                ]
                query = prefix[1:]
                filtered = [c for c in commands if c.value.startswith(query)]
                if filtered:
                    return filtered, prefix
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("/")
        await flush_autocomplete()
        assert editor.text == "/"
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\x7f")  # Backspace
        await flush_autocomplete()
        assert editor.text == ""
        assert editor.is_showing_autocomplete() is False

    async def test_applies_exact_typed_slash_argument_value_on_enter_even_when_first_item_is_highlighted(
        self,
    ) -> None:
        """editor.test.ts:2484."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before_cursor = (lines[0] if lines else "")[:cursor_col]
            m = re.fullmatch(r"/argtest\s+(\S+)", before_cursor)
            if m:
                argument_text = m.group(1)
                all_arguments = [
                    AutocompleteItem(value="one", label="one"),
                    AutocompleteItem(value="two", label="two"),
                    AutocompleteItem(value="three", label="three"),
                ]
                filtered = [a for a in all_arguments if a.value.startswith(argument_text)]
                if filtered:
                    return filtered, argument_text
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/argtest two":
            editor.handle_input(ch)

        assert editor.text == "/argtest two"
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")  # Enter

        assert editor.text == "/argtest two"

    async def test_selects_first_prefix_match_on_enter_when_typed_arg_is_not_exact_match(
        self,
    ) -> None:
        """editor.test.ts:2540."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before_cursor = (lines[0] if lines else "")[:cursor_col]
            m = re.fullmatch(r"/argtest\s+(\S+)", before_cursor)
            if m:
                argument_text = m.group(1)
                all_arguments = [
                    AutocompleteItem(value="two", label="two"),
                    AutocompleteItem(value="three", label="three"),
                    AutocompleteItem(value="twelve", label="twelve"),
                ]
                filtered = [a for a in all_arguments if a.value.startswith(argument_text)]
                if filtered:
                    return filtered, argument_text
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/argtest t":
            editor.handle_input(ch)

        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")
        assert editor.text == "/argtest two"

    async def test_highlights_unique_prefix_match_as_user_types_before_full_exact_match(
        self,
    ) -> None:
        """editor.test.ts:2591."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before_cursor = (lines[0] if lines else "")[:cursor_col]
            m = re.fullmatch(r"/argtest\s+(\S+)", before_cursor)
            if m:
                argument_text = m.group(1)
                all_arguments = [
                    AutocompleteItem(value="one", label="one"),
                    AutocompleteItem(value="two", label="two"),
                    AutocompleteItem(value="three", label="three"),
                ]
                return all_arguments, argument_text
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/argtest tw":
            editor.handle_input(ch)

        assert editor.text == "/argtest tw"
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")
        assert editor.text == "/argtest two"

    async def test_selects_first_prefix_match_when_multiple_items_match(self) -> None:
        """editor.test.ts:2640."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before_cursor = (lines[0] if lines else "")[:cursor_col]
            m = re.fullmatch(r"/argtest\s+(\S+)", before_cursor)
            if m:
                argument_text = m.group(1)
                all_arguments = [
                    AutocompleteItem(value="one", label="one"),
                    AutocompleteItem(value="two", label="two"),
                    AutocompleteItem(value="three", label="three"),
                ]
                return all_arguments, argument_text
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/argtest t":
            editor.handle_input(ch)

        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")
        assert editor.text == "/argtest two"

    async def test_works_for_builtin_style_command_argument_completion_path_model_like(
        self,
    ) -> None:
        """editor.test.ts:2686."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before_cursor = (lines[0] if lines else "")[:cursor_col]
            m = re.fullmatch(r"/model\s+(\S+)", before_cursor)
            if m:
                model_text = m.group(1)
                all_models = [
                    AutocompleteItem(value="gpt-4o", label="gpt-4o"),
                    AutocompleteItem(value="gpt-4o-mini", label="gpt-4o-mini"),
                    AutocompleteItem(value="claude-sonnet", label="claude-sonnet"),
                ]
                filtered = [m2 for m2 in all_models if m2.value.startswith(model_text)]
                if filtered:
                    return filtered, model_text
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "/model gpt-4o-mini":
            editor.handle_input(ch)

        assert editor.text == "/model gpt-4o-mini"
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")
        assert editor.text == "/model gpt-4o-mini"

    async def test_awaits_async_slash_command_argument_completions(self) -> None:
        """editor.test.ts:2749. Stands in for
        ``CombinedAutocompleteProvider`` + its ``getArgumentCompletions``
        hook — see module docstring note 4. The generic ``apply_completion``
        helper suffices here: upstream's own
        ``CombinedAutocompleteProvider.applyCompletion`` argument-completion
        branch (autocomplete.ts:427-444) reduces to a plain prefix-replace
        for this non-directory, non-slash-command-name case."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before = (lines[0] if lines else "")[:cursor_col]
            if before.startswith("/load-skills "):
                arg_prefix = before[len("/load-skills ") :]
                await asyncio.sleep(0.01)  # genuinely async, like the real hook
                if arg_prefix.startswith("s"):
                    return [AutocompleteItem(value="skill-a", label="skill-a")], arg_prefix
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)
        editor.set_text("/load-skills ")

        editor.handle_input("s")
        # This provider's ``await asyncio.sleep(0.01)`` is a real timer delay
        # (deliberately, to prove the editor genuinely awaits the coroutine
        # rather than assuming a synchronously-resolved one) - flush_autocomplete()'s
        # plain event-loop-turn yields alone cannot cross a real time delay,
        # so a small bounded real wait is needed here too (mirrors the
        # debounce-seam waits elsewhere in this file).
        await asyncio.sleep(0.05)
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\t")
        assert editor.text == "/load-skills skill-a"
        assert editor.is_showing_autocomplete() is False

    async def test_ignores_invalid_slash_command_argument_completion_results(self) -> None:
        """editor.test.ts:2774. Upstream's invalid result is a non-array
        ``"not-an-array"`` returned from ``getArgumentCompletions``, guarded
        by ``CombinedAutocompleteProvider``'s own
        ``!Array.isArray(argumentSuggestions)`` check (autocomplete.ts:351).
        This port has no such inner/outer split (note 4), so the
        equivalent translation exercises the *same* defensive guard at the
        provider-boundary level directly: ``get_suggestions`` itself
        returns a non-list ``items`` value, and Editor must not crash or
        show a menu."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before = (lines[0] if lines else "")[:cursor_col]
            if before.startswith("/load-skills "):
                return "not-an-array", before[len("/load-skills ") :]  # deliberately invalid
            return [], ""

        # GREEN-phase pyright note: `get_suggestions` deliberately returns a
        # non-list `items` value (a real, runtime-only defensive case this
        # test exists to exercise, per the docstring above) — that's a
        # genuine mismatch against `GetSuggestionsFn`'s declared return
        # type, not a masked bug, so it's suppressed for just this one call.
        editor.set_autocomplete_provider(
            _Provider(get_suggestions),  # pyright: ignore[reportArgumentType]
            tui,
        )
        editor.set_text("/load-skills ")

        editor.handle_input("s")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is False
        assert editor.text == "/load-skills s"

    async def test_does_not_show_argument_completions_when_command_has_no_argument_completer(
        self,
    ) -> None:
        """editor.test.ts:2797. Stands in for
        ``CombinedAutocompleteProvider``'s command-name completion +
        slash-command ``applyCompletion`` branch (autocomplete.ts:308-337,
        391-405) — see ``_apply_slash_command_name`` and module docstring
        note 4."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before = (lines[0] if lines else "")[:cursor_col]
            if force or not before.startswith("/") or " " in before:
                return [], ""
            query = before[1:]
            commands = ["help", "model"]
            matches = [c for c in commands if c.startswith(query)]
            if not matches:
                return [], ""
            return [AutocompleteItem(value=c, label=c) for c in matches], before

        editor.set_autocomplete_provider(
            _Provider(get_suggestions, apply_completion=_apply_slash_command_name), tui
        )

        editor.handle_input("/")
        editor.handle_input("h")
        editor.handle_input("e")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\t")
        assert editor.text == "/help "
        assert editor.is_showing_autocomplete() is False


# =============================================================================
# This port's own extensions (task-13-brief.md: "浮层键改道、apply_completion
# 回写光标、Esc 关闭还焦、新键入作废旧请求 ... ≥8 条"). None of the 18 upstream
# cases above exercise these paths.
# =============================================================================


class TestAutocompleteKeyRerouting:
    async def test_menu_open_down_arrow_moves_selection_for_tab_apply(self) -> None:
        """None of the 18 ported cases ever press Up/Down while a menu is
        open — they only ever apply whichever item
        ``getBestAutocompleteMatchIndex`` already highlighted. The
        ``tui.select.down`` reroute (editor.ts:659-661, routed to
        ``this.autocompleteList.handleInput(data)``) is real, distinct
        behavior: this port's ``SelectList`` has no ``handle_input`` of its
        own (task-10 deviation 3 — the editor calls ``move_down()``/
        ``move_up()`` directly), so this test also pins down that the
        editor, not ``SelectList``, owns the key-to-movement translation.

        Converted (fix round 1) to drive input through ``tui.handle_input``
        — see ``_make_wired_tui``'s docstring: a real regression guard for
        the Critical-1 focus-stealing deadlock (arrows navigating an open
        menu is exactly the input that would have silently vanished)."""
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
                AutocompleteItem(value="three", label="three"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")  # force-Tab: opens the menu, "one" highlighted
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        assert editor.focused is True

        tui.handle_input("\x1b[B")  # Down -> "two"
        tui.handle_input("\x1b[B")  # Down -> "three"
        tui.handle_input("\t")  # Tab applies whatever is now selected

        assert editor.text == "three"
        assert editor.is_showing_autocomplete() is False

    async def test_menu_open_up_arrow_wraps_to_last_item(self) -> None:
        """``SelectList.move_up()`` wraps from index 0 to the last item
        (select-list.ts:115-118, ported per task-10). Pressing Up on a
        freshly-opened menu (selection at index 0) must reach the *last*
        item, not clamp or no-op.

        Converted (fix round 1) to drive input through ``tui.handle_input``
        — see ``_make_wired_tui``'s docstring."""
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
                AutocompleteItem(value="three", label="three"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        tui.handle_input("\x1b[A")  # Up from index 0 wraps to the last item
        tui.handle_input("\t")

        assert editor.text == "three"

    async def test_menu_open_escape_cancels_without_modifying_text(self) -> None:
        """Distinct from ported test 10 (backspacing a slash command to
        empty incidentally hides the menu) — this is a direct Esc-cancel
        on an otherwise-untouched buffer: editor.ts:654-657's
        ``tui.select.cancel`` reroute inside the "menu open" guard.

        Converted (fix round 1) to drive input through ``tui.handle_input``
        — see ``_make_wired_tui``'s docstring: Escape closing the menu is
        exactly the input path that used to deadlock once focus had been
        (wrongly) stolen onto the overlay."""
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        assert editor.focused is True

        tui.handle_input("\x1b")  # Escape
        assert editor.is_showing_autocomplete() is False
        assert editor.text == ""
        assert editor.focused is True, "closing the menu must leave the editor focused"

    async def test_apply_completion_writes_back_cursor_exactly(self) -> None:
        """None of the 18 ported cases assert ``editor.cursor`` after an
        autocomplete apply, only ``editor.text``. Since ``apply_completion``'s
        whole job (per the brief's ``-> tuple[list[str], int, int]``
        signature) is computing the *cursor*, not just the text, this
        checks that write-back explicitly on a mid-line completion."""
        tui = _make_tui()
        editor = Editor()
        editor.set_text("open Work please")
        editor.handle_input("\x01")  # Ctrl+A - start of line
        for _ in range(9):  # "open Work" is 9 characters
            editor.handle_input("\x1b[C")  # Right
        assert editor.cursor == (0, 9)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            text = lines[cursor_line] if cursor_line < len(lines) else ""
            prefix_text = text[:cursor_col]
            if prefix_text.endswith("Work"):
                return [AutocompleteItem(value="Workspace/", label="Workspace/")], "Work"
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("\t")
        await flush_autocomplete()

        assert editor.text == "open Workspace/ please"
        assert editor.cursor == (0, 15), (
            "cursor must land exactly after the inserted 'Workspace/' "
            "(len('open ') + len('Workspace/') == 15)"
        )

    async def test_enter_on_slash_command_name_menu_applies_then_falls_through_to_submit(
        self,
    ) -> None:
        """Real, distinct upstream behavior none of the 18 ported cases
        exercise: editor.ts:685-710's Enter/``tui.select.confirm`` handler
        applies the selected item, then — only if
        ``autocompletePrefix.startsWith("/")`` (a *command-name*
        completion, not an *argument* completion) — does NOT ``return``,
        so execution falls through to the ordinary Enter/submit handling
        below. Picking a slash command name via Enter both fills it in
        *and* submits the line."""
        tui = _make_tui()
        editor = Editor()
        submitted: list[str] = []
        editor.on_submit = submitted.append

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            before = (lines[0] if lines else "")[:cursor_col]
            if before == "/he":
                return [AutocompleteItem(value="/help", label="help")], before
            return [], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("/")
        editor.handle_input("h")
        editor.handle_input("e")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("\r")  # Enter

        assert editor.is_showing_autocomplete() is False
        assert editor.text == "", "submit clears the buffer back to a single empty line"
        assert submitted == ["/help"], "the applied text must have been handed to on_submit"

    async def test_new_keystroke_marks_stale_request_is_cancelled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direct coverage of the ``is_cancelled`` callable's own contract
        (task-13-brief.md "新键入作废旧请求（is_cancelled 早退）"), distinct
        from ported test 9's abort-side-effect-counter style: this test
        captures the *is_cancelled callable itself* and polls it directly,
        rather than inferring cancellation through a callback the mock
        provider chooses to invoke. Uses the debounce seam (module
        docstring note 3) to keep the "@" trigger's own debounce window
        short and bounded, since this test's focus is is_cancelled, not
        debounce timing."""
        monkeypatch.setattr(Editor, "AUTOCOMPLETE_DEBOUNCE_MS", 5)
        tui = _make_tui()
        editor = Editor()
        captured: list[Callable[[], bool]] = []

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            captured.append(is_cancelled)
            await asyncio.sleep(0.2)
            return [AutocompleteItem(value="@main.ts", label="main.ts")], "@main"

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("@")
        editor.handle_input("m")
        await asyncio.sleep(0.05)  # past the (patched) debounce window
        await flush_autocomplete()
        assert len(captured) >= 1
        first_is_cancelled = captured[0]
        assert first_is_cancelled() is False

        editor.handle_input("a")  # supersedes the in-flight request
        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert first_is_cancelled() is True, (
            "the superseded request's is_cancelled() must flip True once a "
            "new keystroke starts a fresh request"
        )

    async def test_escape_closes_open_menu_and_cancels_in_flight_requery(self) -> None:
        """Escape only reroutes through the autocomplete-cancel path while
        a menu is *already showing* (editor.ts:653's guard). This opens a
        menu first (force-Tab, always immediate), types one more character
        that kicks off a slow re-query (still in-flight, menu still
        showing the stale items), then presses Escape: the menu must close
        immediately (not wait for the slow re-query) and the stale
        re-query's ``is_cancelled()`` must flip True."""
        tui = _make_tui()
        editor = Editor()
        captured: list[Callable[[], bool]] = []
        calls = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal calls
            calls += 1
            if calls == 1:
                # force-Tab on an empty buffer: resolves immediately.
                return [
                    AutocompleteItem(value="one", label="one"),
                    AutocompleteItem(value="two", label="two"),
                ], ""
            # The re-query triggered by typing "o" below: slow, so it is
            # still in-flight when Escape is pressed.
            captured.append(is_cancelled)
            await asyncio.sleep(0.2)
            return [AutocompleteItem(value="one", label="one")], "o"

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("\t")  # force-Tab: opens the menu immediately
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        editor.handle_input("o")  # kicks off the slow re-query above
        await flush_autocomplete()
        assert len(captured) == 1, "typing while the menu is open must re-query"

        editor.handle_input("\x1b")  # Escape - must close the menu right away
        assert editor.is_showing_autocomplete() is False

        await asyncio.sleep(0.25)  # let the slow re-query actually finish
        assert captured[0]() is True, "the in-flight re-query must observe cancellation"

    async def test_provider_without_trigger_characters_attribute_uses_defaults(self) -> None:
        """``trigger_characters`` is optional per the brief's Produces list
        ("可选 trigger_characters: str") - a provider that never sets the
        attribute at all (not even an empty string) must still fall back
        to the default "@"/"#" triggers, mirroring upstream's
        ``provider.triggerCharacters ?? []`` default (editor.ts:373)."""
        tui = _make_tui()
        editor = Editor()
        calls = 0

        class _NoTriggerCharsProvider:
            apply_completion = staticmethod(apply_completion)

            async def get_suggestions(
                self, lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
            ):
                nonlocal calls
                calls += 1
                text = (lines[0] if lines else "")[:cursor_col]
                return [AutocompleteItem(value="@main.ts", label="main.ts")], text

        provider = _NoTriggerCharsProvider()
        assert not hasattr(provider, "trigger_characters")
        editor.set_autocomplete_provider(provider, tui)

        editor.handle_input("@")
        editor.handle_input("m")
        await asyncio.sleep(0.05)
        await flush_autocomplete()

        assert calls >= 1
        assert editor.is_showing_autocomplete() is True

    def test_autocomplete_item_is_the_select_item_alias(self) -> None:
        """Brief's Produces list: "AutocompleteItem (= SelectItem alias
        re-export)" - a literal identity, not merely a same-shape
        dataclass, so downstream code importing ``AutocompleteItem`` from
        either ``editor.py`` or ``select_list.py`` gets the exact same
        class object (``isinstance``-compatible both ways)."""
        from pipython.tui.components.select_list import SelectItem

        assert AutocompleteItem is SelectItem
        item = AutocompleteItem(value="x", label="y")
        assert item.value == "x"
        assert item.label == "y"
        assert item.description is None


class TestAutocompleteViaTuiHandleInput:
    """Fix round 1 (Critical finding 1) — RED-first regression coverage
    driving every step of the autocomplete lifecycle through
    ``tui.handle_input`` (the *real* production input path — a real
    ``TUI``'s own ``handle_input`` forwards to whatever it currently
    considers focused), never ``editor.handle_input`` directly.

    Before the fix, ``tui.show_overlay`` unconditionally stole TUI-level
    focus onto the autocomplete ``SelectList`` overlay the moment the menu
    opened. ``SelectList`` has no ``handle_input`` of its own (task-10
    deviation 3), so ``TUI.handle_input``'s ``getattr(component,
    "handle_input", None)`` probe found nothing callable and silently
    no-op'd — forever, since nothing ever moved focus back. Every one of
    the tests below (open the menu, assert the editor is still the
    focused component, navigate, apply, escape, and type through) fails
    at the ``assert editor.focused is True`` step (or hangs/no-ops on the
    next keystroke) against the pre-fix code, and is the reason none of
    the many pre-existing ``editor.handle_input``-driven tests in this
    file ever caught the bug: they bypass ``TUI`` entirely."""

    async def test_open_menu_via_tui_handle_input_keeps_editor_focused(self) -> None:
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="alpha", label="alpha"),
                AutocompleteItem(value="beta", label="beta"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")  # force-Tab, routed through the real TUI
        await flush_autocomplete()

        assert editor.is_showing_autocomplete() is True
        assert editor.focused is True, (
            "opening the autocomplete overlay must not steal focus from the editor"
        )

        tui.do_render()
        screen_text = "\n".join(term.screen())
        assert "alpha" in screen_text
        assert "beta" in screen_text

    async def test_escape_via_tui_handle_input_closes_menu_and_editor_stays_focused(self) -> None:
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="alpha", label="alpha"),
                AutocompleteItem(value="beta", label="beta"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        tui.handle_input("\x1b")  # Escape, via tui.handle_input
        assert editor.is_showing_autocomplete() is False
        assert editor.focused is True

    async def test_arrows_via_tui_handle_input_navigate_the_menu(self) -> None:
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
                AutocompleteItem(value="three", label="three"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        tui.handle_input("\x1b[B")  # Down -> "two"
        tui.handle_input("\x1b[B")  # Down -> "three"
        tui.handle_input("\x1b[A")  # Up -> "two"
        tui.handle_input("\t")  # Apply whatever is currently selected

        assert editor.text == "two"
        assert editor.is_showing_autocomplete() is False

    async def test_enter_via_tui_handle_input_applies_selection(self) -> None:
        editor = Editor()
        tui = _make_wired_tui(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        tui.handle_input("\x1b[B")  # Down -> "two"
        tui.handle_input("\r")  # Enter applies the highlighted item

        assert editor.text == "two"
        assert editor.is_showing_autocomplete() is False

    async def test_typing_via_tui_handle_input_requeries_the_menu(self) -> None:
        """editor.ts:1109-1139's "update or re-trigger autocomplete on
        further typing" path, driven through the real TUI: typing more
        characters while the menu is open must re-query the provider (not
        merely append to the buffer with a stale, unfiltered menu still
        showing) — and every one of these keystrokes has to actually reach
        the editor, which is exactly what a focus-stealing overlay would
        prevent."""
        editor = Editor()
        tui = _make_wired_tui(editor)
        query_log: list[str] = []

        all_files = [
            AutocompleteItem(value="readme.md", label="readme.md"),
            AutocompleteItem(value="requirements.txt", label="requirements.txt"),
            AutocompleteItem(value="src/", label="src/"),
        ]

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            should_match = force or prefix.startswith(".") or True
            query_log.append(prefix)
            if not should_match:
                return [], ""
            filtered = [f for f in all_files if f.value.startswith(prefix)]
            return (filtered, prefix) if filtered else ([], "")

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")  # force-Tab: opens the menu unfiltered
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        calls_after_open = len(query_log)

        tui.handle_input("r")
        await flush_autocomplete()
        assert editor.text == "r"
        assert editor.is_showing_autocomplete() is True
        assert len(query_log) > calls_after_open, "typing through tui.handle_input must re-query"

        tui.handle_input("e")
        await flush_autocomplete()
        assert editor.text == "re"
        assert editor.is_showing_autocomplete() is True

        tui.handle_input("\t")  # applies "readme.md" (the only remaining match)
        assert editor.text == "readme.md"
        assert editor.is_showing_autocomplete() is False


class TestAutocompleteOverlayIntegration:
    """task-13-brief.md: "触发时 tui.show_overlay(SelectList(...))" — real
    TUI + RecordingTerm, asserting menu visibility/content via ``screen()``
    and overlay close on Esc, per the job description's explicit
    instruction."""

    async def test_overlay_composites_menu_content_onto_real_tui_screen(self) -> None:
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="alpha.txt", label="alpha.txt"),
                AutocompleteItem(value="beta.txt", label="beta.txt"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)
        tui.do_render()  # initial frame, no menu yet

        editor.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        tui.do_render()
        screen_text = "\n".join(term.screen())
        assert "alpha.txt" in screen_text
        assert "beta.txt" in screen_text

    async def test_overlay_content_disappears_from_screen_after_escape(self) -> None:
        """Two suggestions, not one: a single force-Tab suggestion
        auto-applies without ever showing a menu at all (ported test 1),
        so this - like every other "menu stays open" scenario in this file
        - needs 2+ items to actually exercise the overlay."""
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="alpha.txt", label="alpha.txt"),
                AutocompleteItem(value="beta.txt", label="beta.txt"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)
        tui.do_render()

        editor.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        tui.do_render()
        assert "alpha.txt" in "\n".join(term.screen())

        editor.handle_input("\x1b")  # Escape
        assert editor.is_showing_autocomplete() is False

        tui.do_render()
        screen_text = "\n".join(term.screen())
        assert "alpha.txt" not in screen_text
        assert "beta.txt" not in screen_text

    async def test_overlay_content_disappears_from_screen_after_apply(self) -> None:
        """Same two-item setup as the Escape variant above. Checks that
        ``beta.txt`` (the item that was *not* applied - it only ever
        appears as menu chrome, never as editor text) is gone from the
        screen after applying ``alpha.txt`` - a check that can't
        accidentally pass "for the wrong reason" the way asserting
        ``"alpha.txt" not in screen`` could once the editor's own applied
        text legitimately contains that same string."""
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="alpha.txt", label="alpha.txt"),
                AutocompleteItem(value="beta.txt", label="beta.txt"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)
        tui.do_render()

        editor.handle_input("\t")  # opens the menu ("alpha.txt" highlighted)
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        tui.do_render()
        assert "beta.txt" in "\n".join(term.screen())

        editor.handle_input("\t")  # apply the highlighted item ("alpha.txt")
        assert editor.text == "alpha.txt"
        assert editor.is_showing_autocomplete() is False

        tui.do_render()
        assert "beta.txt" not in "\n".join(term.screen())

    async def test_overlay_does_not_steal_focus_and_editor_keeps_handling_input(self) -> None:
        """Fix round 1 (Critical finding 1) supersedes this test's original
        premise. The original version of this test asserted
        ``editor.focused is False`` while the menu was open, reasoning that
        ``tui.show_overlay`` "always steals TUI-level focus... this
        focus-steal/restore is a forced consequence of tui.py's existing,
        tested behavior — not a GREEN implementation choice." That reasoning
        was itself the bug: with focus stolen onto the passive
        ``SelectList`` overlay (which has no ``handle_input`` of its own),
        ``tui.handle_input`` forwards every subsequent keystroke to a
        component that cannot do anything with it — a real, permanent input
        deadlock in production the moment autocomplete opened, wholly
        invisible to every pre-fix-round-1 test in this file because they
        all drove input through ``editor.handle_input`` directly, bypassing
        ``tui.handle_input``'s focus dispatch entirely.

        Upstream itself never has this problem: its own ``autocompleteList``
        renders inline as part of the (always-focused) ``Editor``'s own
        component tree (editor.ts:578-581) — it is never a ``tui.show_overlay``
        overlay at all, so there is no separate "who has TUI focus" question
        to get wrong. This port's own choice to route the menu through
        ``tui.show_overlay`` (module docstring deviation 10) needs the
        equivalent of upstream's ``OverlayOptions.nonCapturing``
        (tui.ts:205-206) to reproduce that same "the editor is always the
        one actually handling input" invariant — which is exactly what
        ``show_overlay(..., non_capturing=True)`` now provides (see
        ``tui.py``'s ``show_overlay`` docstring and
        ``tests/tui/engine/test_overlay_focus.py``'s
        ``TestNonCapturingOverlay``)."""
        term = RecordingTerm()
        tui = TUI(term)
        editor = Editor()
        tui.set_root(editor)
        tui.set_focus(editor)
        assert editor.focused is True

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            return [
                AutocompleteItem(value="one", label="one"),
                AutocompleteItem(value="two", label="two"),
            ], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        tui.handle_input("\t")
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True
        assert editor.focused is True, (
            "the editor must keep TUI-level focus while its own autocomplete "
            "overlay is showing — a non-capturing overlay, per the fix"
        )

        # The real regression check: tui.handle_input must still actually
        # reach the editor while the menu is open (this is what a stolen-
        # focus deadlock would break) — navigate, then close via Escape.
        tui.handle_input("\x1b[B")  # Down -> "two"
        tui.handle_input("\x1b")  # Escape
        assert editor.is_showing_autocomplete() is False
        assert editor.focused is True, "the editor was never unfocused, so it stays focused"
        assert editor.text == "", "Escape must not have applied the selection"

        # And the editor must still be genuinely receiving input afterward.
        tui.handle_input("x")
        assert editor.text == "x"


class TestAutocompleteStalenessGuard:
    """Important finding 2 (fix round 1): port upstream's
    ``isAutocompleteRequestCurrent`` (editor.ts:2250-2264). A resolved
    autocomplete request must be discarded unless *both* the cancel token
    matches *and* the buffer's text/cursor are unchanged from the snapshot
    taken right before the (possibly slow) ``get_suggestions`` call — not
    just the token. The pre-fix code only checked the token
    (``if my_token != self._autocomplete_current_token: return``), so a
    keystroke that doesn't happen to match any trigger condition (and so
    never bumps the token) can still change the buffer while a request is
    in flight — the reviewer's concrete scenario: typing "src", pressing
    force-Tab (a slow provider starts resolving suggestions for "src"),
    then typing a non-trigger character ("!", which matches none of the
    default trigger/slash/word-char conditions) *before* the provider
    resolves. Without the text/cursor re-check, the stale "src" completion
    still gets applied once the provider finally resolves — but against
    the *current* buffer/cursor ("src!"), corrupting it: with only 1 char
    difference between prefix length (3) and the live cursor (4), the
    generic ``apply_completion`` prefix-strip helper used throughout this
    file computes ``before = line[: cursor_col - len(prefix)]`` = ``"s"``
    (one char of "src!", not the full "src") and ``after = line[cursor_col:]``
    = ``""``, yielding ``"s" + "src/" + "" == "ssrc/"`` — a real,
    reproducible data-corruption bug, not a hypothetical one."""

    async def test_stale_result_discarded_when_non_trigger_keystroke_changes_text_before_resolve(
        self,
    ) -> None:
        tui = _make_tui()
        editor = Editor()
        resolve_event = asyncio.Event()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            text = lines[0] if lines else ""
            prefix = text[:cursor_col]
            await resolve_event.wait()
            return [AutocompleteItem(value="src/", label="src/")], prefix

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        for ch in "src":
            editor.handle_input(ch)
        assert editor.text == "src"

        editor.handle_input("\t")  # force-Tab: starts the slow request for "src"
        await asyncio.sleep(0)  # let the task start and reach `await resolve_event.wait()`

        # "!" matches none of the default trigger characters ("@#"), the
        # slash-command-context check, or the word-char trigger pattern —
        # so it does NOT bump the cancel token, yet it does change the text
        # the in-flight request's eventual result would get applied against.
        editor.handle_input("!")
        assert editor.text == "src!"

        resolve_event.set()
        await flush_autocomplete()

        assert editor.text == "src!", (
            "the stale 'src' completion must be discarded, not applied onto "
            "the now-different 'src!' buffer (the 'ssrc/'-style corruption "
            "this staleness guard exists to prevent)"
        )
        assert editor.is_showing_autocomplete() is False

    async def test_stale_result_discarded_when_cursor_moves_before_resolve(self) -> None:
        """Same guard, but the text stays identical and only the *cursor*
        moves before the slow request resolves — upstream's
        ``isAutocompleteRequestCurrent`` checks cursor line/col in addition
        to (not instead of) the text, so this must be independently
        effective even when ``getText()`` alone wouldn't have caught it."""
        tui = _make_tui()
        editor = Editor()
        resolve_event = asyncio.Event()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            if not force:
                return [], ""
            await resolve_event.wait()
            return [AutocompleteItem(value="X", label="X")], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)
        editor.set_text("ab")
        editor.handle_input("\x01")  # Ctrl+A - start of line
        for _ in range(2):
            editor.handle_input("\x1b[C")  # Right, right -> cursor at (0, 2)
        assert editor.cursor == (0, 2)

        editor.handle_input("\t")  # force-Tab: slow request snapshotting cursor (0, 2)
        await asyncio.sleep(0)

        editor.handle_input("\x1b[D")  # Left: cursor moves to (0, 1), text unchanged
        assert editor.text == "ab"
        assert editor.cursor == (0, 1)

        resolve_event.set()
        await flush_autocomplete()

        assert editor.text == "ab", "a cursor-only change must also invalidate the stale result"
        assert editor.is_showing_autocomplete() is False


class TestAutocompleteTaskLifecycle:
    """Important finding 3 (fix round 1): ``_autocomplete_task`` is a real
    ``asyncio.Task`` (unlike upstream's fire-and-forget ``Promise`` chain,
    which has no equivalent concept of an unretrieved exception or a
    process-visible pending-task count) — a provider's own exception must
    not leak as an unhandled "Task exception was never retrieved" warning,
    and a request the user has fully abandoned (closed the menu / cleared
    the buffer) must not keep running forever in the background."""

    async def test_provider_exception_does_not_crash_editor(self) -> None:
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            raise RuntimeError("boom")

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("\t")  # force-Tab: the provider raises while resolving
        await flush_autocomplete()

        # The editor must still be fully usable after a provider blew up.
        assert editor.is_showing_autocomplete() is False
        editor.handle_input("x")
        assert editor.text == "x"

    async def test_provider_exception_is_retrieved_not_left_unhandled(self) -> None:
        """Distinct from the "doesn't crash" test above: a raising
        provider's exception must be *retrieved* (e.g. via a done-callback),
        not merely swallowed by the fact that nothing awaits the background
        task directly. Proving the negative (no leaked "exception was never
        retrieved" warning) requires the task to actually be garbage
        collected with nothing left holding it — keeping ``editor`` alive
        (as the "doesn't crash" test does, to prove continued usability)
        would keep a strong reference to the task via
        ``editor._autocomplete_task`` forever, so this test drops every
        reference to ``editor`` itself and forces a collection instead."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            raise RuntimeError("boom")

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        unhandled: list[dict] = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        try:
            editor.handle_input("\t")  # force-Tab: the provider raises while resolving
            await flush_autocomplete()
            del editor  # drop the only strong reference to the finished task
            gc.collect()
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        assert unhandled == [], f"provider exception leaked as unretrieved: {unhandled}"

    async def test_clearing_text_cancels_still_pending_non_cooperative_task(self) -> None:
        """A provider that never itself polls ``is_cancelled()`` at all is
        still a legitimate implementation (the Protocol only says
        ``is_cancelled`` *may* be consulted) — before this fix, such a
        provider's request task would keep running/sleeping in the
        background indefinitely once the user abandoned it (e.g. by
        clearing the buffer), invisible to ``asyncio.all_tasks()`` until it
        finally, coincidentally woke up on its own timer. ``set_text``
        already calls ``_cancel_autocomplete()`` (unchanged); this test
        pins down that doing so now also reclaims the task itself."""
        tui = _make_tui()
        editor = Editor()

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            await asyncio.sleep(10)  # deliberately never checks is_cancelled
            return [AutocompleteItem(value="x", label="x")], ""

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        baseline = len(asyncio.all_tasks())
        editor.handle_input("\t")  # force-Tab: starts the never-cooperating request
        await asyncio.sleep(0)
        assert len(asyncio.all_tasks()) == baseline + 1, "the request task must have started"

        editor.set_text("")  # abandon autocomplete entirely
        await asyncio.sleep(0)  # let the cancellation actually propagate

        assert len(asyncio.all_tasks()) == baseline, (
            "abandoning autocomplete must reclaim a still-pending request task "
            "even when the provider itself never observes is_cancelled()"
        )

    async def test_escape_cancels_still_pending_requery_task_that_never_polls_is_cancelled(
        self,
    ) -> None:
        """Same guarantee as above, but via the menu-open Escape path
        (``tui.select.cancel`` reroute) rather than ``set_text`` — the more
        common real-world "close the menu" trigger."""
        tui = _make_tui()
        editor = Editor()
        calls = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal calls
            calls += 1
            if calls == 1:
                return [
                    AutocompleteItem(value="one", label="one"),
                    AutocompleteItem(value="two", label="two"),
                ], ""
            await asyncio.sleep(10)  # deliberately never checks is_cancelled
            return [AutocompleteItem(value="one", label="one")], "o"

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("\t")  # force-Tab: resolves immediately, opens the menu
        await flush_autocomplete()
        assert editor.is_showing_autocomplete() is True

        baseline = len(asyncio.all_tasks())
        editor.handle_input("o")  # re-query while menu open: the never-cooperating request
        await asyncio.sleep(0)
        assert len(asyncio.all_tasks()) == baseline + 1

        editor.handle_input("\x1b")  # Escape: close the menu
        await asyncio.sleep(0)

        assert len(asyncio.all_tasks()) == baseline, (
            "Escape must reclaim the still-pending re-query task even though "
            "this provider never itself calls is_cancelled()"
        )

    async def test_new_trigger_does_not_disrupt_cooperative_is_cancelled_polling(self) -> None:
        """Guard-rail in the *other* direction: a well-behaved provider that
        DOES cooperatively poll ``is_cancelled()`` must still observe it and
        wind down on its own when superseded by a new keystroke — this
        fix must not force-cancel a task that is actively mid-flight inside
        a provider's own cooperative wait loop, which would race ahead of
        its own next ``is_cancelled()`` check and terminate it via
        ``CancelledError`` before it ever runs its own cleanup path (this
        is exactly the existing, already-green
        ``test_aborts_active_at_autocomplete_when_typing_continues`` case,
        re-asserted here as an explicit lifecycle-policy pin)."""
        tui = _make_tui()
        editor = Editor()
        aborts = 0

        async def get_suggestions(
            lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
        ):
            nonlocal aborts
            for _ in range(400):
                if is_cancelled():
                    aborts += 1
                    return [], ""
                await asyncio.sleep(0.005)
            return [AutocompleteItem(value="@main.ts", label="main.ts")], "@main"

        editor.set_autocomplete_provider(_Provider(get_suggestions), tui)

        editor.handle_input("@")
        editor.handle_input("m")
        editor.handle_input("a")
        editor.handle_input("i")
        await asyncio.sleep(0.25)
        editor.handle_input("n")  # supersedes the in-flight cooperative request
        await asyncio.sleep(0.05)

        assert aborts == 1, (
            "a cooperatively-cancelling provider must still get to run its own "
            "abort path — this fix's task.cancel() must only fire on "
            "cancel/close, never on an ordinary new-trigger supersede"
        )
