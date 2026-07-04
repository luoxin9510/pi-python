"""Markdown component — Python port of upstream pi's
``packages/tui/src/components/markdown.ts`` (858 lines), narrowed to the
plan's Task 14 interface: ``Markdown(source: str, caps: TermCaps)``
implementing ``Component`` (``render(width) -> list[str]``, ``invalidate()``).

Upstream's constructor is ``Markdown(text, paddingX, paddingY, theme,
defaultTextStyle?, options?)``. Per ``.superpowers/sdd/task-14-brief.md``:

- No ``paddingX``/``paddingY`` — always ``padding=0`` (render width ==
  content width), matching the ``Box`` narrowing precedent (``box.py``
  docstring deviations 1-2).
- No injectable ``MarkdownTheme``/``defaultTextStyle``/``MarkdownOptions`` —
  styling is pi's real default (dark) theme, fixed module-top constants
  exactly like ``select_list.py``'s precedent (see "Theme constants" below
  for the citation chain). No ordered-list-marker/backslash-escape
  preservation options either — ordered lists always renumber from the
  list's own ``start`` attribute + item index, matching upstream's own
  *default* (non-``preserveOrderedListMarkers``) behaviour
  (markdown.ts:613-616).
- ``caps: TermCaps`` (Task 2) gates *only* the OSC-8 hyperlink branch
  (``caps.hyperlinks``, markdown.ts:540) — ``caps.true_color`` is never
  consulted; every theme color below is a fixed truecolor
  (``\\x1b[38;2;R;G;Bm``) sequence, matching ``select_list.py``'s own
  precedent of hardcoding truecolor ANSI unconditionally.
- No render-output cache (markdown.ts:119-122, 152-154, 236-239) — a pure
  perf optimization orthogonal to render semantics, dropped for the same
  reason ``box.py`` drops its own cache (module docstring deviation 4
  there): not in this task's Produces list.

Three-stage pipeline (this port's own architecture, replacing upstream's
single ``marked``-based lex+render pass, since ``markdown-it-py``'s token
model differs structurally — see "markdown-it-py adapter notes" below):

1. ``_parse(source) -> list[Token]``: a module-level ``MarkdownIt("commonmark")``
   instance with ``table``/``strikethrough``/``linkify`` enabled (a GFM-like
   preset) plus :func:`strict_strikethrough_plugin`, producing markdown-it-py's
   flat open/close token stream.
2. ``_build_tree(tokens) -> list[Node]``: the flat-stream -> nested-node
   adapter layer. Tables are rebuilt into a ``{"type": "table", "header":
   [[Token,...],...], "rows": [[[Token,...],...],...]}`` shape isomorphic to
   upstream's already-nested ``Tokens.Table.header``/``.rows``
   (markdown.ts:685 ``renderTable``).
3. ``_render_node``/``_render_blocks``/``_render_inline``: per-node-type pi
   ANSI rendering rules, cited against markdown.ts line ranges throughout.

Theme constants (pi's real default dark theme, not invented — same citation
chain as task-10's ``select_list.py``):

- ``getMarkdownTheme()`` (``~/Developer/nukcole-pi/packages/coding-agent/src/
  modes/interactive/theme/theme.ts:1220-1251``): every markdown theme
  function is ``theme.fg(<colorKey>, text)`` except ``bold``/``italic``/
  ``underline`` (-> ``chalk.bold``/``chalk.italic``/``chalk.underline``) and
  ``strikethrough`` (-> ``chalk.strikethrough`` directly, theme.ts:1235 — no
  color, SGR 9/29 only).
- ``Theme.fg(color, text)`` (theme.ts:351-354): ``f"{ansi}{text}\\x1b[39m"`` —
  a foreground-only reset, never the full ``\\x1b[0m``.
- ``fgAnsi`` truecolor branch (theme.ts:260-266): hex -> ``\\x1b[38;2;R;G;Bm``.
- ``dark.json`` (``.../theme/dark.json``) ``vars`` (lines 7, 11, 12, 14) +
  ``colors.md*`` (lines 47-56): ``mdHeading="#f0c674"``, ``mdLink="#81a2be"``,
  ``mdLinkUrl=dimGray="#666666"``, ``mdCode=accent="#8abeb7"``,
  ``mdCodeBlock=green="#b5bd68"``, ``mdCodeBlockBorder=gray="#808080"``,
  ``mdQuote=gray``, ``mdQuoteBorder=gray``, ``mdHr=gray``,
  ``mdListBullet=accent``.
- ``chalk``'s ``bold``/``italic``/``underline``/``strikethrough`` SGR pairs
  (vendored ``ansi-styles`` table, index.js:13,15,16,18,20): bold=[1,22],
  italic=[3,23], underline=[4,24], strikethrough=[9,29].
- Table border characters (``┌─┬─┐``/``├─┼─┤``/``└─┴─┘``/``│``) carry **no**
  theme styling (verified by reading the full ``renderTable`` function,
  markdown.ts:685-857 — no ``theme.*`` call touches border glyphs, only
  header cell *text* gets ``theme.bold``). **No column-alignment support**:
  ``:---``/``:---:``/``---:`` markers are parsed by the grammar but
  ``token.align`` (``th_open``/``td_open``'s ``style="text-align:..."``
  attr here) is never read anywhere in ``renderTable`` — every column
  always left-pads.

markdown-it-py adapter notes (this port's own findings, not upstream-derived):

1. **Flat block-token stream, not a nested tree.** Unlike ``marked``'s
   already-nested ``Tokens.Table``/``Tokens.List``/etc., markdown-it-py's
   ``.parse()`` returns a flat list of ``_open``/``_close`` pairs (blocks)
   with a ``level`` int for nesting depth. ``_build_tree``/``_build_nodes``
   below do a manual recursive-descent match of open/close pairs (tracked
   generically via :func:`_find_matching_close`) to recover the nesting
   ``marked``'s token model gives upstream for free. Inline content is the
   one exception: markdown-it-py *does* populate ``inline.children`` as a
   nested list directly from ``.parse()`` — but those children are
   themselves still a *flat* run of ``strong_open``/``text``/``strong_close``
   etc. (not nested), so :func:`_render_inline` does its own local
   open/close matching for formatting spans.
2. **No blank-line token.** ``marked`` emits an explicit ``{type: "space"}``
   token for blank source lines between blocks (markdown.ts's repeated
   ``if (nextTokenType && nextTokenType !== "space") lines.push("")``
   spacing rule, e.g. lines 358-360, 368-370, 394-396, 457-459, 465-467).
   markdown-it-py has no equivalent — blank lines only show up as gaps in
   adjacent tokens' ``.map`` line-range metadata. :func:`_has_blank_between`
   derives "was there a blank line here" from those gaps instead, with a
   fallback for absorbed trailing blanks (list/ordered-list blocks swallow a
   trailing blank source line into their own ``.map`` end rather than
   leaving a real gap before the next block — verified empirically; the
   fallback re-inspects the raw source line at ``prev_map[1] - 1`` when the
   naive gap check finds none).
3. **``strict_strikethrough_plugin`` needs no custom regex engine.**
   markdown-it-py's own built-in ``"strikethrough"`` inline rule (registered
   but disabled under the ``"commonmark"`` preset) already rejects
   space-adjacent delimiters (``~~ x ~~``, ``~~x ~~``, ``~~ x~~``) exactly
   like upstream's ``STRICT_STRIKETHROUGH_REGEX``/``StrictStrikethroughTokenizer.del()``
   (markdown.ts:6-23) — confirmed empirically side by side on the same
   inputs. So :func:`strict_strikethrough_plugin` is simply
   ``md.enable(["strikethrough"])``. :data:`STRICT_STRIKETHROUGH_REGEX`
   itself is still exported as a faithful 1:1 translation of upstream's
   regex (for API/test parity and as documentation of the semantics), even
   though the production parse path relies on markdown-it-py's own
   equivalent rule rather than this regex directly.
4. **No ``InlineStyleContext``-level ``defaultTextStyle``.** Upstream's
   ``applyText``/``stylePrefix`` machinery (``getDefaultInlineStyleContext``,
   markdown.ts:320-325) exists so a user-supplied ``defaultTextStyle``
   "base" style survives across formatting-span resets. This port has no
   ``defaultTextStyle`` at all, so the *default* inline context's
   ``apply_text`` is always the identity function — but the mechanism itself
   is kept (as :class:`_InlineCtx`) because *headings* still need it: H1-H6
   wrap their own plain-text runs in the heading style function
   (``headingStyleFn``, markdown.ts:343-353), and nested formatting spans
   (bold/italic/etc. *inside* a heading) must re-open that heading style
   after their own closing codes via the same sentinel-based
   ``getStylePrefix`` trick (markdown.ts:313-318).

Deviations from upstream, beyond the interface narrowing already listed:

- Blockquote content rendering does not special-case a "no ``\\x1b[0m``
  found" branch the way ``applyQuoteStyle`` does (markdown.ts:417-423):
  since none of this port's theme functions ever emit a full ``\\x1b[0m``
  reset (only ``\\x1b[39m``/SGR-specific on-off pairs), that regex-based
  reinjection is unconditionally a no-op here, so :func:`_render_blockquote`
  just applies ``quote(italic(...))`` once per rendered block-line directly.
- ``renderTable``'s too-narrow fallback (markdown.ts:702-709) prints the
  table's raw source text via ``token.raw`` when even the minimum column
  widths don't fit. This port has no equivalent raw-text capture at the
  table-node level (the table node only carries structured header/row cell
  tokens, not the original source span), so :func:`_render_table` instead
  clamps ``available_for_cells`` up to ``num_cols`` (guaranteeing at least
  1 column of width per cell) rather than bailing out to raw text — a
  narrower, but always-render-something, fallback for this edge case
  (untested; none of this task's fixtures are narrow enough to hit it).
- Task-list checkboxes (``item.task``/``item.checked``, markdown.ts:620-622)
  are not available for free the way upstream gets them from ``marked``'s
  own GFM tokenizer: this repo's ``markdown-it-py`` setup has no
  ``mdit-py-plugins`` tasklist extension (a new runtime dependency, out of
  scope per this repo's frozen-dependency policy), so :func:`_extract_task_marker`
  hand-rolls detection off a list item's first paragraph's leading inline
  text instead, matching upstream's rendered ``"[ ] "``/``"[x] "`` marker
  behavior exactly (always-lowercase ``"x"``, never source-case-preserving).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ..engine.term_caps import TermCaps, hyperlink
from ..engine.utils import visible_width, wrap_text_with_ansi

__all__ = [
    "STRICT_STRIKETHROUGH_REGEX",
    "Markdown",
    "strict_strikethrough_plugin",
]

# A ``Node`` is one of this adapter's own tree shapes (heading/paragraph/
# code/list/table/blockquote/hr/html); heterogeneous by "type", so plain
# ``dict[str, Any]`` rather than a rigid dataclass/TypedDict hierarchy.
Node = dict[str, Any]

# ==============================================================================
# Strict strikethrough — markdown.ts:6-23.
# ==============================================================================

#: 1:1 translation of upstream's ``STRICT_STRIKETHROUGH_REGEX``
#: (markdown.ts:6): ``~~`` delimiters that immediately hug non-space,
#: non-tilde content on both sides (no space-adjacent loose form).
STRICT_STRIKETHROUGH_REGEX = re.compile(
    r"^(~~)(?=[^\s~])((?:\\.|[^\\])*?(?:\\.|[^\s~\\]))\1(?=[^~]|$)"
)


def strict_strikethrough_plugin(md: MarkdownIt) -> None:
    """Register strict (tight-adjacency) strikethrough on ``md``.

    See module docstring "markdown-it-py adapter notes" item 3: markdown-it-py's
    own built-in ``"strikethrough"`` inline rule already implements the same
    tight-adjacency semantics as :data:`STRICT_STRIKETHROUGH_REGEX`, so
    enabling it is sufficient — no custom rule needed.
    """
    md.enable(["strikethrough"])


def _make_parser() -> MarkdownIt:
    """GFM-like preset: commonmark + tables + strict strikethrough + linkify."""
    md = MarkdownIt("commonmark", {"linkify": True})
    strict_strikethrough_plugin(md)
    md.enable(["table", "linkify"])
    return md


_PARSER = _make_parser()


def _parse(source: str) -> list[Token]:
    """Stage 1: source -> markdown-it-py's flat open/close token stream."""
    return _PARSER.parse(source)


