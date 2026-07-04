"""Editor component — Python port of upstream pi's
``packages/tui/src/components/editor.ts`` (2307 lines).

Task-11 narrowed this component to buffer model, cursor, character
insert/delete, arrow/word/line movement, character jump (Ctrl+]/Ctrl+Alt+]),
sticky-column vertical movement, and soft-wrap rendering with an embedded
``CURSOR_MARKER``. **Task 12 (this revision) adds**: Emacs-style kill-ring
(Ctrl+W/Ctrl+U/Ctrl+K kill, Ctrl+Y/Alt+Y yank/yank-pop), linear undo
(Ctrl+-), prompt history navigation (Up/Down arrow browsing with draft
preservation), and large-paste marker folding (``[paste #N +M lines]``)
with atomic-segment treatment for cursor movement/deletion/word-movement
and ``get_expanded_text()`` for marker expansion at submit time.

Interface (binding, per task-11 + task-12 briefs):

- ``Editor(bindings: KeyBindings = DEFAULT_EDITOR_BINDINGS, on_submit:
  Callable[[str], None] | None = None)`` — satisfies task-7's ``Component``
  (``render``/``invalidate``) and ``Focusable`` (``focused: bool``)
  contracts.
- ``text: str`` / ``cursor: tuple[int, int]`` (line, grapheme column) state
  accessors; ``set_text(s)``.
- ``handle_input(data: str) -> None`` — the outer entry point (the TUI
  forwards raw frames here): detects a bracketed-paste frame (markers
  preserved, per ``stdin_buffer.py``'s single-channel contract) and routes
  it to ``handle_paste``; otherwise parses the frame with Task 4's
  ``parse_key`` and routes the result to ``handle_key``.
- ``handle_key(e: KeyEvent) -> None`` — internal but public (kept so a
  caller, e.g. a future task's test, can drive actions without frame
  encoding). Character insert, backspace/delete (atomic-segment aware),
  arrow movement (with sticky column), word movement (Ctrl+Left/Right et
  al., atomic-segment aware), line start/end (Home/End, Ctrl+A/E),
  character jump, the backslash+Enter newline workaround, ``newLine``,
  ``submit``, kill-ring (Ctrl+W/Ctrl+U/Ctrl+K/Ctrl+Y/Alt+Y), undo
  (Ctrl+-), and prompt history (Up/Down).
- ``handle_paste(text: str) -> None`` — filters control characters, folds
  large pastes (>10 lines or >1000 chars) into a ``[paste #N +M lines]`` /
  ``[paste #N M chars]`` marker (editor.ts:1183-1198), and pushes exactly
  one undo snapshot (single undo unit for the whole paste, editor.ts:1147).
- ``history: list[str]`` (most-recent-first) / ``add_history(s: str) ->
  None`` (editor.ts:381-391 ``addToHistory``) — the caller is responsible
  for invoking ``add_history`` after a successful submit; this port does
  not call it automatically (upstream doesn't either).
- ``get_expanded_text() -> str`` (editor.ts:986-988 ``getExpandedText``) —
  ``text`` with every paste marker substituted back to its original
  pasted content. ``on_submit`` is always called with the *expanded* text
  (editor.ts:1248 ``submitValue``), never the raw marker string.
- ``render(width: int) -> list[str]`` — soft-wrapped visual lines framed by
  a plain top/bottom border line (``"─" * width``, no theme/color — this
  port's ``Editor`` takes no ``tui``/``theme`` constructor argument, see
  deviation 1); embeds ``CURSOR_MARKER`` at the cursor's grapheme position
  when ``focused`` is true (task-7's ``CURSOR_MARKER``).

Consumes: Task 4 (``KeyEvent``/``parse_key``/``key_id``), Task 5
(``KeyBindings``/``DEFAULT_EDITOR_BINDINGS``, ``KillRing``, ``UndoStack``),
Task 1 (``visible_width``/``graphemes``), Task 7 (``CURSOR_MARKER``), and
the already-ported ``word_left``/``word_right`` (word-navigation.ts,
task-5 brief).

Deviations from upstream editor.ts:

1. **No ``tui``/``theme``/``options`` constructor parameters** (editor.ts
   ``constructor(tui: TUI, theme: EditorTheme, options: EditorOptions =
   {})``) — per the task-11 brief's narrower ``Editor(bindings, on_submit)``
   signature. Consequently: no ``paddingX`` (always 0 — every render reserves
   exactly 1 column for the cursor, matching upstream's ``paddingX === 0``
   branch, editor.ts:471), no border *color* (the border is the literal
   ``"─"`` repeated — upstream's ``theme.borderColor`` callback has nothing
   to plug into here), and no vertical scrolling (``scrollOffset``/
   ``maxVisibleLines`` derive from ``tui.terminal.rows``, which does not
   exist on this component at all — every layout line is always rendered).
2. **Cursor column is a plain Python string index into the logical line**,
   which this port treats as upstream's UTF-16-code-unit ``cursorCol``
   would for anything wider than one code unit: since Python strings are
   codepoint arrays (an astral character like "😀" is *one* Python index
   position, not a UTF-16 surrogate pair) and every movement/deletion
   operation below always advances by whole grapheme-cluster (or, for
   paste markers, whole-marker) boundaries, the cursor index is always
   left sitting at such a boundary — i.e. it *is* "the grapheme column"
   the brief specifies, without needing a separate grapheme-index
   bookkeeping layer distinct from the string index.
3. **Vertical-movement atomic-segment snapping is ported**
   (editor.ts:1372-1412, ``snappedFromCursorCol``) as of the task-12
   fix-round-2 pass. Task 11 originally deferred this pending paste-marker
   support, and task 12's initial GREEN phase left it unported since no RED
   test drove a paste marker across a vertical (up/down) move — that gap
   was in fact a data-loss bug: a sticky column could land the cursor
   *inside* a paste marker (e.g. sticky col 10 landing inside a marker
   starting at col 6), and the next keystroke there would split the
   marker's text, breaking ``_PASTE_MARKER_RE``'s match and silently
   losing the original pasted content at submit (``get_expanded_text()``
   would return the broken literal instead of expanding it). ``_move_to_
   visual_line`` now (a) resolves the pre-move visual column against
   ``_snapped_from_cursor_col`` when a previous vertical move left the
   cursor sitting at a segment start (so sticky-column tracking survives
   the snap), and (b) after computing the raw target column, snaps it to
   the start of any atomic segment (paste marker) it would otherwise land
   inside — skipping past multi-visual-line marker continuations when
   moving down through an already-visited segment, exactly as upstream.
4. **``word_wrap_line`` (promoted from task-11's private ``_word_wrap_line``
   to a public name matching upstream's exported ``wordWrapLine``) gains an
   optional ``pre_segmented`` parameter** (editor.ts's third ``wordWrapLine``
   argument) so paste markers can be wrapped as atomic units instead of
   being split at arbitrary character boundaries. A private alias
   ``_word_wrap_line = word_wrap_line`` is kept so the existing 10-plus
   precision tests in ``test_editor_core.py`` (which import the private
   name directly, calling it with 2 positional args) need no changes: the
   new parameter defaults to ``None`` and degrades to the previous
   plain-grapheme-segmentation behavior. ``Editor._segment_with_markers``
   computes the atomic-aware segment list (editor.ts's ``segmentWithMarkers``,
   folded into this port's index-carrying grapheme-segment representation)
   from ``self._pastes``' *valid* IDs only — a line containing marker-shaped
   text with no matching entry in ``self._pastes`` (e.g. a manually typed
   ``"[paste #99 +5 lines]"``) is never merged, matching upstream's
   ``validPasteIds()`` gate.
5. **Word-boundary movement (Ctrl+Left/Right et al.) still uses the
   already-ported ``word_left``/``word_right``** (``engine/word_navigation.py``,
   task-5) as its fallback, but is now wrapped by
   ``_word_left_with_markers``/``_word_right_with_markers``: before
   delegating, these check whether a *valid* paste marker starts (forward)
   or ends (backward) at the position reached after skipping whitespace,
   and if so jump over the whole marker in one step — this reproduces
   upstream's ``findWordBackward``/``findWordForward`` ``isAtomicSegment``
   parameter (word-navigation.ts) without modifying that shared module
   (out of this task's file scope), since the atomic check only ever
   short-circuits when a real paste marker is present; plain text is
   dispatched to the unmodified ``word_left``/``word_right`` exactly as
   task 11 left it.
6. **``onChange`` callback, ``disableSubmit``, and
   ``getLines``/``getCursor``/``getText`` accessor *methods* are not
   ported** — the task-11 brief's Produces list exposes ``text``/``cursor``
   as plain read-only properties and only ``on_submit`` as a callback; none
   of the translated tests exercise ``onChange`` or ``disableSubmit``.
   ``getExpandedText`` *is* ported (task-12 brief, ``get_expanded_text()``).
7. **``handle_input`` calls ``parse_key(data, kitty=False)`` with the Kitty
   channel hardcoded off** — the task-11 brief's ``handle_input(data)``
   signature carries no kitty-enabled parameter (this component, per
   deviation 1, holds no ``tui``/terminal reference to read one from).
   Upstream instead consults a module-level ``_kittyProtocolActive`` flag
   (keys.ts:25-40) that a real terminal's keyboard-protocol negotiation
   flips at runtime. This is a **known limitation, not a design choice**:
   Kitty CSI-u–encoded keys are always parsed as if Kitty mode were
   disabled until a future task threads a live capability flag through —
   the natural checkpoint is Task 16, where ``RealTerminal.kitty_enabled``
   (``engine/terminal.py``) must be wired into this call (and into the
   TUI's dispatch to ``handle_input`` generally) so this hardcoded
   ``False`` can be replaced with the negotiated value. (Note: the Kitty
   CSI-u *parser itself* is not gated by this flag — ``\x1b[45;5u`` for
   Ctrl+- still parses correctly regardless — only a couple of legacy
   ambiguous 2-byte sequences depend on it; see keys.py.)
8. **``_submit_value`` resets ``_preferred_visual_col`` (and, since the
   task-12-fix-round-2 vertical-snap port, ``_snapped_from_cursor_col``)
   to ``None``**, which upstream's ``submitValue`` (editor.ts:1246-1259)
   does not do — deliberate, not an oversight: submit clears the buffer
   back to a single empty line, and leaving a stale sticky-column value in
   place would let it leak into subsequent up/down navigation on that
   fresh empty buffer (``_compute_vertical_move_column``/
   ``_move_to_visual_line`` treat a non-``None`` value as "the user has an
   intentional preferred column / pre-snap position to restore"). Resetting
   both here is a narrow behavioral improvement over upstream rather than a
   compatibility gap.
9. **``handle_paste`` does not port** the CSI-u Ctrl+letter re-decoding
   (editor.ts:1154-1159, a tmux-popup compatibility shim), the file-path
   leading-space heuristic (editor.ts:1170-1178), or autocomplete
   suppression during paste (autocomplete itself is Task 13's territory) —
   none of these are in the task-12 brief's Produces list or exercised by
   its RED suite; only control-character filtering, line-ending/tab
   normalization, and the large-paste marker-folding threshold are ported.

RED corrections (task-12 GREEN phase): see task-12-report.md for the one
correction applied to ``tests/tui/components/test_editor_killring_undo_history.py``
(``TestPasteMarkerAtomicBehavior.test_paste_is_single_undo_unit`` — the
original assertion sequence was inconsistent with ``UndoStack``'s plain
LIFO full-state-snapshot semantics, per undo-stack.ts / editor.ts:1970-1984;
corrected to the sequence a faithful port actually produces).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import regex

from ..engine.keybindings import DEFAULT_EDITOR_BINDINGS, KeyBindings
from ..engine.keys import KeyEvent, key_id, parse_key
from ..engine.kill_ring import KillRing
from ..engine.tui import CURSOR_MARKER
from ..engine.undo_stack import UndoStack
from ..engine.utils import graphemes, visible_width
from ..engine.word_navigation import word_left, word_right

__all__ = ["Editor", "word_wrap_line"]

# =============================================================================
# Bracketed-paste markers (stdin_buffer.py's single-channel contract: a whole
# paste frame arrives through handle_input with both markers preserved).
# =============================================================================

_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"

# Large-paste marker regex (editor.ts:22 PASTE_MARKER_REGEX): "[paste #1
# +123 lines]" or "[paste #2 1234 chars]". Uses stdlib `re` (not the `regex`
# package imported below for CJK detection) — no Unicode-property features
# are needed here, just a plain ASCII pattern with a numeric capture group.
_PASTE_MARKER_RE = re.compile(r"\[paste #(\d+)(?: (?:\+\d+ lines|\d+ chars))?\]")

# CJK break detection for word-wrap (editor.ts's imported `cjkBreakRegex`,
# utils.ts:48). Duplicated locally rather than imported from
# ``engine/utils.py`` because that module's equivalent (`_CJK_BREAK_RE`) is
# a private, module-internal constant there (task-1's own scope) — not part
# of this port's public utils surface.
_CJK_BREAK_RE = regex.compile(
    r"[\p{Script_Extensions=Han}\p{Script_Extensions=Hiragana}"
    r"\p{Script_Extensions=Katakana}\p{Script_Extensions=Hangul}"
    r"\p{Script_Extensions=Bopomofo}]",
    regex.V1,
)


def _is_cjk_break(s: str) -> bool:
    return bool(_CJK_BREAK_RE.search(s))


def _grapheme_len_at_start(s: str) -> int:
    """Length (in Python string index units) of the first grapheme cluster
    of ``s``, or 1 if ``s`` is empty (defensive fallback, mirrors upstream's
    ``graphemes[0]?.segment.length ?? 1``)."""
    if not s:
        return 1
    clusters = graphemes(s)
    return len(clusters[0]) if clusters else 1


def _grapheme_len_at_end(s: str) -> int:
    """Length of the last grapheme cluster of ``s``, or 1 if empty."""
    if not s:
        return 1
    clusters = graphemes(s)
    return len(clusters[-1]) if clusters else 1


# =============================================================================
# Word wrap (editor.ts:93-206 TextChunk / wordWrapLine)
# =============================================================================


@dataclass
class _Chunk:
    text: str
    start: int
    end: int


def _grapheme_segments(text: str) -> list[tuple[str, int]]:
    """``[(grapheme, start_index), ...]`` for ``text`` — the index-carrying
    equivalent of upstream's ``Intl.Segmenter`` output (``SegmentData`` has
    both ``.segment`` and ``.index``; ``graphemes()`` here only returns
    cluster text, so the cumulative index is reconstructed)."""
    segments: list[tuple[str, int]] = []
    idx = 0
    for g in graphemes(text):
        segments.append((g, idx))
        idx += len(g)
    return segments


def word_wrap_line(
    line: str,
    max_width: int,
    pre_segmented: list[tuple[str, int]] | None = None,
) -> list[_Chunk]:
    """Split ``line`` into word-wrapped chunks, each at most ``max_width``
    visible columns. Ported from editor.ts:114-206 ``wordWrapLine``.

    ``pre_segmented`` (editor.ts's third ``wordWrapLine`` argument) is an
    optional ``[(segment_text, start_index), ...]`` list to use instead of
    the default plain-grapheme segmentation — this is how a caller (see
    ``Editor._segment_with_markers``) makes paste markers wrap as atomic
    units. When omitted (the common case, and every call from
    ``test_editor_core.py``'s precision-test suite), behavior is identical
    to task-11's private ``_word_wrap_line``.
    """
    if not line or max_width <= 0:
        return [_Chunk("", 0, 0)]

    if visible_width(line) <= max_width:
        return [_Chunk(line, 0, len(line))]

    chunks: list[_Chunk] = []
    segments = pre_segmented if pre_segmented is not None else _grapheme_segments(line)

    current_width = 0
    chunk_start = 0

    # Wrap opportunity: the position after the last whitespace before a
    # non-whitespace grapheme, i.e. where a line break is allowed.
    wrap_opp_index = -1
    wrap_opp_width = 0

    for i, (grapheme, char_index) in enumerate(segments):
        g_width = visible_width(grapheme)
        is_ws = grapheme.isspace()

        if current_width + g_width > max_width:
            if wrap_opp_index >= 0 and current_width - wrap_opp_width + g_width <= max_width:
                chunks.append(_Chunk(line[chunk_start:wrap_opp_index], chunk_start, wrap_opp_index))
                chunk_start = wrap_opp_index
                current_width -= wrap_opp_width
            elif chunk_start < char_index:
                chunks.append(_Chunk(line[chunk_start:char_index], chunk_start, char_index))
                chunk_start = char_index
                current_width = 0
            wrap_opp_index = -1

        if g_width > max_width:
            # Single segment (grapheme or atomic paste marker) wider than
            # max_width: re-wrap it at grapheme granularity for visual
            # purposes only — it remains one logical unit to every other
            # operation (cursor movement, deletion, ...).
            sub_chunks = word_wrap_line(grapheme, max_width)
            for sc in sub_chunks[:-1]:
                chunks.append(_Chunk(sc.text, char_index + sc.start, char_index + sc.end))
            last = sub_chunks[-1]
            chunk_start = char_index + last.start
            current_width = visible_width(last.text)
            wrap_opp_index = -1
            continue

        current_width += g_width

        next_seg = segments[i + 1] if i + 1 < len(segments) else None
        if is_ws and next_seg is not None and not next_seg[0].isspace():
            wrap_opp_index = next_seg[1]
            wrap_opp_width = current_width
        elif not is_ws and next_seg is not None and not next_seg[0].isspace():
            if _is_cjk_break(grapheme) or _is_cjk_break(next_seg[0]):
                wrap_opp_index = next_seg[1]
                wrap_opp_width = current_width

    chunks.append(_Chunk(line[chunk_start:], chunk_start, len(line)))
    return chunks


# Private alias — task-11's precision word-wrap tests (test_editor_core.py)
# import this name directly; see module docstring deviation 4.
_word_wrap_line = word_wrap_line


# =============================================================================
# Layout (editor.ts:215-219 LayoutLine, 881-967 layoutText)
# =============================================================================


@dataclass
class _LayoutLine:
    text: str
    has_cursor: bool
    cursor_pos: int | None = None


# A visual line: (logical_line_index, start_col_in_logical_line, length).
_VisualLine = tuple[int, int, int]


# =============================================================================
# Undo snapshot (editor.ts's EditorState — lines/cursorLine/cursorCol)
# =============================================================================


@dataclass
class _EditorSnapshot:
    lines: list[str] = field(default_factory=lambda: [""])
    cursor_line: int = 0
    cursor_col: int = 0


# =============================================================================
# Editor
# =============================================================================

_DEFAULT_BINDINGS = KeyBindings(DEFAULT_EDITOR_BINDINGS)


class Editor:
    """task-7 ``Component``/``Focusable``-compatible text editor: buffer
    model, cursor, editing, kill-ring/undo/history, paste-marker folding,
    soft-wrapped rendering. See module docstring for full scope and
    deviations."""

    def __init__(
        self,
        bindings: KeyBindings = _DEFAULT_BINDINGS,
        on_submit: Callable[[str], None] | None = None,
    ) -> None:
        self.bindings = bindings
        self.on_submit = on_submit

        self.focused: bool = False

        self._lines: list[str] = [""]
        self._cursor_line: int = 0
        self._cursor_col: int = 0

        # Store last render width for cursor navigation (editor.ts:267).
        self._last_width: int = 80

        # Preferred visual column for vertical cursor movement (sticky
        # column), editor.ts:311.
        self._preferred_visual_col: int | None = None

        # Pre-snap cursor column: when a vertical move snaps the cursor to
        # the start of an atomic segment (a paste marker), this remembers
        # where the cursor *would* have landed, so the next vertical move
        # can resolve the correct visual column against the VL it actually
        # belongs to — even after a resize reshuffles VLs (editor.ts:318
        # ``snappedFromCursorCol``).
        self._snapped_from_cursor_col: int | None = None

        # Character jump mode (Ctrl+]/Ctrl+Alt+]), editor.ts:308.
        self._jump_mode: str | None = None

        # Prompt history (editor.ts:298-301). `history` is public per the
        # task-12 brief; `_history_index`/`_history_draft` are the browsing
        # cursor and the draft snapshot captured on first entering browsing
        # mode (both editor.ts-private).
        self.history: list[str] = []
        self._history_index: int = -1  # -1 = not browsing, 0 = most recent, ...
        self._history_draft: _EditorSnapshot | None = None

        # Kill ring + last-action coalescing tag (editor.ts:304-305).
        # "kill" | "yank" | "type-word" | None.
        self._kill_ring: KillRing = KillRing()
        self._last_action: str | None = None

        # Undo stack (editor.ts:320-321). No redo — see undo_stack.py.
        self._undo_stack: UndoStack[_EditorSnapshot] = UndoStack()

        # Large-paste tracking (editor.ts:290-292): paste id -> original
        # (pre-folding) pasted content, so get_expanded_text() can restore
        # it and so atomic-segment checks can validate a marker's id.
        self._pastes: dict[int, str] = {}
        self._paste_counter: int = 0

    # -- public state accessors (editor.ts:969-996) --------------------

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    @property
    def cursor(self) -> tuple[int, int]:
        return (self._cursor_line, self._cursor_col)

    def set_text(self, text: str) -> None:
        """editor.ts:998-1008 ``setText``: exits history browsing, resets
        undo coalescing, and pushes an undo snapshot iff the content
        actually changes (making programmatic changes undoable)."""
        self._last_action = None
        self._exit_history_browsing()
        normalized = self._normalize_text(text)
        if self.text != normalized:
            self._push_undo_snapshot()
        self._set_text_internal(normalized, "end")

    def _set_text_internal(self, text: str, cursor_placement: str = "end") -> None:
        """editor.ts:447-458 ``setTextInternal`` — does not touch history
        state or undo (callers, e.g. ``_navigate_history``, manage those
        themselves)."""
        lines = text.split("\n")
        self._lines = lines if lines else [""]
        if cursor_placement == "start":
            self._cursor_line = 0
            self._set_cursor_col(0)
        else:
            self._cursor_line = len(self._lines) - 1
            self._set_cursor_col(len(self._lines[self._cursor_line]))

    def add_history(self, text: str) -> None:
        """editor.ts:381-391 ``addToHistory``. Not called automatically by
        submit — the caller invokes this after a successful submission."""
        trimmed = text.strip()
        if not trimmed:
            return
        if self.history and self.history[0] == trimmed:
            return
        self.history.insert(0, trimmed)
        if len(self.history) > 100:
            self.history.pop()

    def get_expanded_text(self) -> str:
        """editor.ts:986-988 ``getExpandedText`` — ``text`` with every
        paste marker substituted back to its original content."""
        return self._expand_paste_markers(self.text)

    def _expand_paste_markers(self, text: str) -> str:
        """editor.ts:973-980 ``expandPasteMarkers``."""
        result = text
        for paste_id, content in self._pastes.items():
            marker_re = re.compile(rf"\[paste #{paste_id}(?: (?:\+\d+ lines|\d+ chars))?\]")
            result = marker_re.sub(lambda _m, content=content: content, result)
        return result

    # -- Component contract (task-7) ------------------------------------

    def invalidate(self) -> None:
        """No cached render state to invalidate (upstream has none either,
        editor.ts:460-462)."""

    def render(self, width: int) -> list[str]:
        content_width = max(1, width)
        # Reserve 1 column for the cursor (no padding in this port — see
        # module docstring deviation 1).
        layout_width = max(1, content_width - 1)
        self._last_width = layout_width

        border = "─" * width

        layout_lines = self._layout_text(layout_width)

        result: list[str] = [border]

        emit_cursor_marker = self.focused

        for ll in layout_lines:
            display_text = ll.text
            line_visible_width = visible_width(ll.text)

            if ll.has_cursor and ll.cursor_pos is not None:
                before = display_text[: ll.cursor_pos]
                after = display_text[ll.cursor_pos :]
                marker = CURSOR_MARKER if emit_cursor_marker else ""

                if after:
                    after_graphemes = graphemes(after)
                    first_grapheme = after_graphemes[0] if after_graphemes else ""
                    rest_after = after[len(first_grapheme) :]
                    cursor = f"\x1b[7m{first_grapheme}\x1b[0m"
                    display_text = before + marker + cursor + rest_after
                else:
                    cursor = "\x1b[7m \x1b[0m"
                    display_text = before + marker + cursor
                    line_visible_width += 1

            padding = " " * max(0, content_width - line_visible_width)
            result.append(display_text + padding)

        result.append(border)
        return result

    # -- input dispatch (editor.ts:591-879 handleInput) ------------------

    def handle_input(self, data: str) -> None:
        if not data:
            return

        # Character-jump mode: the next frame is the jump target (which may
        # be any literal character, including non-ASCII — hence resolved
        # here at the raw-frame level rather than solely via KeyEvent.text;
        # see handle_key's docstring for why parse_key alone cannot carry
        # arbitrary Unicode literals).
        if self._jump_mode is not None:
            e = parse_key(data, kitty=False)
            cancels = e is not None and (
                self.bindings.matches(key_id(e), "tui.editor.jumpForward")
                or self.bindings.matches(key_id(e), "tui.editor.jumpBackward")
            )
            if cancels:
                self._jump_mode = None
                return

            if e is not None and e.text is not None:
                target: str | None = e.text
            elif ord(data[0]) >= 32:
                target = data
            else:
                target = None

            if target is not None:
                direction = self._jump_mode
                self._jump_mode = None
                self._jump_to_char(target, direction)
                return

            # Control character: cancel jump mode and fall through to
            # process this frame normally (e.g. Escape), editor.ts:611-613.
            self._jump_mode = None

        if data.startswith(_PASTE_START) and data.endswith(_PASTE_END):
            self.handle_paste(data[len(_PASTE_START) : -len(_PASTE_END)])
            return

        # Bare LF (also Ctrl+J's raw byte, 0x0A): upstream special-cases a
        # standalone "\n" frame to always add a newline rather than submit
        # (editor.ts:780 `data === "\n" && data.length === 1`), since once
        # parsed it is indistinguishable from a bare Enter ("\r") frame —
        # Task 4's parse_key maps both to the same `KeyEvent(name="enter")`
        # (non-kitty branch, keys.py:520).
        if data == "\n":
            self._add_new_line()
            return

        e = parse_key(data, kitty=False)
        if e is not None:
            self.handle_key(e)
            return

        # parse_key (Task 4 scope) only recognizes ASCII/control/escape
        # frames; a literal — possibly multi-byte/astral — Unicode
        # character typed directly ("ä", "中", "😀") reaches here as a
        # single decoded Python character with no KeyEvent representation.
        # Mirrors upstream's own final fallback (editor.ts:876-878
        # `if (data.charCodeAt(0) >= 32) this.insertCharacter(data)`).
        if ord(data[0]) >= 32:
            self._insert_character(data)

    def handle_key(self, e: KeyEvent) -> None:
        """Internal action dispatch (kept public per the task-11 brief, so
        a caller can drive actions directly, bypassing frame encoding).

        Character-jump-mode *consumption* lives in ``handle_input`` instead
        of here (not duplicated) because a jump target can be an arbitrary
        Unicode literal that ``parse_key`` does not turn into a
        ``KeyEvent`` at all (see ``handle_input``) — by the time
        ``handle_key`` runs, jump mode is guaranteed already resolved.
        """
        kb = self.bindings
        kid = key_id(e)

        if kb.matches(kid, "tui.input.copy"):
            # Ctrl+C: parent's job (exit/clear) — nothing to do here.
            return

        if kb.matches(kid, "tui.editor.undo"):
            self._undo()
            return

        if kb.matches(kid, "tui.editor.deleteToLineEnd"):
            self._delete_to_end_of_line()
            return
        if kb.matches(kid, "tui.editor.deleteToLineStart"):
            self._delete_to_start_of_line()
            return
        if kb.matches(kid, "tui.editor.deleteWordBackward"):
            self._delete_word_backward()
            return
        if kb.matches(kid, "tui.editor.deleteWordForward"):
            self._delete_word_forward()
            return

        if kb.matches(kid, "tui.editor.deleteCharBackward") or kid == "shift+backspace":
            self._handle_backspace()
            return
        if kb.matches(kid, "tui.editor.deleteCharForward") or kid == "shift+delete":
            self._handle_forward_delete()
            return

        if kb.matches(kid, "tui.editor.yank"):
            self._yank()
            return
        if kb.matches(kid, "tui.editor.yankPop"):
            self._yank_pop()
            return

        if kb.matches(kid, "tui.editor.cursorLineStart"):
            self._move_to_line_start()
            return
        if kb.matches(kid, "tui.editor.cursorLineEnd"):
            self._move_to_line_end()
            return
        if kb.matches(kid, "tui.editor.cursorWordLeft"):
            self._move_word_backwards()
            return
        if kb.matches(kid, "tui.editor.cursorWordRight"):
            self._move_word_forwards()
            return

        if kb.matches(kid, "tui.input.newLine"):
            self._add_new_line()
            return

        if kb.matches(kid, "tui.input.submit"):
            current_line = self._lines[self._cursor_line]
            # Workaround for terminals without Shift+Enter support: if the
            # char before the cursor is '\', delete it and insert a newline
            # instead of submitting (editor.ts:791-806).
            if self._cursor_col > 0 and current_line[self._cursor_col - 1] == "\\":
                self._handle_backspace()
                self._add_new_line()
                return
            self._submit_value()
            return

        if kb.matches(kid, "tui.editor.cursorUp"):
            if self._is_on_first_visual_line() and (
                self._is_editor_empty() or self._history_index > -1 or self._cursor_col == 0
            ):
                self._navigate_history(-1)
            elif self._is_on_first_visual_line():
                self._move_to_line_start()
            else:
                self._move_cursor(-1, 0)
            return
        if kb.matches(kid, "tui.editor.cursorDown"):
            if self._history_index > -1 and self._is_on_last_visual_line():
                self._navigate_history(1)
            elif self._is_on_last_visual_line():
                self._move_to_line_end()
            else:
                self._move_cursor(1, 0)
            return
        if kb.matches(kid, "tui.editor.cursorRight"):
            self._move_cursor(0, 1)
            return
        if kb.matches(kid, "tui.editor.cursorLeft"):
            self._move_cursor(0, -1)
            return

        if kb.matches(kid, "tui.editor.jumpForward"):
            self._jump_mode = "forward"
            return
        if kb.matches(kid, "tui.editor.jumpBackward"):
            self._jump_mode = "backward"
            return

        if e.text is not None:
            self._insert_character(e.text)

    def handle_paste(self, text: str) -> None:
        """editor.ts:1142-1208 ``handlePaste`` (minus the pieces noted in
        module docstring deviation 9). Filters control characters, folds
        large pastes (>10 lines or >1000 chars, editor.ts:1183-1198) into a
        ``[paste #N +M lines]``/``[paste #N M chars]`` marker, and is a
        single undo unit (one ``_push_undo_snapshot`` for the whole
        paste — never per-character)."""
        self._last_action = None
        self._exit_history_browsing()
        self._push_undo_snapshot()

        clean_text = self._normalize_text(text)
        filtered_text = "".join(ch for ch in clean_text if ch == "\n" or ord(ch) >= 32)

        pasted_lines = filtered_text.split("\n")
        total_chars = len(filtered_text)

        if len(pasted_lines) > 10 or total_chars > 1000:
            self._paste_counter += 1
            paste_id = self._paste_counter
            self._pastes[paste_id] = filtered_text

            if len(pasted_lines) > 10:
                marker = f"[paste #{paste_id} +{len(pasted_lines)} lines]"
            else:
                marker = f"[paste #{paste_id} {total_chars} chars]"
            self._insert_text_at_cursor(marker)
            return

        self._insert_text_at_cursor(filtered_text)

    # -- text normalization / insertion (editor.ts:1025-1079) ------------

    def _normalize_text(self, text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")

    def _insert_text_at_cursor(self, text: str) -> None:
        if not text:
            return
        inserted_lines = text.split("\n")
        current_line = self._lines[self._cursor_line]
        before = current_line[: self._cursor_col]
        after = current_line[self._cursor_col :]

        if len(inserted_lines) == 1:
            self._lines[self._cursor_line] = before + text + after
            self._set_cursor_col(self._cursor_col + len(text))
        else:
            self._lines = (
                self._lines[: self._cursor_line]
                + [before + inserted_lines[0]]
                + inserted_lines[1:-1]
                + [inserted_lines[-1] + after]
                + self._lines[self._cursor_line + 1 :]
            )
            self._cursor_line += len(inserted_lines) - 1
            self._set_cursor_col(len(inserted_lines[-1]))

    def _insert_character(self, char: str) -> None:
        """editor.ts:1082-1095 undo-coalescing prefix (fish-style): consecutive
        word chars coalesce into one undo unit; a space captures state
        *before* itself (so undo removes the space+following word together);
        each space is separately undoable."""
        self._exit_history_browsing()

        if char.isspace() or self._last_action != "type-word":
            self._push_undo_snapshot()
        self._last_action = "type-word"

        line = self._lines[self._cursor_line]
        before = line[: self._cursor_col]
        after = line[self._cursor_col :]
        self._lines[self._cursor_line] = before + char + after
        self._set_cursor_col(self._cursor_col + len(char))

    # -- editing actions (editor.ts:1210-1233, 1262-1317) ----------------

    def _add_new_line(self) -> None:
        self._exit_history_browsing()
        self._last_action = None
        self._push_undo_snapshot()

        line = self._lines[self._cursor_line]
        before = line[: self._cursor_col]
        after = line[self._cursor_col :]
        self._lines[self._cursor_line] = before
        self._lines.insert(self._cursor_line + 1, after)
        self._cursor_line += 1
        self._set_cursor_col(0)

    def _submit_value(self) -> None:
        """editor.ts:1246-1260 ``submitValue`` — expands paste markers
        before handing text to ``on_submit`` (the brief's binding
        requirement: the model must never see a raw marker string), clears
        paste tracking, exits history browsing, and clears the undo
        stack (a submitted buffer has nothing left to undo into)."""
        result = self.get_expanded_text().strip()
        self._lines = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._preferred_visual_col = None
        self._snapped_from_cursor_col = None
        self._pastes.clear()
        self._paste_counter = 0
        self._exit_history_browsing()
        self._undo_stack.clear()
        self._last_action = None
        if self.on_submit is not None:
            self.on_submit(result)

    def _handle_backspace(self) -> None:
        self._exit_history_browsing()
        self._last_action = None

        if self._cursor_col > 0:
            self._push_undo_snapshot()
            line = self._lines[self._cursor_line]
            # Delete the atomic unit before the cursor: a paste marker if
            # one ends exactly here, else one grapheme (handles emojis,
            # combining characters, etc. — editor.ts:1269-1282).
            unit_len = self._segment_len_before(line, self._cursor_col)
            before = line[: self._cursor_col - unit_len]
            after = line[self._cursor_col :]
            self._lines[self._cursor_line] = before + after
            self._set_cursor_col(self._cursor_col - unit_len)
        elif self._cursor_line > 0:
            self._push_undo_snapshot()
            current_line = self._lines[self._cursor_line]
            previous_line = self._lines[self._cursor_line - 1]
            self._lines[self._cursor_line - 1] = previous_line + current_line
            del self._lines[self._cursor_line]
            self._cursor_line -= 1
            self._set_cursor_col(len(previous_line))

    def _handle_forward_delete(self) -> None:
        self._exit_history_browsing()
        self._last_action = None

        line = self._lines[self._cursor_line]
        if self._cursor_col < len(line):
            self._push_undo_snapshot()
            # Delete the atomic unit at the cursor: a paste marker if one
            # starts exactly here, else one grapheme (editor.ts:1639-1652).
            unit_len = self._segment_len_at(line, self._cursor_col)
            before = line[: self._cursor_col]
            after = line[self._cursor_col + unit_len :]
            self._lines[self._cursor_line] = before + after
        elif self._cursor_line < len(self._lines) - 1:
            self._push_undo_snapshot()
            next_line = self._lines[self._cursor_line + 1]
            self._lines[self._cursor_line] = line + next_line
            del self._lines[self._cursor_line + 1]

    # -- kill ring (editor.ts:1479-1631, 1852-1968) ----------------------

    def _delete_to_start_of_line(self) -> None:
        """Ctrl+U. editor.ts:1479-1512 ``deleteToStartOfLine``."""
        self._exit_history_browsing()
        current_line = self._lines[self._cursor_line]

        if self._cursor_col > 0:
            self._push_undo_snapshot()
            deleted_text = current_line[: self._cursor_col]
            self._kill_ring.kill(deleted_text, prepend=True, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            self._lines[self._cursor_line] = current_line[self._cursor_col :]
            self._set_cursor_col(0)
        elif self._cursor_line > 0:
            self._push_undo_snapshot()
            self._kill_ring.kill("\n", prepend=True, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            previous_line = self._lines[self._cursor_line - 1]
            self._lines[self._cursor_line - 1] = previous_line + current_line
            del self._lines[self._cursor_line]
            self._cursor_line -= 1
            self._set_cursor_col(len(previous_line))

    def _delete_to_end_of_line(self) -> None:
        """Ctrl+K. editor.ts:1514-1544 ``deleteToEndOfLine``."""
        self._exit_history_browsing()
        current_line = self._lines[self._cursor_line]

        if self._cursor_col < len(current_line):
            self._push_undo_snapshot()
            deleted_text = current_line[self._cursor_col :]
            self._kill_ring.kill(
                deleted_text, prepend=False, accumulate=self._last_action == "kill"
            )
            self._last_action = "kill"
            self._lines[self._cursor_line] = current_line[: self._cursor_col]
        elif self._cursor_line < len(self._lines) - 1:
            self._push_undo_snapshot()
            self._kill_ring.kill("\n", prepend=False, accumulate=self._last_action == "kill")
            self._last_action = "kill"
            next_line = self._lines[self._cursor_line + 1]
            self._lines[self._cursor_line] = current_line + next_line
            del self._lines[self._cursor_line + 1]

    def _delete_word_backward(self) -> None:
        """Ctrl+W / Alt+Backspace. editor.ts:1546-1589 ``deleteWordBackwards``."""
        self._exit_history_browsing()
        current_line = self._lines[self._cursor_line]

        if self._cursor_col == 0:
            if self._cursor_line > 0:
                self._push_undo_snapshot()
                self._kill_ring.kill("\n", prepend=True, accumulate=self._last_action == "kill")
                self._last_action = "kill"
                previous_line = self._lines[self._cursor_line - 1]
                self._lines[self._cursor_line - 1] = previous_line + current_line
                del self._lines[self._cursor_line]
                self._cursor_line -= 1
                self._set_cursor_col(len(previous_line))
            return

        self._push_undo_snapshot()
        was_kill = self._last_action == "kill"
        old_cursor_col = self._cursor_col
        self._move_word_backwards()
        delete_from = self._cursor_col
        self._set_cursor_col(old_cursor_col)

        deleted_text = current_line[delete_from : self._cursor_col]
        self._kill_ring.kill(deleted_text, prepend=True, accumulate=was_kill)
        self._last_action = "kill"

        self._lines[self._cursor_line] = (
            current_line[:delete_from] + current_line[self._cursor_col :]
        )
        self._set_cursor_col(delete_from)

    def _delete_word_forward(self) -> None:
        """Alt+D / Alt+Delete. editor.ts:1591-1631 ``deleteWordForward``."""
        self._exit_history_browsing()
        current_line = self._lines[self._cursor_line]

        if self._cursor_col >= len(current_line):
            if self._cursor_line < len(self._lines) - 1:
                self._push_undo_snapshot()
                self._kill_ring.kill("\n", prepend=False, accumulate=self._last_action == "kill")
                self._last_action = "kill"
                next_line = self._lines[self._cursor_line + 1]
                self._lines[self._cursor_line] = current_line + next_line
                del self._lines[self._cursor_line + 1]
            return

        self._push_undo_snapshot()
        was_kill = self._last_action == "kill"
        old_cursor_col = self._cursor_col
        self._move_word_forwards()
        delete_to = self._cursor_col
        self._set_cursor_col(old_cursor_col)

        deleted_text = current_line[self._cursor_col : delete_to]
        self._kill_ring.kill(deleted_text, prepend=False, accumulate=was_kill)
        self._last_action = "kill"

        self._lines[self._cursor_line] = current_line[: self._cursor_col] + current_line[delete_to:]

    def _yank(self) -> None:
        """Ctrl+Y. editor.ts:1852-1861 ``yank``."""
        if len(self._kill_ring) == 0:
            return
        self._push_undo_snapshot()
        text = self._kill_ring.yank()
        assert text is not None
        self._insert_yanked_text(text)
        self._last_action = "yank"

    def _yank_pop(self) -> None:
        """Alt+Y. editor.ts:1867-1884 ``yankPop`` — only works immediately
        after a yank/yank-pop, and only if the ring has more than one
        entry."""
        if self._last_action != "yank" or len(self._kill_ring) <= 1:
            return
        self._push_undo_snapshot()
        self._delete_yanked_text()
        text = self._kill_ring.yank_pop()
        assert text is not None
        self._insert_yanked_text(text)
        self._last_action = "yank"

    def _insert_yanked_text(self, text: str) -> None:
        """editor.ts:1889-1926 ``insertYankedText``."""
        self._exit_history_browsing()
        lines = text.split("\n")
        current_line = self._lines[self._cursor_line]
        before = current_line[: self._cursor_col]
        after = current_line[self._cursor_col :]

        if len(lines) == 1:
            self._lines[self._cursor_line] = before + text + after
            self._set_cursor_col(self._cursor_col + len(text))
        else:
            self._lines[self._cursor_line] = before + lines[0]
            for i in range(1, len(lines) - 1):
                self._lines.insert(self._cursor_line + i, lines[i])
            last_line_index = self._cursor_line + len(lines) - 1
            self._lines.insert(last_line_index, lines[-1] + after)
            self._cursor_line = last_line_index
            self._set_cursor_col(len(lines[-1]))

    def _delete_yanked_text(self) -> None:
        """editor.ts:1932-1968 ``deleteYankedText`` — used by yank-pop to
        remove the previously-yanked text (derived from the kill ring's
        current top, which hasn't rotated yet)."""
        yanked_text = self._kill_ring.yank()
        if not yanked_text:
            return
        yank_lines = yanked_text.split("\n")

        if len(yank_lines) == 1:
            current_line = self._lines[self._cursor_line]
            delete_len = len(yanked_text)
            before = current_line[: self._cursor_col - delete_len]
            after = current_line[self._cursor_col :]
            self._lines[self._cursor_line] = before + after
            self._set_cursor_col(self._cursor_col - delete_len)
        else:
            start_line = self._cursor_line - (len(yank_lines) - 1)
            start_col = len(self._lines[start_line]) - len(yank_lines[0])
            after_cursor = self._lines[self._cursor_line][self._cursor_col :]
            before_yank = self._lines[start_line][:start_col]
            self._lines[start_line : start_line + len(yank_lines)] = [before_yank + after_cursor]
            self._cursor_line = start_line
            self._set_cursor_col(start_col)

    # -- undo (editor.ts:1970-1984) ---------------------------------------

    def _push_undo_snapshot(self) -> None:
        self._undo_stack.push(self._snapshot())

    def _snapshot(self) -> _EditorSnapshot:
        return _EditorSnapshot(list(self._lines), self._cursor_line, self._cursor_col)

    def _restore(self, snapshot: _EditorSnapshot) -> None:
        self._lines = list(snapshot.lines)
        self._cursor_line = snapshot.cursor_line
        self._cursor_col = snapshot.cursor_col

    def _undo(self) -> None:
        """Ctrl+-. editor.ts:1974-1984 ``undo`` — exits history browsing
        even when the undo stack is empty (matches upstream's call order)."""
        self._exit_history_browsing()
        snapshot = self._undo_stack.undo()
        if snapshot is None:
            return
        self._restore(snapshot)
        self._last_action = None
        self._preferred_visual_col = None

    # -- history (editor.ts:381-444) ---------------------------------------

    def _exit_history_browsing(self) -> None:
        """editor.ts:441-444 ``exitHistoryBrowsing`` — drops the browsing
        bookkeeping without restoring any draft (so an in-progress edit of
        a history entry becomes the new live text, matching upstream)."""
        self._history_index = -1
        self._history_draft = None

    def _navigate_history(self, direction: int) -> None:
        """Up (direction=-1) / Down (direction=1). editor.ts:409-439
        ``navigateHistory``, including draft capture/restore semantics."""
        self._last_action = None
        if not self.history:
            return

        new_index = self._history_index - direction
        if new_index < -1 or new_index >= len(self.history):
            return

        if self._history_index == -1 and new_index >= 0:
            self._push_undo_snapshot()
            self._history_draft = self._snapshot()

        self._history_index = new_index

        if self._history_index == -1:
            draft = self._history_draft
            self._history_draft = None
            if draft is not None:
                self._restore(draft)
                self._preferred_visual_col = None
                self._snapped_from_cursor_col = None
            else:
                self._set_text_internal("", "end")
        else:
            self._set_text_internal(
                self.history[self._history_index], "start" if direction == -1 else "end"
            )

    def _is_editor_empty(self) -> bool:
        return len(self._lines) == 1 and self._lines[0] == ""

    # -- simple cursor movement (editor.ts:1468-1477, 1827-1847, 2020-2039) --

    def _set_cursor_col(self, col: int) -> None:
        """Set cursor column and clear the sticky (preferred visual)
        column. Used for all non-vertical cursor movements (editor.ts:
        1319-1327)."""
        self._cursor_col = col
        self._preferred_visual_col = None
        self._snapped_from_cursor_col = None

    def _move_to_line_start(self) -> None:
        self._last_action = None
        self._set_cursor_col(0)

    def _move_to_line_end(self) -> None:
        self._last_action = None
        line = self._lines[self._cursor_line]
        self._set_cursor_col(len(line))

    def _move_word_backwards(self) -> None:
        self._last_action = None
        line = self._lines[self._cursor_line]
        if self._cursor_col == 0:
            if self._cursor_line > 0:
                self._cursor_line -= 1
                prev_line = self._lines[self._cursor_line]
                self._set_cursor_col(len(prev_line))
            return
        self._set_cursor_col(self._word_left_with_markers(line, self._cursor_col))

    def _move_word_forwards(self) -> None:
        self._last_action = None
        line = self._lines[self._cursor_line]
        if self._cursor_col >= len(line):
            if self._cursor_line < len(self._lines) - 1:
                self._cursor_line += 1
                self._set_cursor_col(0)
            return
        self._set_cursor_col(self._word_right_with_markers(line, self._cursor_col))

    def _jump_to_char(self, char: str, direction: str) -> None:
        """Jump to the first occurrence of ``char`` in ``direction``
        ("forward"/"backward"), multi-line, case-sensitive, skipping the
        current cursor position. No-op if not found (editor.ts:1986-2018)."""
        self._last_action = None
        is_forward = direction == "forward"
        lines = self._lines
        end = len(lines) if is_forward else -1
        step = 1 if is_forward else -1

        start_line = self._cursor_line
        line_idx = start_line
        while line_idx != end:
            line = lines[line_idx]
            is_current_line = line_idx == start_line

            if is_current_line:
                if is_forward:
                    idx = line.find(char, self._cursor_col + 1)
                else:
                    search_from = self._cursor_col - 1
                    idx = line.rfind(char, 0, search_from + 1) if search_from >= 0 else -1
            else:
                idx = line.find(char) if is_forward else line.rfind(char)

            if idx != -1:
                self._cursor_line = line_idx
                self._set_cursor_col(idx)
                return

            line_idx += step
        # No match found — cursor stays in place.

    # -- paste-marker atomic-segment helpers (editor.ts:21-91) -----------

    def _valid_paste_marker_at(self, line: str, col: int) -> re.Match[str] | None:
        """A paste-marker match starting exactly at ``col`` in ``line``,
        but only if its id is a currently-tracked paste (editor.ts's
        ``validPasteIds()`` gate) — a manually typed marker-shaped string
        with no matching paste is never atomic."""
        if not self._pastes or "[paste #" not in line:
            return None
        for m in _PASTE_MARKER_RE.finditer(line):
            if m.start() == col and int(m.group(1)) in self._pastes:
                return m
        return None

    def _valid_paste_marker_ending_at(self, line: str, col: int) -> re.Match[str] | None:
        """A paste-marker match ending exactly at ``col`` in ``line`` (id-validated,
        see ``_valid_paste_marker_at``)."""
        if not self._pastes or "[paste #" not in line:
            return None
        for m in _PASTE_MARKER_RE.finditer(line):
            if m.end() == col and int(m.group(1)) in self._pastes:
                return m
        return None

    def _segment_len_at(self, line: str, col: int) -> int:
        """Length of the atomic unit starting at ``col``: a valid paste
        marker's full length if one starts there, else the first
        grapheme's length."""
        marker = self._valid_paste_marker_at(line, col)
        if marker is not None:
            return len(marker.group(0))
        return _grapheme_len_at_start(line[col:])

    def _segment_len_before(self, line: str, col: int) -> int:
        """Length of the atomic unit ending at ``col``: a valid paste
        marker's full length if one ends there, else the last grapheme's
        length."""
        marker = self._valid_paste_marker_ending_at(line, col)
        if marker is not None:
            return len(marker.group(0))
        return _grapheme_len_at_end(line[:col])

    def _word_right_with_markers(self, line: str, col: int) -> int:
        """``word_right``, but a valid paste marker reached while skipping
        leading whitespace (or found immediately at ``col``) is treated as
        one atomic word-movement unit (editor.ts's ``findWordForward`` with
        ``isAtomicSegment``, folded in without modifying word_navigation.py —
        see module docstring deviation 5)."""
        n = len(line)
        i = col
        while i < n and line[i].isspace():
            marker = self._valid_paste_marker_at(line, i)
            if marker is not None:
                return marker.end()
            i += 1
        if i < n:
            marker = self._valid_paste_marker_at(line, i)
            if marker is not None:
                return marker.end()
        return word_right(line, col)

    def _word_left_with_markers(self, line: str, col: int) -> int:
        """Backward counterpart of ``_word_right_with_markers``."""
        i = col
        while i > 0 and line[i - 1].isspace():
            marker = self._valid_paste_marker_ending_at(line, i)
            if marker is not None:
                return marker.start()
            i -= 1
        if i > 0:
            marker = self._valid_paste_marker_ending_at(line, i)
            if marker is not None:
                return marker.start()
        return word_left(line, col)

    def _segment_with_markers(self, text: str) -> list[tuple[str, int]]:
        """Grapheme segmentation of ``text`` with valid paste markers merged
        into single atomic segments — editor.ts:39-91 ``segmentWithMarkers``,
        folded into this port's index-carrying grapheme-segment
        representation (``_grapheme_segments``). Degrades to plain grapheme
        segmentation whenever there are no tracked pastes or no marker-shaped
        text, so lines with no paste markers (i.e. every pre-task-12 test)
        are completely unaffected."""
        if not self._pastes or "[paste #" not in text:
            return _grapheme_segments(text)

        markers: list[tuple[int, int]] = []
        for m in _PASTE_MARKER_RE.finditer(text):
            if int(m.group(1)) in self._pastes:
                markers.append((m.start(), m.end()))
        if not markers:
            return _grapheme_segments(text)

        result: list[tuple[str, int]] = []
        marker_idx = 0
        for g, idx in _grapheme_segments(text):
            while marker_idx < len(markers) and markers[marker_idx][1] <= idx:
                marker_idx += 1
            if marker_idx < len(markers):
                m_start, m_end = markers[marker_idx]
                if m_start <= idx < m_end:
                    if idx == m_start:
                        result.append((text[m_start:m_end], m_start))
                    continue
            result.append((g, idx))
        return result

    # -- soft-wrap layout (editor.ts:881-967, 1690-1746) -----------------

    def _layout_text(self, content_width: int) -> list[_LayoutLine]:
        if len(self._lines) == 1 and self._lines[0] == "":
            return [_LayoutLine("", True, 0)]

        layout_lines: list[_LayoutLine] = []
        for i, line in enumerate(self._lines):
            is_current_line = i == self._cursor_line
            line_width = visible_width(line)

            if line_width <= content_width:
                if is_current_line:
                    layout_lines.append(_LayoutLine(line, True, self._cursor_col))
                else:
                    layout_lines.append(_LayoutLine(line, False))
                continue

            chunks = word_wrap_line(line, content_width, self._segment_with_markers(line))
            for ci, chunk in enumerate(chunks):
                is_last_chunk = ci == len(chunks) - 1
                has_cursor_in_chunk = False
                adjusted_cursor_pos = 0

                if is_current_line:
                    if is_last_chunk:
                        has_cursor_in_chunk = self._cursor_col >= chunk.start
                        adjusted_cursor_pos = self._cursor_col - chunk.start
                    else:
                        has_cursor_in_chunk = chunk.start <= self._cursor_col < chunk.end
                        if has_cursor_in_chunk:
                            adjusted_cursor_pos = self._cursor_col - chunk.start
                            if adjusted_cursor_pos > len(chunk.text):
                                adjusted_cursor_pos = len(chunk.text)

                if has_cursor_in_chunk:
                    layout_lines.append(_LayoutLine(chunk.text, True, adjusted_cursor_pos))
                else:
                    layout_lines.append(_LayoutLine(chunk.text, False))

        return layout_lines

    def _build_visual_line_map(self, width: int) -> list[_VisualLine]:
        visual_lines: list[_VisualLine] = []
        for i, line in enumerate(self._lines):
            line_vis_width = visible_width(line)
            if len(line) == 0:
                visual_lines.append((i, 0, 0))
            elif line_vis_width <= width:
                visual_lines.append((i, 0, len(line)))
            else:
                chunks = word_wrap_line(line, width, self._segment_with_markers(line))
                for chunk in chunks:
                    visual_lines.append((i, chunk.start, chunk.end - chunk.start))
        return visual_lines

    def _find_visual_line_at(self, visual_lines: list[_VisualLine], line: int, col: int) -> int:
        for i, (log_line, start_col, length) in enumerate(visual_lines):
            if log_line != line:
                continue
            offset = col - start_col
            is_last_segment = i == len(visual_lines) - 1 or visual_lines[i + 1][0] != log_line
            if offset >= 0 and (offset < length or (is_last_segment and offset == length)):
                return i
        return len(visual_lines) - 1

    def _find_current_visual_line(self, visual_lines: list[_VisualLine]) -> int:
        return self._find_visual_line_at(visual_lines, self._cursor_line, self._cursor_col)

    def _is_on_first_visual_line(self) -> bool:
        visual_lines = self._build_visual_line_map(self._last_width)
        return self._find_current_visual_line(visual_lines) == 0

    def _is_on_last_visual_line(self) -> bool:
        visual_lines = self._build_visual_line_map(self._last_width)
        return self._find_current_visual_line(visual_lines) == len(visual_lines) - 1

    # -- vertical movement / sticky column (editor.ts:1330-1466, 1748-1809) --

    def _move_cursor(self, delta_line: int, delta_col: int) -> None:
        self._last_action = None
        visual_lines = self._build_visual_line_map(self._last_width)
        current_visual_line = self._find_current_visual_line(visual_lines)

        if delta_line != 0:
            target_visual_line = current_visual_line + delta_line
            if 0 <= target_visual_line < len(visual_lines):
                self._move_to_visual_line(visual_lines, current_visual_line, target_visual_line)

        if delta_col != 0:
            current_line = self._lines[self._cursor_line]

            if delta_col > 0:
                if self._cursor_col < len(current_line):
                    step = self._segment_len_at(current_line, self._cursor_col)
                    self._set_cursor_col(self._cursor_col + step)
                elif self._cursor_line < len(self._lines) - 1:
                    self._cursor_line += 1
                    self._set_cursor_col(0)
                else:
                    # At end of last line: can't move, but set
                    # preferredVisualCol for subsequent up/down navigation
                    # (editor.ts:1776-1781).
                    if current_visual_line < len(visual_lines):
                        current_vl = visual_lines[current_visual_line]
                        self._preferred_visual_col = self._cursor_col - current_vl[1]
            else:
                if self._cursor_col > 0:
                    step = self._segment_len_before(current_line, self._cursor_col)
                    self._set_cursor_col(self._cursor_col - step)
                elif self._cursor_line > 0:
                    self._cursor_line -= 1
                    prev_line = self._lines[self._cursor_line]
                    self._set_cursor_col(len(prev_line))

    def _move_to_visual_line(
        self,
        visual_lines: list[_VisualLine],
        current_visual_line: int,
        target_visual_line: int,
    ) -> None:
        current_vl = visual_lines[current_visual_line]
        target_vl = visual_lines[target_visual_line]

        # When the cursor was snapped to a segment start on a previous
        # vertical move, resolve the pre-snap position against the VL it
        # belongs to. This gives the correct visual column even after a
        # resize reshuffles VLs (editor.ts:1346-1349).
        if self._snapped_from_cursor_col is not None:
            vl_index = self._find_visual_line_at(
                visual_lines, current_vl[0], self._snapped_from_cursor_col
            )
            current_visual_col = self._snapped_from_cursor_col - visual_lines[vl_index][1]
        else:
            current_visual_col = self._cursor_col - current_vl[1]

        is_last_source_segment = (
            current_visual_line == len(visual_lines) - 1
            or visual_lines[current_visual_line + 1][0] != current_vl[0]
        )
        source_max_visual_col = (
            current_vl[2] if is_last_source_segment else max(0, current_vl[2] - 1)
        )

        is_last_target_segment = (
            target_visual_line == len(visual_lines) - 1
            or visual_lines[target_visual_line + 1][0] != target_vl[0]
        )
        target_max_visual_col = target_vl[2] if is_last_target_segment else max(0, target_vl[2] - 1)

        move_to_visual_col = self._compute_vertical_move_column(
            current_visual_col, source_max_visual_col, target_max_visual_col
        )

        # Direct assignment (not _set_cursor_col): preferredVisualCol is
        # managed by _compute_vertical_move_column itself, not reset here
        # (editor.ts:1366-1370).
        self._cursor_line = target_vl[0]
        target_col = target_vl[1] + move_to_visual_col
        logical_line = self._lines[target_vl[0]]
        self._cursor_col = min(target_col, len(logical_line))

        # Snap cursor to atomic segment boundary (e.g. a paste marker) so
        # the cursor never lands mid-marker — a partial edit there would
        # split the marker text, breaking the PASTE_MARKER_REGEX match and
        # silently losing the pasted content at submit time. Single-
        # grapheme segments don't need snapping (editor.ts:1372-1412
        # snappedFromCursorCol).
        segments = self._segment_with_markers(logical_line)
        for seg_text, seg_index in segments:
            if seg_index > self._cursor_col:
                break
            if len(seg_text) <= 1:
                continue
            if self._cursor_col < seg_index + len(seg_text):
                is_continuation = seg_index < target_vl[1]
                is_moving_down = target_visual_line > current_visual_line

                if is_continuation and is_moving_down:
                    # The segment started on a previous visual line, and we
                    # already visited it on the way down. Skip all
                    # remaining continuation VLs and land on the first VL
                    # past it.
                    seg_end = seg_index + len(seg_text)
                    next_vl = target_visual_line + 1
                    while (
                        next_vl < len(visual_lines)
                        and visual_lines[next_vl][0] == target_vl[0]
                        and visual_lines[next_vl][1] < seg_end
                    ):
                        next_vl += 1
                    if next_vl < len(visual_lines):
                        self._move_to_visual_line(visual_lines, current_visual_line, next_vl)
                        return

                # Snap to the start of the segment so it gets highlighted.
                # Store the pre-snap position so the next vertical move can
                # resolve it to the correct visual column.
                self._snapped_from_cursor_col = self._cursor_col
                self._cursor_col = seg_index
                return

        # No snap occurred — we moved out of the atomic segment.
        self._snapped_from_cursor_col = None

    def _compute_vertical_move_column(
        self,
        current_visual_col: int,
        source_max_visual_col: int,
        target_max_visual_col: int,
    ) -> int:
        """Sticky-column decision table (editor.ts:1415-1466), ported
        verbatim. ``P`` = preferred col set, ``S`` = cursor in middle of
        source line, ``T`` = target line shorter than current visual col,
        ``U`` = target line shorter than preferred col."""
        has_preferred = self._preferred_visual_col is not None  # P
        cursor_in_middle = current_visual_col < source_max_visual_col  # S
        target_too_short = target_max_visual_col < current_visual_col  # T

        if not has_preferred or cursor_in_middle:
            if target_too_short:
                self._preferred_visual_col = current_visual_col
                return target_max_visual_col
            self._preferred_visual_col = None
            return current_visual_col

        assert self._preferred_visual_col is not None
        target_cant_fit_preferred = target_max_visual_col < self._preferred_visual_col  # U
        if target_too_short or target_cant_fit_preferred:
            return target_max_visual_col

        result = self._preferred_visual_col
        self._preferred_visual_col = None
        return result
