"""Undo state stack — Python port of upstream pi's
``packages/tui/src/undo-stack.ts`` (28 lines).

Upstream's ``UndoStack<S>`` is a plain stack: ``push(state)`` deep-clones
(``structuredClone``) and appends; ``pop()`` returns the most recent
snapshot (or ``undefined``); ``clear()``; ``length``. There is **no redo**
anywhere upstream — both consumers (``components/input.ts:339,343`` and
``components/editor.ts:1971,1976``) only ever call ``push``/``pop`` for a
single linear undo history; "redo" is not a concept in the TS codebase.

redo omitted — upstream has none; plan corrected. An earlier revision of
this port invented a ``redo()`` (conventional secondary-stack idiom) on the
strength of a task-brief line that turned out to be a hallucination (the
brief cited "merge policy per undo-stack.ts", but undo-stack.ts has no
merge policy — verified by reading the file). Code review proved the
invented ``redo()`` broken: calling ``redo()`` after ``undo()`` returned the
same popped value again on the *next* ``undo()`` instead of progressing,
because both stacks ended up holding the same snapshot. The plan
(``docs/superpowers/plans/2026-07-04-phase3-pi-tui-port.md``, Task 5
Produces) was corrected to match upstream exactly: ``push``/``undo``/
``clear`` only, no redo, no merge window. This module now mirrors that.

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
    """Plain stack of deep-cloned state snapshots (undo-stack.ts:1-28, no
    redo — see module docstring)."""

    def __init__(self) -> None:
        self._stack: list[S] = []

    def push(self, state: S) -> None:
        """Deep-clone ``state`` and push it. undo-stack.ts:11-13."""
        self._stack.append(copy.deepcopy(state))

    def undo(self) -> S | None:
        """Pop and return the most recent snapshot, or ``None`` if empty
        (upstream: ``pop()`` / ``undefined``, undo-stack.ts:16-18)."""
        if not self._stack:
            return None
        return self._stack.pop()

    def clear(self) -> None:
        """Remove all snapshots. undo-stack.ts:21-23."""
        self._stack.clear()

    def __len__(self) -> int:
        return len(self._stack)