# ==============================================================================
# Theme constants — pi's real default (dark) theme. See module docstring
# "Theme constants" section for the full citation chain.
# ==============================================================================

_FG_RESET = "\x1b[39m"  # theme.ts:354 — foreground-only reset.

_BOLD_ON, _BOLD_OFF = "\x1b[1m", "\x1b[22m"
_ITALIC_ON, _ITALIC_OFF = "\x1b[3m", "\x1b[23m"
_UNDERLINE_ON, _UNDERLINE_OFF = "\x1b[4m", "\x1b[24m"
_STRIKE_ON, _STRIKE_OFF = "\x1b[9m", "\x1b[29m"

_HEADING_FG = "\x1b[38;2;240;198;116m"  # dark.json:47 mdHeading "#f0c674"
_LINK_FG = "\x1b[38;2;129;162;190m"  # dark.json:48 mdLink "#81a2be"
_LINK_URL_FG = "\x1b[38;2;102;102;102m"  # dark.json:49,12 mdLinkUrl=dimGray "#666666"
_CODE_FG = "\x1b[38;2;138;190;183m"  # dark.json:50,14 mdCode=accent "#8abeb7"
_CODE_BLOCK_FG = "\x1b[38;2;181;189;104m"  # dark.json:51,7 mdCodeBlock=green "#b5bd68"
_CODE_BLOCK_BORDER_FG = "\x1b[38;2;128;128;128m"  # dark.json:52,11 mdCodeBlockBorder=gray
_QUOTE_FG = "\x1b[38;2;128;128;128m"  # dark.json:53 mdQuote=gray
_QUOTE_BORDER_FG = "\x1b[38;2;128;128;128m"  # dark.json:54 mdQuoteBorder=gray
_HR_FG = "\x1b[38;2;128;128;128m"  # dark.json:55 mdHr=gray
_LIST_BULLET_FG = "\x1b[38;2;138;190;183m"  # dark.json:56,14 mdListBullet=accent


