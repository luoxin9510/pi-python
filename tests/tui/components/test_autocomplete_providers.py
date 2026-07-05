"""RED-phase tests for Task 15: autocomplete Provider group over ``engine.fuzzy``.

Target surface under test (task-15-brief.md's "Produces" list) — **does not
exist yet**, so every test in this file fails at collection
(``ModuleNotFoundError``) until GREEN adds
``src/pipython/tui/components/autocomplete.py``:

- ``PathProvider(file_list: Callable[[], Awaitable[list[str]]])`` — ``@``
  trigger, async bridge to a ``build_file_list``-shaped source
  (``completers.py``'s ``async def build_file_list(cwd, limit=...) ->
  list[str]``), ``engine.fuzzy`` filtering/ordering, upstream-style
  paths-with-spaces quoting.
- ``CommandProvider(commands: dict[str, str])`` — ``/`` trigger, line-start
  only, prefix filtering, descriptions carried into ``AutocompleteItem``.
- ``CombinedProvider(providers: list[AutocompleteProvider])`` — trigger
  priority (first matching provider wins) + ``trigger_characters`` union.

Both concrete providers, and ``CombinedProvider``, must structurally satisfy
Task 13's ``AutocompleteProvider`` Protocol
(``src/pipython/tui/components/editor.py``): ``async def get_suggestions(
lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False)
-> tuple[list[AutocompleteItem], str]`` and ``def apply_completion(lines,
cursor_line, cursor_col, item, prefix) -> tuple[list[str], int, int]``.
``AutocompleteItem`` is re-imported from ``editor.py`` (the ``SelectItem``
alias, task-13) rather than redefined here — same identity, per that
module's own re-export contract.

=============================================================================
Design decisions this RED suite locks in (cite before assuming a mismatch
is wrong — these are this port's concrete narrowing of the brief's terse
Produces line, derived from upstream + the existing, unmodified
``completers.py``):
=============================================================================

1. **PathProvider's "@" trigger pattern is ``completers.py``'s own
   ``AT_FRAGMENT_RE = re.compile(r"@([^\\s@]*)$")``** (completers.py:13),
   applied to ``lines[cursor_line][:cursor_col]`` (the current line only —
   the regex can never span a "\\n" anyway, since ``\\s`` excludes it from
   the captured fragment, so scoping to the current line is equivalent to
   scoping to the whole multi-line buffer's suffix). This is deliberately
   **not** Task 13 Editor's own ``_build_trigger_pattern`` (editor.py:416-421),
   which requires a preceding word boundary before the trigger char — the
   brief's "``@`` trigger anywhere in text" phrasing, and ``completers.py``'s
   existing precedent (``PiCompleter.get_completions``, completers.py:87-96,
   which never gates on a preceding boundary either), both point at the
   *unanchored* pattern. A bare "@" alone (no boundary requirement, no
   preceding-char check) always matches with an empty fragment.
2. **Fragment filtering/ordering is literally ``engine.fuzzy.fuzzy_filter``**
   (not the ``rapidfuzz``-based scoring ``completers.py``'s existing
   ``PiCompleter`` uses) — the brief's explicit "engine.fuzzy filtering/
   ordering" instruction. Tests that check ordering call ``fuzzy_filter``
   themselves and assert the provider's output matches it exactly, rather
   than hand-deriving expected scores — this pins the *engine* used, not a
   guessed score table. An empty fragment (bare "@") must return every
   candidate **unfiltered, in ``file_list``'s own order**
   (``fuzzy_filter``'s own contract — fuzzy.py:135-136: ``if not
   query.strip(): return items_list`` — no sort happens for an empty query).
3. **Quoting for paths containing a space follows upstream's
   ``buildCompletionValue``** (autocomplete.ts:107-121) narrowed to this
   port's file-only (never-a-directory) ``file_list`` shape: ``value = "@" +
   path`` when ``path`` has no space, else ``value = '@"' + path + '"'``
   (upstream's ``isAtPrefix`` + ``needsQuotes = isQuotedPrefix ||
   path.includes(" ")`` branches, autocomplete.ts:111-120, collapsed since
   this port's trigger never distinguishes an already-quoted typed prefix —
   not in the brief's Produces list). ``item.label`` is always the raw,
   unquoted, un-prefixed path (matching ``completers.py``'s own
   ``display_meta="file"`` convention of showing the plain path).
   ``apply_completion`` ports upstream's directory-vs-file trailing-space
   branch faithfully (autocomplete.ts:407-415 ``isDirectory``/``suffix``,
   :417-418/:423 ``cursorOffset``/``cursorCol``): ``suffix = "" if
   item.label.endswith("/") else " "``, and the cursor always lands right
   after that suffix (``len(before) + len(item.value) + len(suffix)``).
   Since ``build_file_list`` (and any conforming ``file_list`` source) only
   ever enumerates *files*, never directories (``completers.py``'s
   ``os.walk`` only appends ``files``, never a directory entry itself —
   completers.py:52-58), ``isDirectory`` is always ``False`` in practice
   today and the space-appending branch always fires — the check is kept,
   unexercised by any real ``file_list`` today, purely so a future
   directory-yielding ``file_list`` gets the right behavior for free.
4. **``is_cancelled`` is checked at two points**: once before ever awaiting
   the (possibly slow) ``file_list()`` source — so a request already known
   to be stale never starts the fetch at all — and once again immediately
   after it resolves, before fuzzy-filtering/building items — so a request
   that went stale *while the fetch was in flight* still discards its
   result instead of returning it. Both checkpoints are independently
   exercised below (the first via a source that must never even start; the
   second via a deterministic call-counting ``is_cancelled`` that is False
   on its first poll and True on its second, with no real timing race).
5. **CommandProvider's "/" trigger reuses ``completers.py``'s existing,
   unmodified guard exactly**: ``PiCompleter.get_completions``
   (completers.py:81) triggers slash completion iff
   ``document.text.startswith("/") and "\\n" not in document.text`` — i.e.
   the **entire buffer** is a single line starting with "/", not merely
   "the current line, wherever it is, starts with /". Translated to this
   port's ``lines``-list contract: ``"\\n".join(lines).startswith("/")`` and
   ``len(lines) == 1`` (equivalent to "no \\n in the buffer" once ``lines``
   is already the pre-split-on-"\\n" representation). This is why
   ``test_completers.py``'s existing ``test_slash_completion_suppressed_in_
   multiline`` case is translated 1:1 below (``TestCommandProviderTrigger.
   test_suppressed_in_multiline_buffer``) — a multi-line buffer suppresses
   "/" completion entirely, even when the cursor sits at column 0 of some
   later line. Fragment = ``text_before_cursor[1:]`` (everything after the
   leading "/", including any embedded space — matching
   ``PiCompleter``'s own ``frag = text[1:]``, completers.py:82, with no
   special-case for a space: a fragment containing a space naturally
   matches no command name via ``str.startswith``, so "no suggestions past
   the command name" falls out for free rather than needing an explicit
   guard).
6. **CombinedProvider's trigger priority is "first sub-provider whose
   ``get_suggestions`` returns a non-empty ``prefix`` wins"** — the winning
   sub-provider's ``(items, prefix)`` result is returned immediately,
   whether or not ``items`` itself is empty (an empty-items-but-nonempty-
   prefix result still means "this provider claims the context, just has
   nothing to suggest"). ``CombinedProvider`` remembers which sub-provider
   won the most recent ``get_suggestions`` call and routes the next
   ``apply_completion`` call to exactly that sub-provider — mirroring how
   Task 13's real ``Editor`` always calls ``apply_completion`` on the same
   provider instance immediately after that instance's own
   ``get_suggestions`` produced the ``prefix`` being applied
   (``editor.py``'s ``handle_key`` Tab/Enter branches, lines ~928-965: both
   call ``self._autocomplete_provider.apply_completion(..., self.
   _autocomplete_prefix)`` where ``self._autocomplete_provider`` is the
   single provider — possibly a ``CombinedProvider`` — configured via
   ``set_autocomplete_provider``). Every ``apply_completion`` test below
   therefore calls ``get_suggestions`` first, exactly as real usage would.
   ``trigger_characters`` is the **union** of every sub-provider's own
   ``getattr(p, "trigger_characters", "")``, deduplicated, order preserved
   by first appearance — a provider that never sets the attribute (e.g.
   ``CommandProvider``, whose "/" is deliberately never a formal trigger
   character, matching upstream's ``triggerCharacters?: string[]`` never
   including "/" either) contributes nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from pipython.tui.completers import build_file_list
from pipython.tui.components.autocomplete import (
    CombinedProvider,
    CommandProvider,
    PathProvider,
)
from pipython.tui.components.editor import AutocompleteItem
from pipython.tui.engine.fuzzy import fuzzy_filter

FileListFn = Callable[[], Awaitable[list[str]]]


def _files_fn(files: list[str]) -> FileListFn:
    """A trivial async ``file_list``-shaped source over an in-memory list —
    used wherever a test wants deterministic candidates without touching a
    real filesystem (the ordering/quoting/cursor-math unit tests). Real-fs
    integration is covered separately by ``TestPathProviderRealFsIntegration``
    (tmp_path trees, per repo convention: no mocked filesystem)."""

    async def _fn() -> list[str]:
        return files

    return _fn


# =============================================================================
# PathProvider — trigger detection ("@" anywhere in the current line's text
# before the cursor, completers.py's own AT_FRAGMENT_RE).
# =============================================================================


class TestPathProviderTrigger:
    async def test_no_at_symbol_returns_no_suggestions(self) -> None:
        provider = PathProvider(_files_fn(["readme.md"]))
        items, prefix = await provider.get_suggestions(["just plain text"], 0, 15)
        assert (items, prefix) == ([], "")

    async def test_at_anywhere_in_text_triggers_not_only_at_word_boundary(self) -> None:
        """Unlike Task 13 Editor's own ``_build_trigger_pattern`` (which
        requires a preceding whitespace/start-of-string boundary),
        PathProvider's own pattern (design note 1) has no such requirement —
        an "@" immediately after a non-space character still triggers."""
        provider = PathProvider(_files_fn(["readme.md"]))
        text = "seea@re"  # "@" immediately follows "a", no boundary before it
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@re"
        assert [i.label for i in items] == ["readme.md"]

    async def test_at_mid_sentence_with_trailing_words_still_triggers_on_final_token(
        self,
    ) -> None:
        provider = PathProvider(_files_fn(["readme.md", "other.txt"]))
        text = "please check @re"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@re"
        assert [i.label for i in items] == ["readme.md"]

    async def test_empty_fragment_after_bare_at_returns_all_files_unfiltered(self) -> None:
        """Design note 2: an empty query short-circuits ``fuzzy_filter`` to
        return every candidate in ``file_list``'s own order — deliberately
        unsorted here to prove no incidental sort happens."""
        provider = PathProvider(_files_fn(["b.txt", "a.txt", "c.txt"]))
        items, prefix = await provider.get_suggestions(["look at @"], 0, 9)
        assert prefix == "@"
        assert [i.label for i in items] == ["b.txt", "a.txt", "c.txt"]


# =============================================================================
# PathProvider — fuzzy ordering (design note 2: engine.fuzzy.fuzzy_filter,
# not rapidfuzz).
# =============================================================================


class TestPathProviderFuzzyOrdering:
    async def test_ordering_matches_engine_fuzzy_filter_exactly(self) -> None:
        files = ["src/main.py", "src/util.py", "srcfile.py", "other.py"]
        provider = PathProvider(_files_fn(files))
        expected = fuzzy_filter("src", files)
        assert expected, "fixture query must actually match something"

        text = "look at @src"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@src"
        assert [i.label for i in items] == expected


# =============================================================================
# PathProvider — upstream-style quoting for paths containing a space
# (design note 3, autocomplete.ts:107-121 buildCompletionValue).
# =============================================================================


class TestPathProviderQuoting:
    async def test_quotes_path_containing_a_space(self) -> None:
        provider = PathProvider(_files_fn(["my file.txt"]))
        text = "@my"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@my"
        assert len(items) == 1
        assert items[0].value == '@"my file.txt"'
        assert items[0].label == "my file.txt"

    async def test_no_quotes_for_path_without_a_space(self) -> None:
        provider = PathProvider(_files_fn(["readme.md"]))
        text = "@re"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert items[0].value == "@readme.md"
        assert items[0].label == "readme.md"


# =============================================================================
# PathProvider — apply_completion cursor/line math (design note 3: no added
# trailing space; exact multi-line write-back).
# =============================================================================


class TestPathProviderApplyCompletion:
    def test_apply_completion_single_line_cursor_lands_after_inserted_value(self) -> None:
        """autocomplete.ts:407-415/423: a non-directory item always gets a
        trailing space appended, and the cursor lands right after that
        space. The text already following the cursor here ("` please`")
        already had its own leading space, so upstream's unconditional
        append produces a double space — upstream never trims what's after
        the cursor, it only ever prepends."""
        provider = PathProvider(_files_fn([]))  # file_list unused by apply_completion
        item = AutocompleteItem(value="@readme.md", label="readme.md")
        lines = ["open @re please"]
        # cursor sits right after "@re" (index 8), prefix is "@re" (len 3)
        new_lines, cursor_line, cursor_col = provider.apply_completion(lines, 0, 8, item, "@re")
        assert new_lines == ["open @readme.md  please"]
        assert cursor_line == 0
        assert cursor_col == len("open @readme.md ")

    def test_apply_completion_multiline_buffer_exact_cursor_math(self) -> None:
        provider = PathProvider(_files_fn([]))
        item = AutocompleteItem(value="@readme.md", label="readme.md")
        lines = ["first line", "second @re line more", "third line"]
        # "second @re" -> before cursor length 10 ("second " is 7, "@re" is 3)
        new_lines, cursor_line, cursor_col = provider.apply_completion(lines, 1, 10, item, "@re")
        assert new_lines[0] == "first line", "untouched lines must survive verbatim"
        assert new_lines[1] == "second @readme.md  line more"
        assert new_lines[2] == "third line"
        assert cursor_line == 1
        assert cursor_col == len("second @readme.md ")

    def test_apply_completion_quoted_value_cursor_math(self) -> None:
        provider = PathProvider(_files_fn([]))
        item = AutocompleteItem(value='@"my file.txt"', label="my file.txt")
        lines = ["@my"]
        new_lines, cursor_line, cursor_col = provider.apply_completion(lines, 0, 3, item, "@my")
        assert new_lines == ['@"my file.txt" ']
        assert cursor_line == 0
        assert cursor_col == len('@"my file.txt" ')

    def test_apply_completion_directory_shaped_label_appends_no_space(self) -> None:
        """autocomplete.ts:407-415 ``isDirectory``/``suffix``: an item whose
        ``label`` ends with "/" gets no trailing space, so the user can keep
        autocompleting deeper into that directory. This port's own
        ``build_file_list`` never yields a directory entry
        (completers.py:52-58, ``os.walk`` only ever appends ``files``), so no
        real ``file_list`` source can trigger this branch today — this test
        exercises the ported check directly via a hand-built directory-shaped
        item, matching this class's existing pattern of constructing items by
        hand to unit-test ``apply_completion`` in isolation."""
        provider = PathProvider(_files_fn([]))  # file_list unused by apply_completion
        item = AutocompleteItem(value="@src/", label="src/")
        lines = ["@sr"]
        new_lines, cursor_line, cursor_col = provider.apply_completion(lines, 0, 3, item, "@sr")
        assert new_lines == ["@src/"]
        assert cursor_line == 0
        assert cursor_col == len("@src/")


# =============================================================================
# PathProvider — real filesystem integration (tmp_path; no mocked fs, per
# repo convention). The async file_list callable is a small real function
# bridging a real directory tree, including build_file_list itself.
# =============================================================================


class TestPathProviderRealFsIntegration:
    async def test_bridges_real_build_file_list_over_tmp_path(self, tmp_path: Path) -> None:
        """Uses the actual, unmodified ``completers.build_file_list`` (no
        git repo here, so it falls back to the pathspec walk) as the
        ``file_list``-shaped source — directly exercising the brief's
        "async bridge to build_file_list-shaped source" requirement."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "calculator.py").write_text("# calc\n")
        (tmp_path / "src" / "calibrate.py").write_text("# cal\n")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "junk.js").write_text("// junk\n")
        (tmp_path / ".gitignore").write_text("node_modules/\n")

        provider = PathProvider(lambda: build_file_list(tmp_path))

        text = "please look at @calc"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@calc"

        files = await build_file_list(tmp_path)
        expected = fuzzy_filter("calc", files)
        assert [i.label for i in items] == expected
        assert all("node_modules" not in i.label for i in items), (
            "gitignore-respecting build_file_list must keep node_modules/ out"
        )

    async def test_matches_nested_files_including_a_path_with_a_space(self, tmp_path: Path) -> None:
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "todo.md").write_text("- a\n")
        (tmp_path / "notes" / "my file.txt").write_text("hi\n")
        (tmp_path / "readme.md").write_text("# readme\n")

        async def real_file_list() -> list[str]:
            return sorted(
                str(p.relative_to(tmp_path)).replace("\\", "/")
                for p in tmp_path.rglob("*")
                if p.is_file()
            )

        provider = PathProvider(real_file_list)

        all_items, all_prefix = await provider.get_suggestions(["@"], 0, 1)
        assert all_prefix == "@"
        assert {i.label for i in all_items} == {
            "notes/todo.md",
            "notes/my file.txt",
            "readme.md",
        }

        text = "@notes/my"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert prefix == "@notes/my"
        assert len(items) == 1
        assert items[0].label == "notes/my file.txt"
        assert items[0].value == '@"notes/my file.txt"'


