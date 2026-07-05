"""RecordingTerm — test double for TerminalIO implementing cursor/erase replay."""

from __future__ import annotations

import re

import pytest

from pipython.tui.engine.terminal import (
    HIDE_CURSOR,
    SHOW_CURSOR,
)
from pipython.tui.engine.tui import ERASE_LINE_FULL


class RecordingTerm:
    """TerminalIO protocol test double: records all write() calls and replays
    cursor movements/erases into a virtual line array for assertion.

    Attributes:
        ops: list[str] — every write() call's data, in order (for sequence
            assertions). Callers are free to ``.clear()`` this between
            renders to isolate "what did THIS render write" — doing so does
            *not* affect ``screen()`` (see below).
        columns: int — fixed to 80 (per brief).
        rows: int — fixed to 24 (per brief).
        flush_count: int — total number of ``flush()`` calls received (Task
            17 review, Important 1: ``TUI.do_render`` calls ``term.flush()``
            exactly once per frame, at the very end — this counter is how
            ``tests/tui/engine/test_diff_render.py`` verifies that without
            coupling to a particular real-``sys.stdout`` mock).

    Methods:
        screen() -> list[str] — returns the current virtual screen (a list
            of rendered lines), built up *incrementally* inside write()
            itself rather than replayed lazily from ``ops`` — see RED
            correction #1 below for why that distinction matters.

    RED correction #1 (citations: task-7-brief.md step 1 code block;
    tests/tui/engine/test_diff_render.py's ``test_growth_appends_without_clearing``
    / ``test_shrink_erases_tail_lines``, both of which do ``term.ops.clear()``
    then mutate+``do_render()`` then call ``screen()``):

    The original ``screen()`` (a) had no case for a bare newline / ``"\\r\\n"``
    advancing the cursor row, and (b) replayed lazily from ``self.ops`` on
    every call. Combined, these two facts made both tests above structurally
    unpassable by *any* correct differential-rendering implementation:
    a real diff renderer necessarily uses embedded ``"\\r\\n"`` to create a
    new terminal row for first-render / newly-appended lines (there is no
    "move to a row that doesn't exist yet" escape code — you can only get
    there by emitting an actual newline) exactly as upstream's own
    ``doRender`` does (``buffer += "\\r\\n"`` at tui.ts:1489, 1567). Since the
    old ``screen()`` didn't recognize ``"\\r\\n"`` as anything but stray text,
    every line piled onto row 0 — and since it replayed only from
    ``self.ops`` (which the two tests explicitly clear before their second
    ``do_render()``), the earlier render's lines were gone entirely from the
    replay, not just misplaced. ``test_shrink_erases_tail_lines`` in
    particular could never pass: a *correct* differential renderer does not
    rewrite unchanged rows 1-3 on the second render, yet the test (as
    written) required ``screen()`` — replayed only from the post-clear ops —
    to still show rows 1-3's content.

    Fixed by (1) recognizing ``"\\r\\n"``/``"\\n"`` as cursor_row-advancing and
    bare ``"\\r"`` as a no-op (this model tracks rows only, not columns), and
    (2) moving the replay state (``_lines``/``_cursor_row``) into persistent
    instance attributes updated incrementally by ``write()`` itself, so
    ``screen()`` reflects the full history of everything ever written,
    independent of whether ``.ops`` has since been cleared for op-sequence
    assertions.
    """

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.columns: int = 80
        self.rows: int = 24
        self.flush_count: int = 0
        self._lines: list[str] = ["" for _ in range(self.rows)]
        self._cursor_row: int = 0

    def write(self, data: str) -> None:
        """Record the write for op sequence assertions, and incrementally
        apply it to the persistent virtual screen (see RED correction #1)."""
        self.ops.append(data)
        self._apply(data)

    def flush(self) -> None:
        """Record a flush event (Task 17 review, Important 1). No screen
        effect — ``TerminalIO.flush`` is purely about when buffered bytes
        reach the real terminal, which this in-memory double has no
        buffering of in the first place."""
        self.flush_count += 1

    def _apply(self, op: str) -> None:
        """Apply a single write()'s data to the persistent virtual screen."""
        # Handle clear sequence (full screen clear + home + scrollback clear):
        # "\x1b[2J\x1b[H\x1b[3J" — reset all lines and move cursor home.
        # This is a composite sequence handled as a unit (Task 8 housekeeping).
        if op == "\x1b[2J\x1b[H\x1b[3J":
            self._lines = ["" for _ in range(self.rows)]
            self._cursor_row = 0
        # Handle move_to_row: CSI <n>B (down) or CSI <n>A (up)
        elif match := re.match(r"\x1b\[(\d+)B", op):
            delta = int(match.group(1))
            self._cursor_row = min(self._cursor_row + delta, self.rows - 1)
        elif match := re.match(r"\x1b\[(\d+)A", op):
            delta = int(match.group(1))
            self._cursor_row = max(self._cursor_row - delta, 0)
        # Handle newlines: real terminals (and this port's renderer) use a
        # literal newline — not a cursor-addressing escape — to advance onto
        # a row that doesn't exist on screen yet (first render, or newly
        # appended lines). See RED correction #1.
        elif op in ("\r\n", "\n"):
            self._cursor_row = min(self._cursor_row + 1, self.rows - 1)
        # Bare carriage return: column reset only; this model tracks rows,
        # not columns, so it's a no-op here.
        elif op == "\r":
            pass
        # Handle erase_line — doRender's own literal, ERASE_LINE_FULL =
        # "\x1b[2K" (tui.ts:1432/1508/1519/1564), NOT terminal.py's
        # CLEAR_LINE = "\x1b[K" (terminal.ts:493, a different call site:
        # RealTerminal.erase_line(), which tui.py never calls). Fix round 1:
        # this double previously matched against terminal.py's CLEAR_LINE,
        # which silently stopped matching once tui.py was corrected to write
        # its own upstream-faithful literal instead.
        elif op == ERASE_LINE_FULL:
            self._lines[self._cursor_row] = ""
        # Handle cursor visibility (no screen effect)
        elif op in (HIDE_CURSOR, SHOW_CURSOR):
            pass
        # Handle plain text writes (the actual rendered content)
        else:
            self._lines[self._cursor_row] += op

    def screen(self) -> list[str]:
        """Return a snapshot of the persistent virtual screen (list of
        ``rows`` lines), reflecting every write() call so far regardless of
        whether ``.ops`` has since been cleared (see RED correction #1)."""
        return list(self._lines)


@pytest.fixture
def term() -> RecordingTerm:
    """Fixture: a fresh RecordingTerm instance."""
    return RecordingTerm()