def _fg(color: str, text: str) -> str:
    """``Theme.fg(color, text)`` (theme.ts:351-354)."""
    return f"{color}{text}{_FG_RESET}"


def _bold(text: str) -> str:
    return f"{_BOLD_ON}{text}{_BOLD_OFF}"


def _italic(text: str) -> str:
    return f"{_ITALIC_ON}{text}{_ITALIC_OFF}"


def _underline(text: str) -> str:
    return f"{_UNDERLINE_ON}{text}{_UNDERLINE_OFF}"


def _strikethrough(text: str) -> str:
    return f"{_STRIKE_ON}{text}{_STRIKE_OFF}"


def _heading(text: str) -> str:
    return _fg(_HEADING_FG, text)


def _link(text: str) -> str:
    return _fg(_LINK_FG, text)


def _link_url(text: str) -> str:
    return _fg(_LINK_URL_FG, text)


def _code(text: str) -> str:
    return _fg(_CODE_FG, text)


def _code_block(text: str) -> str:
    return _fg(_CODE_BLOCK_FG, text)


def _code_block_border(text: str) -> str:
    return _fg(_CODE_BLOCK_BORDER_FG, text)


def _quote(text: str) -> str:
    return _fg(_QUOTE_FG, text)


def _quote_border(text: str) -> str:
    return _fg(_QUOTE_BORDER_FG, text)


def _hr_style(text: str) -> str:
    return _fg(_HR_FG, text)


def _list_bullet(text: str) -> str:
    return _fg(_LIST_BULLET_FG, text)