# =============================================================================
# PathProvider — bare-word Tab fallback (issue #16): a plain, non-"@"-
# prefixed path fragment before the cursor must still complete when the
# caller passes force=True (editor.py's explicit-Tab path,
# ``_force_file_autocomplete(explicit_tab=True)`` -> ``_request_autocomplete
# (force=True)`` -> provider.get_suggestions(..., force=True)). Before this
# fix, ``get_suggestions`` accepted ``force`` but never read it: no ``@``
# match meant an unconditional ``return [], ""``, silently swallowing every
# bare-word Tab press.
# =============================================================================


class TestPathProviderBareWordForceFallback:
    async def test_force_completes_bare_word_path_over_real_fs(self, tmp_path: Path) -> None:
        """Real tmp_path tree + real ``build_file_list`` (git-less, so the
        pathspec-walk fallback) — no mocked filesystem, per repo
        convention."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "comp1.py").write_text("# c1\n")
        (tmp_path / "src" / "comp2.py").write_text("# c2\n")
        (tmp_path / "other.py").write_text("# other\n")

        provider = PathProvider(lambda: build_file_list(tmp_path))

        text = "src/comp"
        items, prefix = await provider.get_suggestions([text], 0, len(text), force=True)

        assert prefix == "src/comp", "bare-word prefix must never carry a leading '@'"
        assert items, "must actually find the real files under tmp_path"
        labels = [i.label for i in items]
        assert all(label.startswith("src/comp") for label in labels)
        assert {"src/comp1.py", "src/comp2.py"} <= set(labels)
        assert all(not i.value.startswith("@") for i in items), (
            "bare-word completion values must never insert an '@' the user never typed"
        )

    async def test_no_at_and_no_force_still_returns_nothing(self) -> None:
        """A non-forced (debounced/natural) trigger must still require '@'
        — the bare-word fallback only fires for an explicit force=True Tab
        press, never for ordinary typing."""
        provider = PathProvider(_files_fn(["src/comp1.py", "src/comp2.py"]))
        text = "src/comp"
        items, prefix = await provider.get_suggestions([text], 0, len(text), force=False)
        assert (items, prefix) == ([], "")

    async def test_at_prefix_still_wins_over_bare_word_even_when_forced(self) -> None:
        """'@' takes priority: an explicit force=True Tab on text that DOES
        contain a well-formed '@fragment' must still go through the
        original '@' branch (value stays '@'-prefixed), never the bare-word
        fallback."""
        provider = PathProvider(_files_fn(["src/comp1.py"]))
        text = "@src/comp"
        items, prefix = await provider.get_suggestions([text], 0, len(text), force=True)
        assert prefix == "@src/comp"
        assert len(items) == 1
        assert items[0].value == "@src/comp1.py"

    def test_apply_completion_bare_word_round_trip_inserts_no_at_symbol(self) -> None:
        """Full round-trip: get_suggestions(force=True) on a bare word, then
        apply_completion with the winning item and prefix - the written-back
        line must contain the completed path with no stray '@'."""
        provider = PathProvider(_files_fn([]))  # file_list unused by apply_completion
        item = AutocompleteItem(value="src/comp1.py", label="src/comp1.py")
        lines = ["open src/comp"]
        # cursor sits right after "comp" (index 13), bare-word prefix is
        # "src/comp" (len 8, no leading '@' consumed)
        new_lines, cursor_line, cursor_col = provider.apply_completion(
            lines, 0, 13, item, "src/comp"
        )
        assert new_lines == ["open src/comp1.py "]
        assert cursor_line == 0
        assert cursor_col == len("open src/comp1.py ")

    async def test_force_with_empty_bare_fragment_returns_no_suggestions(self) -> None:
        """An empty bare-word fragment (cursor at start of an empty/blank
        line) is treated as "nothing to complete" rather than listing every
        file — deliberately narrower than upstream's ``extractPathPrefix``
        (which always returns, even an empty, prefix for a forced
        extraction): this port's provider contract has no ``None`` sentinel
        (module docstring note 1), so an empty string prefix here would be
        indistinguishable from "no match" to ``CombinedProvider`` (whose
        trigger-priority check is a truthiness test on ``prefix``, design
        note 6) - scoped out of this bugfix rather than silently
        miscompiling that composition."""
        provider = PathProvider(_files_fn(["readme.md"]))
        items, prefix = await provider.get_suggestions(["   "], 0, 3, force=True)
        assert (items, prefix) == ([], "")


# =============================================================================
# PathProvider — is_cancelled early-exit (design note 4: two checkpoints).
# =============================================================================


class TestPathProviderCancellation:
    async def test_is_cancelled_true_at_entry_never_awaits_the_slow_source(self) -> None:
        call_started = False

        async def slow_files() -> list[str]:
            nonlocal call_started
            call_started = True
            await asyncio.sleep(10)  # would hang the test if actually awaited
            return ["readme.md"]

        provider = PathProvider(slow_files)
        items, prefix = await asyncio.wait_for(
            provider.get_suggestions(["@re"], 0, 3, is_cancelled=lambda: True),
            timeout=0.5,
        )
        assert (items, prefix) == ([], "")
        assert call_started is False, "cancelled before the slow source is ever awaited"

    async def test_is_cancelled_rechecked_after_slow_source_resolves(self) -> None:
        """Deterministic (call-counting, no real timing race): False on the
        first poll (the entry check, design note 4's first checkpoint),
        True on the second (the post-fetch check) — proving both
        checkpoints exist, not just the entry one."""
        calls = 0

        def is_cancelled() -> bool:
            nonlocal calls
            calls += 1
            return calls > 1

        async def slow_files() -> list[str]:
            await asyncio.sleep(0.01)
            return ["readme.md"]

        provider = PathProvider(slow_files)
        items, prefix = await provider.get_suggestions(["@re"], 0, 3, is_cancelled=is_cancelled)
        assert (items, prefix) == ([], "")
        assert calls >= 2, "must poll is_cancelled again after the fetch resolves"


# =============================================================================
# CommandProvider — "/" trigger, line-start-of-single-line-buffer ONLY
# (design note 5: completers.py's existing, unmodified PiCompleter guard).
# =============================================================================


class TestCommandProviderTrigger:
    async def test_triggers_at_start_of_single_line_buffer(self) -> None:
        provider = CommandProvider({"model": "切换模型", "tree": "查看会话树"})
        items, prefix = await provider.get_suggestions(["/mo"], 0, 3)
        assert prefix == "/mo"
        assert [i.value for i in items] == ["model"]

    async def test_not_triggered_when_buffer_does_not_start_with_slash(self) -> None:
        provider = CommandProvider({"model": "切换模型"})
        text = "hello /mo"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert (items, prefix) == ([], ""), "仅行首 — a mid-text slash never triggers"

    async def test_suppressed_in_multiline_buffer(self) -> None:
        """Translation of test_completers.py's existing
        ``test_slash_completion_suppressed_in_multiline``: a multi-line
        buffer suppresses "/" completion entirely, even though the cursor
        sits at column 0... of line 0, right after "/model" — the guard is
        on the *whole buffer* being single-line, not "the current line
        happens to start with /"."""
        provider = CommandProvider({"model": "切换模型", "tree": "查看会话树"})
        lines = ["/model", "second line"]
        items, prefix = await provider.get_suggestions(lines, 0, 6)
        assert (items, prefix) == ([], "")


# =============================================================================
# CommandProvider — prefix filtering + descriptions (design note 5).
# =============================================================================


class TestCommandProviderFiltering:
    async def test_prefix_filters_and_sorts_commands(self) -> None:
        provider = CommandProvider(
            {"tree": "会话树", "help": "帮助", "hello": "打招呼", "model": "模型"}
        )
        items, prefix = await provider.get_suggestions(["/he"], 0, 3)
        assert prefix == "/he"
        assert [i.value for i in items] == ["hello", "help"], "sorted() order, per commands dict"

    async def test_descriptions_carried_into_autocomplete_items(self) -> None:
        provider = CommandProvider({"model": "Change the active model"})
        items, prefix = await provider.get_suggestions(["/mo"], 0, 3)
        assert len(items) == 1
        assert items[0].value == "model"
        assert items[0].label == "model"
        assert items[0].description == "Change the active model"

    async def test_no_prefix_matches_returns_empty(self) -> None:
        provider = CommandProvider({"model": "切换模型"})
        items, prefix = await provider.get_suggestions(["/zzz"], 0, 4)
        assert (items, prefix) == ([], "")

    async def test_fragment_with_embedded_space_matches_nothing(self) -> None:
        """Design note 5: no explicit "stop at first space" guard is needed
        — a fragment containing a space (e.g. after a full command name plus
        an argument) naturally fails every ``str.startswith`` prefix check."""
        provider = CommandProvider({"model": "切换模型"})
        text = "/model gpt-4o"
        items, prefix = await provider.get_suggestions([text], 0, len(text))
        assert (items, prefix) == ([], "")


# =============================================================================
# CommandProvider — apply_completion (name + trailing space, cursor math).
# =============================================================================


class TestCommandProviderApplyCompletion:
    def test_apply_completion_inserts_slash_name_with_trailing_space_and_cursor_math(
        self,
    ) -> None:
        provider = CommandProvider({"help": "Show help"})
        item = AutocompleteItem(value="help", label="help", description="Show help")
        lines = ["/he"]
        new_lines, cursor_line, cursor_col = provider.apply_completion(lines, 0, 3, item, "/he")
        assert new_lines == ["/help "]
        assert cursor_line == 0
        assert cursor_col == len("/help ")


# =============================================================================
# CombinedProvider — trigger priority (design note 6: first non-empty-prefix
# result wins, purely by list order — not by provider type).
# =============================================================================


class _AlwaysMatchesProvider:
    """Minimal duck-typed ``AutocompleteProvider`` stand-in: always claims
    the trigger context regardless of input, tagging its result so tests can
    tell which instance actually won."""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def get_suggestions(
        self, lines, cursor_line, cursor_col, *, force=False, is_cancelled=lambda: False
    ):
        return [AutocompleteItem(value=self.tag, label=self.tag)], "match"

    def apply_completion(self, lines, cursor_line, cursor_col, item, prefix):
        return lines, cursor_line, cursor_col


class TestCombinedProviderTriggerPriority:
    async def test_first_matching_provider_wins_regardless_of_type(self) -> None:
        first = _AlwaysMatchesProvider("first")
        second = _AlwaysMatchesProvider("second")
        combined = CombinedProvider([first, second])

        items, prefix = await combined.get_suggestions(["x"], 0, 1)
        assert prefix == "match"
        assert [i.value for i in items] == ["first"], "second must never be consulted"

    async def test_reversed_order_flips_the_winner(self) -> None:
        first = _AlwaysMatchesProvider("first")
        second = _AlwaysMatchesProvider("second")
        combined = CombinedProvider([second, first])

        items, prefix = await combined.get_suggestions(["x"], 0, 1)
        assert [i.value for i in items] == ["second"], "priority is pure list order"

    async def test_trigger_characters_union_deduped_order_preserved(self) -> None:
        class _P:
            trigger_characters = "@"

        class _Q:
            trigger_characters = "@#"

        combined = CombinedProvider([_P(), _Q()])  # type: ignore[list-item]
        assert combined.trigger_characters == "@#"

    async def test_command_provider_contributes_nothing_to_trigger_union(self) -> None:
        """CommandProvider deliberately has no ``trigger_characters``
        attribute at all (design note 6 / note 5: "/" is never a formal
        trigger character, matching upstream)."""
        assert not hasattr(CommandProvider({}), "trigger_characters")

        path_provider = PathProvider(_files_fn([]))
        combined = CombinedProvider([path_provider, CommandProvider({})])
        assert combined.trigger_characters == "@"


# =============================================================================
# CombinedProvider — routing real PathProvider/CommandProvider instances,
# get_suggestions -> apply_completion in the same real-usage sequence Task
# 13's Editor itself uses (design note 6).
# =============================================================================


class TestCombinedProviderRouting:
    async def test_at_trigger_routes_to_path_provider(self) -> None:
        path_provider = PathProvider(_files_fn(["readme.md"]))
        command_provider = CommandProvider({"help": "Show help"})
        combined = CombinedProvider([path_provider, command_provider])

        text = "look @re"
        items, prefix = await combined.get_suggestions([text], 0, len(text))
        assert prefix == "@re"
        assert items[0].value == "@readme.md"

        new_lines, cursor_line, cursor_col = combined.apply_completion(
            [text], 0, len(text), items[0], prefix
        )
        assert new_lines == ["look @readme.md "]
        assert cursor_line == 0
        assert cursor_col == len("look @readme.md ")

    async def test_slash_trigger_routes_to_command_provider(self) -> None:
        path_provider = PathProvider(_files_fn(["readme.md"]))
        command_provider = CommandProvider({"help": "Show help"})
        combined = CombinedProvider([path_provider, command_provider])

        items, prefix = await combined.get_suggestions(["/he"], 0, 3)
        assert prefix == "/he"
        assert items[0].value == "help"

        new_lines, cursor_line, cursor_col = combined.apply_completion(
            ["/he"], 0, 3, items[0], prefix
        )
        assert new_lines == ["/help "]
        assert cursor_line == 0
        assert cursor_col == len("/help ")

    async def test_no_provider_matches_returns_empty_items_and_prefix(self) -> None:
        path_provider = PathProvider(_files_fn(["readme.md"]))
        command_provider = CommandProvider({"help": "Show help"})
        combined = CombinedProvider([path_provider, command_provider])

        items, prefix = await combined.get_suggestions(["plain text, no trigger"], 0, 10)
        assert (items, prefix) == ([], "")

    async def test_forwards_is_cancelled_to_the_matched_sub_provider(self) -> None:
        """CombinedProvider must thread the exact ``is_cancelled`` callable
        through to whichever sub-provider ends up handling the request —
        not swallow or replace it — so a slow PathProvider fetch behind a
        CombinedProvider is still cancellable (design note 4's contract
        must survive composition)."""
        call_started = False

        async def slow_files() -> list[str]:
            nonlocal call_started
            call_started = True
            await asyncio.sleep(10)
            return ["readme.md"]

        combined = CombinedProvider([PathProvider(slow_files), CommandProvider({})])

        items, prefix = await asyncio.wait_for(
            combined.get_suggestions(["@re"], 0, 3, is_cancelled=lambda: True),
            timeout=0.5,
        )
        assert (items, prefix) == ([], "")
        assert call_started is False
