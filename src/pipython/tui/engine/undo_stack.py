"""Undo/redo state stack — Python port of upstream pi's
``packages/tui/src/undo-stack.ts`` (28 lines).

Upstream's ``UndoStack<S>`` is a plain stack: ``push(state)`` deep-clones
(``structuredClone``) and appends; ``pop()`` returns the most recent
snapshot (or ``undefined``); ``clear()``; ``length``. There is **no redo**
anywhere upstream — both consumers (``components/input.ts:339,343`` and
``components/editor.ts:1971,1976``) only ever call ``push``/``pop`` for a
single linear undo history; "redo" is not a concept in the TS codebase.

Task-5 brief's Produces interface nonetheless calls for
``push(state)``/``undo() -> state | None``/``redo()``, citing "合并策略照
undo-stack.ts" (merge policy per undo-stack.ts) — but undo-stack.ts has no
merge policy to copy (verified by reading the file: it is exactly the plain
stack described above). Since the RED suite (``test_undo_stack.py`` /
``TestUndoStack`` in ``test_editor_support.py``) never calls ``redo()`` or
exercises a merge window either, there is no test-derived contract to
satisfy for it. This port implements ``redo()`` via the conventional
secondary-stack pattern (an editor-standard idiom, not an upstream port):
``push`` clears the redo history (a fresh edit invalidates any pending
redo), ``undo`` moves the popped snapshot onto the redo stack, ``redo`` pops
it back onto the undo stack. ``undo()``'s own behavior — LIFO pop order,
``None`` on empty, deep-clone-on-push isolation — is exactly upstream's
``pop()`` and is what every RED test actually exercises.

Deep cloning: Python has no ``structuredClone``; ``copy.deepcopy`` is the
closest equivalent (handles nested dict/list/tuple state, matching the RED
suite's nested-structure-cloning test) and is used on every ``push``.
"""

from __future__ import annotations

import copy
from typing import Generic, TypeVar

__all__ = ["UndoStack"]

S = TypeVar("S")


class UndoStack(Generic[S]):
    """Stack of deep-cloned state snapshots, with a conventional redo stack
    layered on top (see module docstring — no upstream equivalent)."""

    def __init__(self) -> None:
        self._stack: list[S] = []
        self._redo: list[S] = []

    def push(self, state: S) -> None:
        """Deep-clone ``state`` and push it. undo-stack.ts:11-13. Clears any
        pending redo history (new edit invalidates it)."""
        self._stack.append(copy.deepcopy(state))
        self._redo.clear()

    def undo(self) -> S | None:
        """Pop and return the most recent snapshot, or ``None`` if empty
        (upstream: ``pop()`` / ``undefined``, undo-stack.ts:16-18)."""
        if not self._stack:
            return None
        state = self._stack.pop()
        self._redo.append(state)
        return state

    def redo(self) -> S | None:
        """Pop and return the most recently undone snapshot, or ``None`` if
        there is nothing to redo. No upstream equivalent — see module
        docstring."""
        if not self._redo:
            return None
        state = self._redo.pop()
        self._stack.append(state)
        return state

    def clear(self) -> None:
        """Remove all snapshots, undo and redo alike. undo-stack.ts:21-23."""
        self._stack.clear()
        self._redo.clear()

    def __len__(self) -> int:
        return len(self._stack)