def _heading_style_h1(text: str) -> str:
    """H1 = ``heading(bold(underline(text)))`` (markdown.ts:344-345)."""
    return _heading(_bold(_underline(text)))


def _heading_style_default(text: str) -> str:
    """H2-H6 = ``heading(bold(text))`` (markdown.ts:347)."""
    return _heading(_bold(text))


# ==============================================================================
# Stage 2: flat token stream -> nested node tree.
# ==============================================================================


def _find_matching_close(
    tokens: list[Token], open_idx: int, open_type: str, close_type: str
) -> int:
    """Index of the ``close_type`` token matching ``tokens[open_idx]``,
    depth-counting solely on ``open_type``/``close_type`` occurrences (safe
    for well-formed, properly-nested markdown-it-py token streams even when
    other token types intervene)."""
    depth = 1
    i = open_idx + 1
    n = len(tokens)
    while i < n:
        if tokens[i].type == open_type:
            depth += 1
        elif tokens[i].type == close_type:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def _token_map(tok: Token) -> list[int]:
    return list(tok.map) if tok.map is not None else [0, 0]


def _item_is_loose(item_tokens: list[Token]) -> bool:
    """Whether this list item's own (direct) paragraph is non-hidden, i.e.
    the enclosing list is "loose" (markdown.ts ``token.loose``, list rendering
    at markdown.ts:648-650). markdown-it-py marks tight-list paragraphs
    ``hidden=True``; only the item's own *first* direct block is consulted
    (module docstring adapter note 1 — nested blocks inside the item, e.g. a
    blockquote's own paragraphs, are never "hidden" regardless of the outer
    list's tightness, so they must not be consulted here)."""
    if item_tokens and item_tokens[0].type == "paragraph_open":
        return not item_tokens[0].hidden
    return False


def _build_table_node(tokens: list[Token], table_open_idx: int) -> tuple[Node, int]:
    """Rebuild a flat ``table_open/thead_open/tr_open/th_open/inline/th_close/
    .../tbody_open?/.../table_close`` span into ``{"type": "table", "header":
    [[Token,...],...], "rows": [[[Token,...],...],...]}`` (markdown.ts:685
    ``renderTable``'s ``Tokens.Table.header``/``.rows`` shape)."""
    open_tok = tokens[table_open_idx]
    i = table_open_idx + 1

    header: list[list[Token]] = []
    i += 1  # thead_open
    i += 1  # tr_open
    while tokens[i].type == "th_open":
        i += 1  # th_open
        inline_tok = tokens[i]
        header.append(list(inline_tok.children) if inline_tok.children else [])
        i += 1  # inline
        i += 1  # th_close
    i += 1  # tr_close
    i += 1  # thead_close

    rows: list[list[list[Token]]] = []
    if i < len(tokens) and tokens[i].type == "tbody_open":
        i += 1  # tbody_open
        while tokens[i].type == "tr_open":
            i += 1  # tr_open
            row: list[list[Token]] = []
            while tokens[i].type == "td_open":
                i += 1  # td_open
                inline_tok = tokens[i]
                row.append(list(inline_tok.children) if inline_tok.children else [])
                i += 1  # inline
                i += 1  # td_close
            i += 1  # tr_close
            rows.append(row)
        i += 1  # tbody_close
    i += 1  # table_close

    node: Node = {"type": "table", "header": header, "rows": rows, "map": _token_map(open_tok)}
    return node, i


def _build_nodes(tokens: list[Token]) -> list[Node]:
    """Recursive-descent adapter: flat open/close token stream -> nested
    ``Node`` list (module docstring adapter note 1)."""
    nodes: list[Node] = []
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]

        if tok.type == "heading_open":
            level = int(tok.tag[1:]) if len(tok.tag) > 1 and tok.tag[1:].isdigit() else 1
            inline_tok = tokens[i + 1]
            nodes.append(
                {
                    "type": "heading",
                    "level": level,
                    "inline": list(inline_tok.children) if inline_tok.children else [],
                    "map": _token_map(tok),
                }
            )
            i += 3  # heading_open, inline, heading_close
            continue

        if tok.type == "paragraph_open":
            inline_tok = tokens[i + 1]
            nodes.append(
                {
                    "type": "paragraph",
                    "inline": list(inline_tok.children) if inline_tok.children else [],
                    "map": _token_map(tok),
                }
            )
            i += 3  # paragraph_open, inline, paragraph_close
            continue

        if tok.type == "fence":
            nodes.append(
                {
                    "type": "code",
                    "content": tok.content,
                    "lang": (tok.info or "").strip(),
                    "map": _token_map(tok),
                }
            )
            i += 1
            continue

        if tok.type == "hr":
            nodes.append({"type": "hr", "map": _token_map(tok)})
            i += 1
            continue

        if tok.type in ("bullet_list_open", "ordered_list_open"):
            ordered = tok.type == "ordered_list_open"
            close_type = "ordered_list_close" if ordered else "bullet_list_close"
            start_attr = tok.attrs.get("start", 1) if ordered else 1
            start = int(start_attr) if isinstance(start_attr, (int, float)) else 1
            list_map = _token_map(tok)

            items: list[list[Node]] = []
            loose = False
            i += 1
            while tokens[i].type != close_type:
                item_close_idx = _find_matching_close(
                    tokens, i, "list_item_open", "list_item_close"
                )
                item_tokens = tokens[i + 1 : item_close_idx]
                if _item_is_loose(item_tokens):
                    loose = True
                items.append(_build_nodes(item_tokens))
                i = item_close_idx + 1
            i += 1  # close_type

            nodes.append(
                {
                    "type": "list",
                    "ordered": ordered,
                    "start": start,
                    "items": items,
                    "loose": loose,
                    "map": list_map,
                }
            )
            continue

        if tok.type == "blockquote_open":
            close_idx = _find_matching_close(tokens, i, "blockquote_open", "blockquote_close")
            children = _build_nodes(tokens[i + 1 : close_idx])
            nodes.append({"type": "blockquote", "children": children, "map": _token_map(tok)})
            i = close_idx + 1
            continue

        if tok.type == "table_open":
            node, next_i = _build_table_node(tokens, i)
            nodes.append(node)
            i = next_i
            continue

        if tok.type == "html_block":
            nodes.append({"type": "html", "content": tok.content, "map": _token_map(tok)})
            i += 1
            continue

        # Unrecognized/self-closing block token (e.g. a stray close token
        # when called on a sub-slice, or an unsupported block type): skip.
        i += 1

    return nodes


