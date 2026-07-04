"""Editor component — Python port of upstream pi's
``packages/tui/src/components/editor.ts`` (2307 lines), narrowed to task-11
brief's scope: buffer model, cursor, character insert/delete, arrow/word/
line movement, character jump (Ctrl+]/Ctrl+Alt+]), sticky-column vertical
movement, and soft-wrap rendering with an embedded ``CURSOR_MARKER``.

Interface (binding, per task-11 brief):

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
  encoding). Implements this task's action subset only: character insert,
  backspace/delete (single grapheme), arrow movement (with sticky column),
  word movement (Ctrl+Left/Right et al.), line start/end (Home/End,
  Ctrl+A/E), character jump, the backslash+Enter newline workaround, the
  ``newLine`` action, and ``submit``.
- ``handle_paste(text: str) -> None`` — minimal whole-segment plain insert
  for now; Task 12 adds large-paste marker folding.
- ``render(width: int) -> list[str]`` — soft-wrapped visual lines framed by
  a plain top/bottom border line (``"─" * width``, no theme/color — this
  port's ``Editor`` takes no ``tui``/``theme`` constructor argument, see
  deviation 1); embeds ``CURSOR_MARKER`` at the cursor's grapheme position
  when ``focused`` is true (task-7's ``CURSOR_MARKER`` — locating/extracting
  it into a hardware-cursor position is the TUI's job, not this component's).

Consumes: Task 4 (``KeyEvent``/``parse_key``/``key_id``), Task 5
(``KeyBindings``/``DEFAULT_EDITOR_BINDINGS``), Task 1 (``visible_width``/
``graphemes``), Task 7 (``CURSOR_MARKER``), and the already-ported
``word_left``/``word_right`` (word-navigation.ts, task-5 brief).

Deliberately out of scope this task (clean seams, no implementation) —
Task 12 (kill-ring/undo/history/paste-marker) and Task 13 (autocomplete):

- No ``KillRing``/``UndoStack`` wiring at all: nothing is pushed to an undo
  stack, nothing is copied to a kill ring. Consequently Ctrl+W/Alt+Backspace
  (deleteWordBackward), Alt+D/Alt+Delete (deleteWordForward), Ctrl+U/Ctrl+K
  (delete-to-line-start/end), Ctrl+Y/Alt+Y (yank/yank-pop), and Ctrl+-
  (undo) are simply never dispatched in ``handle_key`` — Task 12 adds those
  branches without needing to touch anything else here.
- No prompt history (``addToHistory``/``navigateHistory``/up-down browsing).
  ``_navigate_history`` is kept as an explicit no-op stub, wired into the
  Up/Down arrow dispatch in the exact same conditional shape as upstream
  (editor.ts:809-833) — since upstream's own ``navigateHistory`` is *also* a
  no-op when history is empty (editor.ts:411 ``if (this.history.length ===
  0) return;``), keeping the real conditional structure (rather than
  collapsing it away) reproduces upstream's exact observable behavior for
  an editor that never has history, not just a stand-in.
- No large-paste marker synthesis/expansion/atomic-segment awareness
  (``pastes``/``pasteCounter``/``segmentWithMarkers``/``isPasteMarker``).
  ``handle_paste`` filters control characters and inserts the (possibly
  multi-line) text verbatim — see its own docstring.
- No autocomplete (``autocompleteProvider``/``SelectList`` integration,
  slash-command/@-mention triggering, Tab-completion). Tab is not
  special-cased at all: with no autocomplete state ever active, upstream's
  own ``handleTabCompletion`` already no-ops without a registered provider
  (editor.ts:2100-2101 ``if (!this.autocompleteProvider) return;``), and a
  bare Tab keypress decodes to a ``KeyEvent`` with no ``.text`` (keys.py:
  Tab yields ``KeyEvent(name="tab")``, no printable payload), so it falls
  through this port's dispatch as a no-op for free — no explicit branch
  needed to reproduce that.

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
   operation below always advances by whole grapheme-cluster boundaries
   (via ``graphemes()``, exactly mirroring upstream's own
   ``Intl.Segmenter``-based ``graphemeLength`` computations), the cursor
   index is always left sitting at a grapheme boundary — i.e. it *is* "the
   grapheme column" the brief specifies, without needing a separate
   grapheme-index bookkeeping layer distinct from the string index.
3. **No atomic-segment ("snap to paste-marker start") logic in vertical
   movement** (editor.ts:1372-1412) — with no paste markers implemented
   this task (see above), no segment in this port's grapheme segmentation
   is ever longer than one Python index position for any tested input, so
   the snap branch would never fire; it is omitted rather than carried as
   dead code. Task 12, when it adds marker-aware segmentation, is the
   natural place to re-add it.
4. **``wordWrapLine`` has no ``preSegmented``/atomic-marker parameter** and
   is a private module function (``_word_wrap_line``), not an exported
   symbol — the task-11 brief's Produces list is the ``Editor`` component
   only; nothing in the RED suite imports ``wordWrapLine`` directly (all
   word-wrap assertions go through ``Editor.render()``). The wrapping
   *algorithm itself* (backtrack-to-last-whitespace-boundary, force-break
   when no viable boundary exists, CJK break-anywhere) is ported faithfully
   (editor.ts:114-206).
5. **Word-boundary movement (Ctrl+Left/Right et al.) uses the already-ported
   ``word_left``/``word_right``** (``engine/word_navigation.py``, task-5),
   not a re-port of upstream's ``findWordBackward``/``findWordForward`` —
   those functions' own module docstring documents the CJK-run-as-one-word
   simplification ruling (spec §9) that this reuse inherits.
6. **``onChange`` callback, ``disableSubmit``, and ``getExpandedText``/
   ``getLines``/``getCursor``/``getText`` accessor *methods* are not
   ported** — the task-11 brief's Produces list exposes ``text``/``cursor``
   as plain read-only properties and only ``on_submit`` as a callback; none
   of the 87 translated tests exercise ``onChange`` or ``disableSubmit``.
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
   ``False`` can be replaced with the negotiated value.
8. **``_submit_value`` resets ``_preferred_visual_col`` to ``None``**,
   which upstream's ``submitValue`` (editor.ts:1246-1259) does not do —
   deliberate, not an oversight: submit clears the buffer back to a single
   empty line, and leaving a stale sticky-column value in place would let
   it leak into subsequent up/down navigation on that fresh empty buffer
   (``_compute_vertical_move_column`` treats a non-``None`` value as "the
   user has an intentional preferred column to restore"). Resetting it
   here is a narrow behavioral improvement over upstream rather than a
   compatibility gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import regex

from ..engine.keybindings import DEFAULT_EDITOR_BINDINGS, KeyBindings
from ..engine.keys import KeyEvent, key_id, parse_key
from ..engine.tui import CURSOR_MARKER
from ..engine.utils import graphemes, visible_width
from ..engine.word_navigation import word_left, word_right

__all__ = ["Editor"]

# =============================================================================
# Bracketed-paste markers (stdin_buffer.py's single-channel contract: a whole
# paste frame arrives through handle_input with both markers preserved).
# =============================================================================

_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"

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


def _word_wrap_line(line: str, max_width: int) -> list[_Chunk]:
    """Split ``line`` into word-wrapped chunks, each at most ``max_width``
    visible columns. Ported from editor.ts:114-206 ``wordWrapLine``, minus
    the ``preSegmented``/atomic-marker parameter (see module docstring
    deviation 4)."""
    if not line or max_width <= 0:
        return [_Chunk("", 0, 0)]

    if visible_width(line) <= max_width:
        return [_Chunk(line, 0, len(line))]

    chunks: list[_Chunk] = []
    segments = _grapheme_segments(line)

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
            # Single grapheme wider than max_width: re-wrap it at grapheme
            # granularity (visual split only; still one logical unit).
            sub_chunks = _word_wrap_line(grapheme, max_width)
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
# Editor
# =============================================================================

_DEFAULT_BINDINGS = KeyBindings(DEFAULT_EDITOR_BINDINGS)


class Editor:
    """task-7 ``Component``/``Focusable``-compatible text editor: buffer
    model, cursor, editing, soft-wrapped rendering. See module docstring for
    full scope and deviations."""

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

        # Character jump mode (Ctrl+]/Ctrl+Alt+]), editor.ts:308.
        self._jump_mode: str | None = None

        # Prompt history is Task 12's territory — this port never populates
        # it, so history_index stays permanently -1 ("not browsing"). Kept
        # as real state (rather than a hardcoded literal at each call site)
        # so the Up/Down dispatch below can mirror upstream's exact
        # conditional shape; see module docstring's "clean seam" note.
        self._history_index: int = -1

    # -- public state accessors (editor.ts:969-996) --------------------

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    @property
    def cursor(self) -> tuple[int, int]:
        return (self._cursor_line, self._cursor_col)

    def set_text(self, text: str) -> None:
        normalized = self._normalize_text(text)
        lines = normalized.split("\n")
        self._lines = lines if lines else [""]
        self._cursor_line = len(self._lines) - 1
        self._set_cursor_col(len(self._lines[self._cursor_line]))

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
        """Internal action dispatch for this task's subset of
        ``DEFAULT_EDITOR_BINDINGS`` (kept public per the task-11 brief, so a
        caller can drive actions directly, bypassing frame encoding).

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

        if kb.matches(kid, "tui.editor.deleteCharBackward") or kid == "shift+backspace":
            self._handle_backspace()
            return
        if kb.matches(kid, "tui.editor.deleteCharForward") or kid == "shift+delete":
            self._handle_forward_delete()
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
        """Minimal whole-segment plain insert (Task 12 adds large-paste
        marker folding, kill-ring/undo integration on top of this)."""
        normalized = self._normalize_text(text)
        filtered = "".join(ch for ch in normalized if ch == "\n" or ord(ch) >= 32)
        self._insert_text_at_cursor(filtered)

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
        line = self._lines[self._cursor_line]
        before = line[: self._cursor_col]
        after = line[self._cursor_col :]
        self._lines[self._cursor_line] = before + char + after
        self._set_cursor_col(self._cursor_col + len(char))

    # -- editing actions (editor.ts:1210-1233, 1262-1317) ----------------

    def _add_new_line(self) -> None:
        line = self._lines[self._cursor_line]
        before = line[: self._cursor_col]
        after = line[self._cursor_col :]
        self._lines[self._cursor_line] = before
        self._lines.insert(self._cursor_line + 1, after)
        self._cursor_line += 1
        self._set_cursor_col(0)

    def _submit_value(self) -> None:
        result = self.text.strip()
        self._lines = [""]
        self._cursor_line = 0
        self._cursor_col = 0
        self._preferred_visual_col = None
        if self.on_submit is not None:
            self.on_submit(result)

    def _handle_backspace(self) -> None:
        if self._cursor_col > 0:
            line = self._lines[self._cursor_line]
            before_cursor = line[: self._cursor_col]
            grapheme_len = _grapheme_len_at_end(before_cursor)
            before = line[: self._cursor_col - grapheme_len]
            after = line[self._cursor_col :]
            self._lines[self._cursor_line] = before + after
            self._set_cursor_col(self._cursor_col - grapheme_len)
        elif self._cursor_line > 0:
            current_line = self._lines[self._cursor_line]
            previous_line = self._lines[self._cursor_line - 1]
            self._lines[self._cursor_line - 1] = previous_line + current_line
            del self._lines[self._cursor_line]
            self._cursor_line -= 1
            self._set_cursor_col(len(previous_line))

    def _handle_forward_delete(self) -> None:
        line = self._lines[self._cursor_line]
        if self._cursor_col < len(line):
            after_cursor = line[self._cursor_col :]
            grapheme_len = _grapheme_len_at_start(after_cursor)
            before = line[: self._cursor_col]
            after = line[self._cursor_col + grapheme_len :]
            self._lines[self._cursor_line] = before + after
        elif self._cursor_line < len(self._lines) - 1:
            next_line = self._lines[self._cursor_line + 1]
            self._lines[self._cursor_line] = line + next_line
            del self._lines[self._cursor_line + 1]

    # -- simple cursor movement (editor.ts:1468-1477, 1827-1847, 2020-2039) --

    def _set_cursor_col(self, col: int) -> None:
        """Set cursor column and clear the sticky (preferred visual)
        column. Used for all non-vertical cursor movements (editor.ts:
        1319-1327)."""
        self._cursor_col = col
        self._preferred_visual_col = None

    def _move_to_line_start(self) -> None:
        self._set_cursor_col(0)

    def _move_to_line_end(self) -> None:
        line = self._lines[self._cursor_line]
        self._set_cursor_col(len(line))

    def _move_word_backwards(self) -> None:
        line = self._lines[self._cursor_line]
        if self._cursor_col == 0:
            if self._cursor_line > 0:
                self._cursor_line -= 1
                prev_line = self._lines[self._cursor_line]
                self._set_cursor_col(len(prev_line))
            return
        self._set_cursor_col(word_left(line, self._cursor_col))

    def _move_word_forwards(self) -> None:
        line = self._lines[self._cursor_line]
        if self._cursor_col >= len(line):
            if self._cursor_line < len(self._lines) - 1:
                self._cursor_line += 1
                self._set_cursor_col(0)
            return
        self._set_cursor_col(word_right(line, self._cursor_col))

    def _jump_to_char(self, char: str, direction: str) -> None:
        """Jump to the first occurrence of ``char`` in ``direction``
        ("forward"/"backward"), multi-line, case-sensitive, skipping the
        current cursor position. No-op if not found (editor.ts:1986-2018)."""
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

    # -- history seam (Task 12 — see module docstring) -------------------

    def _navigate_history(self, direction: int) -> None:
        """No-op: this port never populates prompt history, so this
        reproduces upstream's own early-return for an empty history
        (editor.ts:411) rather than merely stubbing the call away."""
        return

    def _is_editor_empty(self) -> bool:
        return len(self._lines) == 1 and self._lines[0] == ""

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

            chunks = _word_wrap_line(line, content_width)
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
                chunks = _word_wrap_line(line, width)
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
                    after_cursor = current_line[self._cursor_col :]
                    step = _grapheme_len_at_start(after_cursor)
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
                    before_cursor = current_line[: self._cursor_col]
                    step = _grapheme_len_at_end(before_cursor)
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
