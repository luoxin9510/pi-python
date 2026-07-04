"""Emacs-style kill/yank ring — Python port of upstream pi's
``packages/tui/src/kill-ring.ts`` (46 lines).

Upstream's ``KillRing`` exposes ``push(text, { prepend, accumulate })``,
``peek()``, and ``rotate()``. Per task-5 brief's Produces interface, this
port renames the surface to ``kill(text, prepend, accumulate=False)``,
``yank()``, and ``yank_pop()`` — the *behavior* (ring contents, accumulate/
prepend semantics, rotation order) is copied verbatim from kill-ring.ts:19-41;
only the method names differ to match the brief.

- ``kill(text, prepend, accumulate=False)`` == upstream ``push`` (kill-ring.ts:19-28):
  empty text is a no-op; ``accumulate=True`` merges into the most recent
  entry (``prepend=True`` -> ``text + last``, for backward deletion;
  ``prepend=False`` -> ``last + text``, for forward deletion) instead of
  pushing a new entry.
- ``yank()`` == upstream ``peek()`` (kill-ring.ts:31-33): most recent entry,
  read-only; ``None`` on an empty ring (upstream: ``undefined``).
- ``yank_pop()`` == upstream ``rotate()`` (kill-ring.ts:36-41) — moves the
  last entry to the front — followed by returning the new ``yank()`` value,
  so callers get the newly-cycled-to entry directly.
"""

from __future__ import annotations

__all__ = ["KillRing"]


class KillRing:
    """Ring buffer of killed (deleted) text entries."""

    def __init__(self) -> None:
        self._ring: list[str] = []

    def kill(self, text: str, prepend: bool, accumulate: bool = False) -> None:
        """Add ``text`` to the ring. kill-ring.ts:19-28."""
        if not text:
            return

        if accumulate and self._ring:
            last = self._ring.pop()
            self._ring.append(text + last if prepend else last + text)
        else:
            self._ring.append(text)

    def yank(self) -> str | None:
        """Most recent entry, or ``None`` if the ring is empty. kill-ring.ts:31-33."""
        return self._ring[-1] if self._ring else None

    def yank_pop(self) -> str | None:
        """Rotate (move last entry to front) and return the newly current
        entry. kill-ring.ts:36-41."""
        if len(self._ring) > 1:
            last = self._ring.pop()
            self._ring.insert(0, last)
        return self.yank()

    def __len__(self) -> int:
        return len(self._ring)