def _build_tree(tokens: list[Token]) -> list[Node]:
    """Stage 2 entry point: flat token stream -> nested ``Node`` list."""
    return _build_nodes(tokens)


# ==============================================================================
# Block-gap ("was there a blank source line here") detection — module
# docstring adapter note 2.
# ==============================================================================


def _has_blank_between(prev_map: list[int], next_map: list[int], src_lines: list[str]) -> bool:
    prev_end = prev_map[1]
    next_start = next_map[0]
    if prev_end < next_start:
        return True
    if prev_end == next_start and 0 < prev_end <= len(src_lines):
        return src_lines[prev_end - 1].strip() == ""
    return False


# ==============================================================================
# Inline rendering — Stage 3, inline half. markdown.ts:492-589
# ``renderInlineTokens``, adapted for markdown-it-py's flat inline children
# (module docstring adapter note 1).
# ==============================================================================


@dataclass
class _InlineCtx:
    """Mirrors upstream's ``InlineStyleContext`` (markdown.ts:105-108). See
    module docstring adapter note 4 for why this still exists despite this
    port having no ``defaultTextStyle``."""

    apply_text: Callable[[str], str]
    style_prefix: str
    caps: TermCaps


def _style_prefix(style_fn: Callable[[str], str]) -> str:
    """``getStylePrefix`` (markdown.ts:313-318): the ANSI-open-code prefix a
    style function wraps around its input, found via a sentinel probe."""
    sentinel = "\u0000"
    styled = style_fn(sentinel)
    idx = styled.find(sentinel)
    return styled[:idx] if idx >= 0 else ""


def _default_ctx(caps: TermCaps) -> _InlineCtx:
    return _InlineCtx(apply_text=lambda text: text, style_prefix="", caps=caps)


def _heading_ctx(level: int, caps: TermCaps) -> _InlineCtx:
    style_fn = _heading_style_h1 if level == 1 else _heading_style_default
    return _InlineCtx(apply_text=style_fn, style_prefix=_style_prefix(style_fn), caps=caps)


def _apply_with_newlines(text: str, ctx: _InlineCtx) -> str:
    return "\n".join(ctx.apply_text(segment) for segment in text.split("\n"))


def _plain_text(tokens: list[Token]) -> str:
    """Raw (unstyled) text content of a flat inline-token slice — used only
    for the link-text-vs-href equality check (markdown.ts:550), mirroring
    upstream's comparison against ``token.text`` rather than styled output."""
    parts: list[str] = []
    for t in tokens:
        if t.type == "text":
            parts.append(t.content)
        elif t.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif t.type == "code_inline":
            parts.append(t.content)
    return "".join(parts)


_INLINE_SPAN_CLOSE = {
    "strong_open": "strong_close",
    "em_open": "em_close",
    "s_open": "s_close",
    "link_open": "link_close",
}


def _render_inline(tokens: list[Token], ctx: _InlineCtx) -> str:
    """``renderInlineTokens`` (markdown.ts:492-589), adapted for
    markdown-it-py's flat inline-children stream (module docstring adapter
    note 1): formatting spans are matched locally via
    :func:`_find_matching_close` instead of walking an already-nested tree."""
    result = ""
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]

        if tok.type == "text":
            result += _apply_with_newlines(tok.content, ctx)
            i += 1
            continue

        if tok.type in ("softbreak", "hardbreak"):
            result += "\n"
            i += 1
            continue

        if tok.type == "code_inline":
            result += _code(tok.content) + ctx.style_prefix
            i += 1
            continue

        if tok.type == "html_inline":
            result += _apply_with_newlines(tok.content, ctx)
            i += 1
            continue

        close_type = _INLINE_SPAN_CLOSE.get(tok.type)
        if close_type is not None:
            close_idx = _find_matching_close(tokens, i, tok.type, close_type)
            inner_tokens = tokens[i + 1 : close_idx]

            if tok.type == "strong_open":
                inner_text = _render_inline(inner_tokens, ctx)
                result += _bold(inner_text) + ctx.style_prefix
            elif tok.type == "em_open":
                inner_text = _render_inline(inner_tokens, ctx)
                result += _italic(inner_text) + ctx.style_prefix
            elif tok.type == "s_open":
                inner_text = _render_inline(inner_tokens, ctx)
                result += _strikethrough(inner_text) + ctx.style_prefix
            else:  # link_open
                href_attr = tok.attrs.get("href", "")
                href = href_attr if isinstance(href_attr, str) else ""
                inner_text = _render_inline(inner_tokens, ctx)
                raw_text = _plain_text(inner_tokens)
                styled_text = _link(_underline(inner_text))
                if ctx.caps.hyperlinks:
                    result += hyperlink(href, styled_text, ctx.caps) + ctx.style_prefix
                else:
                    href_for_cmp = href[7:] if href.startswith("mailto:") else href
                    if raw_text == href or raw_text == href_for_cmp:
                        result += styled_text + ctx.style_prefix
                    else:
                        result += styled_text + _link_url(f" ({href})") + ctx.style_prefix

            i = close_idx + 1
            continue

        # Unrecognized inline token type (e.g. image): fall back to plain content.
        if tok.content:
            result += _apply_with_newlines(tok.content, ctx)
        i += 1

    while ctx.style_prefix and result.endswith(ctx.style_prefix):
        result = result[: -len(ctx.style_prefix)]

    return result


