"""Autocomplete Provider group over ``engine.fuzzy`` (task-15).

Port of upstream ``autocomplete.ts``'s Provider *semantics* only — the
pt-prompt-toolkit-specific parts of ``completers.py`` (``PiCompleter``,
``Completion`` yielding) stay unported/unmodified, per this port's "旧 TUI
存活约束". This module supplies the async ``AutocompleteProvider`` Protocol
implementations (task-13, ``editor.py``) that Task 13's real ``Editor`` can
be wired up to via ``set_autocomplete_provider``:

- ``PathProvider`` — ``@`` fragment trigger (``completers.py``'s own,
  unmodified ``AT_FRAGMENT_RE``), async-bridged to any ``build_file_list``-
  shaped ``file_list`` callable, ``engine.fuzzy.fuzzy_filter`` ordering,
  upstream-style (``autocomplete.ts:107-121`` ``buildCompletionValue``)
  quoting for paths containing a space. **Issue #16 fix**: when no ``@``
  matches but the caller passes ``force=True`` (editor.py's explicit-Tab
  path), falls back to completing the bare non-whitespace word before the
  cursor — the completion value is then never ``@``-prefixed.
- ``CommandProvider`` — ``/`` trigger, reusing ``completers.py``'s
  ``PiCompleter.get_completions`` guard verbatim (single-line buffer
  starting with ``/``), sorted prefix filtering.
- ``CombinedProvider`` — first-matching-trigger-wins composition of any
  number of ``AutocompleteProvider``s, plus a ``trigger_characters`` union.

See ``tests/tui/components/test_autocomplete_providers.py``'s module
docstring for the design decisions this module implements (regex source,
fuzzy engine choice, quoting/cursor-math conventions, ``is_cancelled``
checkpoints, trigger priority).
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from pipython.tui.completers import AT_FRAGMENT_RE
from pipython.tui.engine.fuzzy import fuzzy_filter

from .editor import AutocompleteItem, AutocompleteProvider

__all__ = ["CombinedProvider", "CommandProvider", "PathProvider"]

# Bare-word fallback fragment: the longest run of non-whitespace characters
# immediately before the cursor (issue #16 — force-Tab on a typed-out path
# like "src/comp", with no leading "@", used to silently return nothing;
# see PathProvider.get_suggestions below). Deliberately simpler than
# upstream's ``extractPathPrefix``/``findLastDelimiter`` (which also treats
# quotes/"="/tabs as delimiters and special-cases "~/"): this only needs to
# cover the reported bug's shape (a plain relative/absolute path token), not
# reproduce every upstream delimiter nuance.
_BARE_WORD_RE = re.compile(r"(\S*)$")


def _quote_if_needed(path: str, *, at_prefix: bool = True) -> str:
    """autocomplete.ts:107-121 ``buildCompletionValue``, narrowed to this
    port's file-only (never-a-directory) ``file_list`` shape: quote iff the
    path contains a space. ``at_prefix`` controls whether the completion
    value is ``@``-prefixed — true for the ``@fragment`` trigger (this
    provider's original, only path until issue #16), false for the bare-word
    Tab fallback, which must never insert a literal "@" the user never
    typed."""
    prefix = "@" if at_prefix else ""
    if " " in path:
        return f'{prefix}"{path}"'
    return f"{prefix}{path}"


class PathProvider:
    """``@`` file-path completion, async-bridged to a ``build_file_list``-
    shaped source (``Callable[[], Awaitable[list[str]]]``)."""

    trigger_characters = "@"

    def __init__(self, file_list: Callable[[], Awaitable[list[str]]]) -> None:
        self._file_list = file_list

    async def get_suggestions(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> tuple[list[AutocompleteItem], str]:
        text = lines[cursor_line][:cursor_col]
        match = AT_FRAGMENT_RE.search(text)
        at_prefix = True
        if match:
            prefix = match.group(0)
            fragment = match.group(1)
        elif force:
            # issue #16: bare-word Tab (no "@") must still complete a file
            # path — fall back to the longest non-whitespace run before the
            # cursor as the fragment, only when the caller explicitly forced
            # completion (editor.py's explicit-Tab path,
            # ``_force_file_autocomplete(explicit_tab=True)``); a natural
            # (debounced) trigger still requires "@", matching
            # ``AT_FRAGMENT_RE``'s existing behavior above.
            bare_match = _BARE_WORD_RE.search(text)
            fragment = bare_match.group(1) if bare_match else ""
            if not fragment:
                return [], ""
            prefix = fragment
            at_prefix = False
        else:
            return [], ""

        # Checkpoint 1 (design note 4): never even start the (possibly
        # slow) file_list() fetch for an already-stale request.
        if is_cancelled():
            return [], ""

        files = await self._file_list()

        # Checkpoint 2: a request that went stale while the fetch was in
        # flight still discards its result instead of returning it.
        if is_cancelled():
            return [], ""

        candidates = fuzzy_filter(fragment, files)
        items = [
            AutocompleteItem(value=_quote_if_needed(path, at_prefix=at_prefix), label=path)
            for path in candidates
        ]
        return items, prefix

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> tuple[list[str], int, int]:
        line = lines[cursor_line]
        before = line[: cursor_col - len(prefix)]
        after = line[cursor_col:]
        # autocomplete.ts:407-415 (isDirectory/suffix) + :417-418,423
        # (cursorOffset/cursorCol), ported faithfully: upstream never adds a
        # trailing space after a directory-shaped item (so the user can keep
        # autocompleting deeper into that directory) but always adds one
        # after a file, and the cursor always lands right after that suffix.
        # This port's file_list never yields a directory entry
        # (completers.py:52-58, os.walk only ever appends files), so
        # is_directory is always False today and the space branch always
        # fires — the check is kept, unexercised by any real file_list today,
        # so a future directory-yielding file_list gets the right behavior
        # for free.
        is_directory = item.label.endswith("/")
        suffix = "" if is_directory else " "
        new_line = before + item.value + suffix + after
        new_lines = list(lines)
        new_lines[cursor_line] = new_line
        return new_lines, cursor_line, len(before) + len(item.value) + len(suffix)


class CommandProvider:
    """``/`` slash-command completion — reuses ``completers.py``'s
    ``PiCompleter.get_completions`` guard verbatim: triggers iff the
    **entire buffer** is a single line starting with ``/`` (not merely "the
    current line starts with /"). Deliberately has no ``trigger_characters``
    attribute at all (matching upstream: ``/`` is never a formal trigger
    character)."""

    def __init__(self, commands: dict[str, str]) -> None:
        self._commands = commands

    async def get_suggestions(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> tuple[list[AutocompleteItem], str]:
        if len(lines) != 1 or not lines[0].startswith("/"):
            return [], ""

        text_before_cursor = lines[0][:cursor_col]
        fragment = text_before_cursor[1:]

        matches = [
            (name, desc)
            for name, desc in sorted(self._commands.items())
            if name.startswith(fragment)
        ]
        if not matches:
            return [], ""

        items = [
            AutocompleteItem(value=name, label=name, description=desc or None)
            for name, desc in matches
        ]
        return items, text_before_cursor

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> tuple[list[str], int, int]:
        line = lines[cursor_line]
        before = line[: cursor_col - len(prefix)]
        after = line[cursor_col:]
        new_segment = f"/{item.value} "
        new_line = before + new_segment + after
        new_lines = list(lines)
        new_lines[cursor_line] = new_line
        return new_lines, cursor_line, len(before) + len(new_segment)


class CombinedProvider:
    """Composes several ``AutocompleteProvider``s: the first sub-provider
    whose ``get_suggestions`` returns a non-empty ``prefix`` wins (pure list
    order, not provider type); ``apply_completion`` routes to that same
    winning sub-provider, mirroring how Task 13's real ``Editor`` always
    calls ``apply_completion`` on the same provider instance immediately
    after that instance's own ``get_suggestions`` produced the prefix being
    applied. ``trigger_characters`` is the deduplicated, first-appearance-
    order union of every sub-provider's own
    ``getattr(p, "trigger_characters", "")``."""

    def __init__(self, providers: list[AutocompleteProvider]) -> None:
        self._providers = list(providers)
        self._last_winner: AutocompleteProvider | None = None

        seen: list[str] = []
        for provider in self._providers:
            for char in getattr(provider, "trigger_characters", ""):
                if char not in seen:
                    seen.append(char)
        self.trigger_characters = "".join(seen)

    async def get_suggestions(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> tuple[list[AutocompleteItem], str]:
        for provider in self._providers:
            items, prefix = await provider.get_suggestions(
                lines, cursor_line, cursor_col, force=force, is_cancelled=is_cancelled
            )
            if prefix:
                self._last_winner = provider
                return items, prefix
        return [], ""

    def apply_completion(
        self,
        lines: list[str],
        cursor_line: int,
        cursor_col: int,
        item: AutocompleteItem,
        prefix: str,
    ) -> tuple[list[str], int, int]:
        if self._last_winner is None:
            return lines, cursor_line, cursor_col
        return self._last_winner.apply_completion(lines, cursor_line, cursor_col, item, prefix)