# ==============================================================================
# Block rendering — Stage 3, block half.
# ==============================================================================


def _render_heading(node: Node, caps: TermCaps) -> list[str]:
    """markdown.ts:336-362."""
    level: int = node["level"]
    ctx = _heading_ctx(level, caps)
    heading_text = _render_inline(node["inline"], ctx)
    if level >= 3:
        prefix = "#" * level + " "
        return [ctx.apply_text(prefix) + heading_text]
    return [heading_text]


def _render_paragraph(node: Node, caps: TermCaps) -> list[str]:
    """markdown.ts:364-372."""
    return [_render_inline(node["inline"], _default_ctx(caps))]


def _render_code(node: Node) -> list[str]:
    """markdown.ts:378-398 (minus ``highlightCode``, not part of this port's
    Produces list)."""
    content: str = node["content"]
    if content.endswith("\n"):
        content = content[:-1]
    lines = [_code_block_border(f"```{node['lang']}")]
    for code_line in content.split("\n"):
        lines.append("  " + _code_block(code_line))
    lines.append(_code_block_border("```"))
    return lines


def _render_hr(width: int) -> list[str]:
    """markdown.ts:463-464."""
    return [_hr_style("─" * min(width, 80))]


#: Hand-rolled equivalent of ``marked``'s ``listIsTask: /^\[[ xX]\] +\S/``
#: tokenizer regex (module docstring deviation note): anchored at the very
#: start of the item's leading text, requires the checkbox + at least one
#: space. Unlike ``listIsTask``, this does *not* also require the following
#: non-space char via a lookahead here — markdown-it-py splits a paragraph's
#: inline children at markup boundaries (bold/italic/code/link/...), so the
#: checkbox's own leading ``text`` token can end right after the marker
#: (e.g. ``"[ ] "`` with the real content living in a *later* sibling token
#: such as ``strong_open``); requiring ``\S`` inside this single token would
#: wrongly reject that case. The "is there real content after the marker at
#: all" check is instead done across the whole item in
#: :func:`_extract_task_marker` (``has_content``), matching ``listIsTask``'s
#: intent without its single-token blind spot.
_TASK_CHECKBOX_RE = re.compile(r"^\[([ xX])\] +")


def _extract_task_marker(item_nodes: list[Node]) -> tuple[str, list[Node]]:
    """Hand-rolled ``item.task``/``item.checked`` detection (markdown.ts:
    620-622, module docstring deviation note): this port has no
    ``mdit-py-plugins`` tasklist dependency, so a list item's task marker is
    detected directly off its first paragraph's leading inline *text* token
    (module docstring adapter note 1: inline children are a flat *run* of
    mixed token types — ``text``/``strong_open``/``text``/``strong_close``/
    etc. — split at markup boundaries, *not* always a single flat ``text``
    token; a checkbox immediately followed by bold/italic/code/link content
    lands its own ``"[ ] "`` marker in ``inline[0]`` with the real content
    starting only in a *later* sibling token, e.g. ``inline[1]`` being
    ``strong_open``).

    Returns ``("", item_nodes)`` unchanged when the item isn't a paragraph,
    has no inline text, that text doesn't start with a checkbox marker, or
    there is no real (non-whitespace) content anywhere after the marker
    (checked via ``has_content`` below: either left over in ``inline[0]``'s
    own remainder, or carried by a later inline token, or by a later item
    node — mirroring ``marked``'s ``listIsTask: /^\\[[ xX]\\] +\\S/`` trailing
    ``\\S`` requirement without needing it all inside one token). Otherwise
    returns the rendered marker (``"[ ] "``/``"[x] "``, always lowercase
    regardless of source case — markdown.ts:620) plus a *new* item-node list
    with the leading marker text stripped from a *copy* of the first
    paragraph's first inline token (the original ``Token``/``Node`` is left
    untouched)."""
    if not item_nodes or item_nodes[0]["type"] != "paragraph":
        return "", item_nodes
    inline: list[Token] = item_nodes[0]["inline"]
    if not inline or inline[0].type != "text":
        return "", item_nodes
    match = _TASK_CHECKBOX_RE.match(inline[0].content)
    if match is None:
        return "", item_nodes

    remainder = inline[0].content[match.end() :]
    has_content = remainder.strip() != "" or len(inline) > 1 or len(item_nodes) > 1
    if not has_content:
        return "", item_nodes

    checked = match.group(1) != " "
    task_marker = f"[{'x' if checked else ' '}] "
    new_first_text = inline[0].copy(content=remainder)
    new_paragraph: Node = {**item_nodes[0], "inline": [new_first_text, *inline[1:]]}
    return task_marker, [new_paragraph, *item_nodes[1:]]


def _render_list(node: Node, depth: int, width: int, caps: TermCaps) -> list[str]:
    """``renderList`` (markdown.ts:604-654)."""
    lines: list[str] = []
    indent = "    " * depth
    ordered: bool = node["ordered"]
    start: int = node["start"]
    items: list[list[Node]] = node["items"]
    n_items = len(items)

    for idx, item_nodes in enumerate(items):
        is_last = idx == n_items - 1
        bullet = f"{start + idx}. " if ordered else "- "
        task_marker, item_nodes = _extract_task_marker(item_nodes)
        marker = bullet + task_marker  # markdown.ts:621 `const marker = bullet + taskMarker`
        first_prefix = indent + _list_bullet(marker)
        continuation_prefix = indent + " " * visible_width(marker)
        item_width = max(1, width - visible_width(first_prefix))
        rendered_any_line = False

        for child in item_nodes:
            if child["type"] == "list":
                # Nested lists recurse at the *original* width (markdown.ts:629),
                # not itemWidth — their own indent already shrinks their budget.
                lines.extend(_render_list(child, depth + 1, width, caps))
                rendered_any_line = True
                continue

            item_lines = _render_node(child, item_width, caps, [])
            for line in item_lines:
                for wrapped in wrap_text_with_ansi(line, item_width):
                    prefix = continuation_prefix if rendered_any_line else first_prefix
                    lines.append(prefix + wrapped)
                    rendered_any_line = True

        if not rendered_any_line:
            lines.append(first_prefix)

        if node["loose"] and not is_last:
            lines.append("")

    return lines


def _render_blockquote(node: Node, width: int, caps: TermCaps, src_lines: list[str]) -> list[str]:
    """``case "blockquote"`` (markdown.ts:414-461). See module docstring
    "Deviations" for why ``applyQuoteStyle``'s ``\\x1b[0m``-reinjection branch
    collapses to a plain ``quote(italic(...))`` wrap here."""
    quote_content_width = max(1, width - 2)
    children: list[Node] = node["children"]
    rendered_quote_lines = _render_blocks(children, src_lines, quote_content_width, caps)

    while rendered_quote_lines and rendered_quote_lines[-1] == "":
        rendered_quote_lines.pop()

    lines: list[str] = []
    for quote_line in rendered_quote_lines:
        styled_line = _quote(_italic(quote_line))
        for wrapped in wrap_text_with_ansi(styled_line, quote_content_width):
            lines.append(_quote_border("│ ") + wrapped)
    return lines


_TABLE_MAX_UNBROKEN_WORD_WIDTH = 30


def _longest_word_width(text: str, max_width: int | None = None) -> int:
    """``getLongestWordWidth`` (markdown.ts:659-669)."""
    words = [w for w in re.split(r"\s+", text) if w]
    longest = max((visible_width(w) for w in words), default=0)
    if max_width is None:
        return longest
    return min(longest, max_width)


def _wrap_cell_text(text: str, max_width: int) -> list[str]:
    """``wrapCellText`` (markdown.ts:677-679)."""
    return wrap_text_with_ansi(text, max(1, max_width))


def _render_table(node: Node, available_width: int, caps: TermCaps) -> list[str]:
    """``renderTable`` (markdown.ts:685-857). See module docstring
    "Deviations" for the too-narrow-fallback simplification."""
    header: list[list[Token]] = node["header"]
    rows: list[list[list[Token]]] = node["rows"]
    num_cols = len(header)
    if num_cols == 0:
        return []

    ctx = _default_ctx(caps)
    header_texts = [_render_inline(cell, ctx) for cell in header]
    row_texts: list[list[str]] = [[_render_inline(cell, ctx) for cell in row] for row in rows]

    border_overhead = 3 * num_cols + 1
    # Deviation: clamp rather than falling back to raw source text (see
    # module docstring) — guarantees at least 1 column of width per cell.
    available_for_cells = max(available_width - border_overhead, num_cols)

    natural_widths = [visible_width(t) for t in header_texts]
    min_word_widths = [
        max(1, _longest_word_width(t, _TABLE_MAX_UNBROKEN_WORD_WIDTH)) for t in header_texts
    ]
    for texts in row_texts:
        for i, text in enumerate(texts):
            natural_widths[i] = max(natural_widths[i], visible_width(text))
            min_word_widths[i] = max(
                min_word_widths[i], _longest_word_width(text, _TABLE_MAX_UNBROKEN_WORD_WIDTH)
            )

    min_column_widths = list(min_word_widths)
    min_cells_width = sum(min_column_widths)

    if min_cells_width > available_for_cells:
        min_column_widths = [1] * num_cols
        remaining = available_for_cells - num_cols
        if remaining > 0:
            total_weight = sum(max(0, w - 1) for w in min_word_widths)
            growth = [
                int((max(0, w - 1) / total_weight) * remaining) if total_weight > 0 else 0
                for w in min_word_widths
            ]
            for i in range(num_cols):
                min_column_widths[i] += growth[i]
            leftover = remaining - sum(growth)
            i = 0
            while leftover > 0 and i < num_cols:
                min_column_widths[i] += 1
                leftover -= 1
                i += 1
        min_cells_width = sum(min_column_widths)

    total_natural_width = sum(natural_widths) + border_overhead
    column_widths: list[int]
    if total_natural_width <= available_width:
        column_widths = [max(natural_widths[i], min_column_widths[i]) for i in range(num_cols)]
    else:
        total_grow_potential = sum(
            max(0, natural_widths[i] - min_column_widths[i]) for i in range(num_cols)
        )
        extra_width = max(0, available_for_cells - min_cells_width)
        column_widths = []
        for i in range(num_cols):
            min_width = min_column_widths[i]
            min_width_delta = max(0, natural_widths[i] - min_width)
            grow = (
                int((min_width_delta / total_grow_potential) * extra_width)
                if total_grow_potential > 0
                else 0
            )
            column_widths.append(min_width + grow)
        remaining = available_for_cells - sum(column_widths)
        while remaining > 0:
            grew = False
            for i in range(num_cols):
                if remaining <= 0:
                    break
                if column_widths[i] < natural_widths[i]:
                    column_widths[i] += 1
                    remaining -= 1
                    grew = True
            if not grew:
                break

    lines: list[str] = []
    lines.append("┌─" + "─┬─".join("─" * w for w in column_widths) + "─┐")

    header_cell_lines = [
        _wrap_cell_text(text, column_widths[i]) for i, text in enumerate(header_texts)
    ]
    header_line_count = max((len(c) for c in header_cell_lines), default=0)
    for line_idx in range(header_line_count):
        parts = []
        for col_idx, cell_lines in enumerate(header_cell_lines):
            text = cell_lines[line_idx] if line_idx < len(cell_lines) else ""
            padded = text + " " * max(0, column_widths[col_idx] - visible_width(text))
            parts.append(_bold(padded))
        lines.append("│ " + " │ ".join(parts) + " │")

    separator_line = "├─" + "─┼─".join("─" * w for w in column_widths) + "─┤"
    lines.append(separator_line)

    for row_index, texts in enumerate(row_texts):
        row_cell_lines = [_wrap_cell_text(text, column_widths[i]) for i, text in enumerate(texts)]
        row_line_count = max((len(c) for c in row_cell_lines), default=0)
        for line_idx in range(row_line_count):
            parts = []
            for col_idx, cell_lines in enumerate(row_cell_lines):
                text = cell_lines[line_idx] if line_idx < len(cell_lines) else ""
                parts.append(text + " " * max(0, column_widths[col_idx] - visible_width(text)))
            lines.append("│ " + " │ ".join(parts) + " │")
        if row_index < len(row_texts) - 1:
            lines.append(separator_line)

    lines.append("└─" + "─┴─".join("─" * w for w in column_widths) + "─┘")
    return lines


def _render_node(node: Node, width: int, caps: TermCaps, src_lines: list[str]) -> list[str]:
    ntype = node["type"]
    if ntype == "heading":
        return _render_heading(node, caps)
    if ntype == "paragraph":
        return _render_paragraph(node, caps)
    if ntype == "code":
        return _render_code(node)
    if ntype == "list":
        return _render_list(node, 0, width, caps)
    if ntype == "table":
        return _render_table(node, width, caps)
    if ntype == "blockquote":
        return _render_blockquote(node, width, caps, src_lines)
    if ntype == "hr":
        return _render_hr(width)
    if ntype == "html":
        content = str(node.get("content", "")).strip()
        return [content] if content else []
    return []


def _render_blocks(
    nodes: list[Node], src_lines: list[str], width: int, caps: TermCaps
) -> list[str]:
    """Render a sibling block list, inserting a single blank line wherever the
    source had one between two adjacent blocks (module docstring adapter
    note 2), mirroring upstream's per-token-type ``nextTokenType`` spacing
    checks with one generic, more-accurate rule."""
    lines: list[str] = []
    n = len(nodes)
    for idx, node in enumerate(nodes):
        lines.extend(_render_node(node, width, caps, src_lines))
        if idx < n - 1 and _has_blank_between(node["map"], nodes[idx + 1]["map"], src_lines):
            lines.append("")
    return lines


class Markdown:
    """``Component``-compatible: renders a markdown ``source`` string to
    pi-styled ANSI terminal lines (markdown.ts ``render``, lines 151-241,
    minus the padding/background/cache machinery — see module docstring)."""

    def __init__(self, source: str, caps: TermCaps) -> None:
        self.source = source
        self.caps = caps

    def invalidate(self) -> None:
        """No cached render state to invalidate (this port carries no
        perf-oriented render cache — see module docstring deviations)."""

    def render(self, width: int) -> list[str]:
        width = max(1, width)

        if not self.source or not self.source.strip():
            return []

        normalized = self.source.replace("\t", "   ")
        tokens = _parse(normalized)
        nodes = _build_tree(tokens)
        src_lines = normalized.split("\n")

        rendered_lines = _render_blocks(nodes, src_lines, width, self.caps)

        wrapped: list[str] = []
        for line in rendered_lines:
            wrapped.extend(wrap_text_with_ansi(line, width))

        return wrapped if wrapped else [""]
