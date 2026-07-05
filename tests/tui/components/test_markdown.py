"""RED-phase golden-line tests for the ``markdown.py`` component (task 14).

Target: ``pipython.tui.components.markdown.Markdown(source: str, caps: TermCaps)``
— narrowed per ``.superpowers/sdd/task-14-brief.md`` from upstream's
``Markdown(text, paddingX, paddingY, theme, defaultTextStyle?, options?)``
constructor (``~/Developer/nukcole-pi/packages/tui/src/components/
markdown.ts``, 858 lines) to just ``(source, caps)``:

- No ``paddingX``/``paddingY`` — this port always renders at ``padding=0``
  (content width == render width), matching the ``Box`` narrowing precedent
  (``src/pipython/tui/components/box.py`` docstring deviation 1-2).
- No injectable ``MarkdownTheme``/``defaultTextStyle``/``MarkdownOptions`` —
  styling is pi's *real* default (dark) theme, fixed at the top of this test
  file (``_Theme`` below) exactly like ``select_list.py``'s
  ``PiDefaultTheme`` precedent (``tests/tui/components/test_select_list.py``):
  no ordered-list-marker/backslash-escape preservation options either
  (ordered lists always renumber from ``token.start``, matching upstream's
  own *default* — non-``preserveOrderedListMarkers`` — behavior).
- ``caps: TermCaps`` (Task 2, ``src/pipython/tui/engine/term_caps.py``) gates
  *only* the OSC-8 hyperlink branch (``caps.hyperlinks``), mirroring
  upstream's ``getCapabilities().hyperlinks`` check at markdown.ts:540. Per
  the established convention in this codebase (``select_list.py`` has no
  ``caps`` parameter at all and hardcodes truecolor ANSI unconditionally),
  ``caps.true_color`` is *not* consulted anywhere — all theme colors below
  are fixed truecolor (``\\x1b[38;2;R;G;Bm``) sequences regardless of caps.

Style derivation (pi's real default theme, not invented — same citation
chain as task-10's ``select_list.py`` GREEN-phase fix):

- ``getMarkdownTheme()`` (``~/Developer/nukcole-pi/packages/coding-agent/
  src/modes/interactive/theme/theme.ts:1220-1251``) wires every markdown
  theme function to ``theme.fg(<colorKey>, text)`` except ``bold``/
  ``italic``/``underline`` (-> ``chalk.bold``/``chalk.italic``/
  ``chalk.underline``) and ``strikethrough`` (-> ``chalk.strikethrough``,
  theme.ts:1235) — note upstream's own ``getMarkdownTheme`` binds
  ``strikethrough`` directly to ``chalk.strikethrough``, *not* through
  ``theme.fg``, so it carries no color, only the SGR 9/29 pair.
- ``Theme.fg(color, text)`` (theme.ts:351-354): returns
  ``f"{ansi}{text}\\x1b[39m"`` — a *foreground-only* reset (``\\x1b[39m``),
  never the full ``\\x1b[0m``.
- ``fgAnsi`` truecolor branch (theme.ts:260-266): a ``#rrggbb`` hex color
  renders as ``\\x1b[38;2;R;G;Bm``.
- Default dark theme (``~/Developer/nukcole-pi/packages/coding-agent/src/
  modes/interactive/theme/dark.json``), ``vars`` (lines 7, 11, 12, 14) and
  the ``colors.md*`` block (lines 47-56):
  ``mdHeading="#f0c674"``, ``mdLink="#81a2be"``, ``mdLinkUrl=dimGray=
  "#666666"``, ``mdCode=accent="#8abeb7"``, ``mdCodeBlock=green="#b5bd68"``,
  ``mdCodeBlockBorder=gray="#808080"``, ``mdQuote=gray``,
  ``mdQuoteBorder=gray``, ``mdHr=gray``, ``mdListBullet=accent``.
- ``chalk``'s ``bold``/``italic``/``underline``/``strikethrough`` are plain,
  well-known SGR on/off pairs — verified directly against the vendored
  ansi-styles table pi's own ``chalk`` dependency ships
  (``~/Developer/nukcole-pi/node_modules/chalk/source/vendor/ansi-styles/
  index.js:13,15,16,18,20``): bold=[1,22], italic=[3,23],
  underline=[4,24], strikethrough=[9,29]. Chalk's ``applyStyle`` (chalk
  ``source/index.js:168-193``) wraps as plain ``open + string + close``
  when the wrapped string carries no ANSI matching that style's own close
  code (true for every composition exercised below — verified by
  inspection, not assumed).

Golden values below were computed with a throwaway oracle script
(``/private/tmp/.../scratchpad/oracle.py``, not part of this repo) that
imports the *real*, already-merged ``pipython.tui.engine.utils.
visible_width``/``wrap_text_with_ansi`` (Task 1) to get exact width/wrap
math (table column widths with CJK cells, ANSI-aware line wrapping) —
this is the same "derive golden bytes with real helper functions, then
transcribe" technique task-10's GREEN phase used
(``.superpowers/sdd/task-10-report.md``, "GREEN phase" section), just run
here at RED time since ``utils.py``/``term_caps.py`` (this component's own
dependencies) already exist and are trustworthy oracles for width/wrap/
hyperlink math, even though ``Markdown`` itself does not exist yet.

Two heads-up notes from earlier tasks, both exercised below:

1. tmux forces ``hyperlinks=False`` unconditionally (a pure-function
   contract — ``term_caps.py`` lines 57-60, ``detect_caps`` never probes
   tmux's actual OSC-8 forwarding). ``TestOSC8TwoStates`` injects ``caps``
   with both ``hyperlinks`` states directly, plus one test that goes
   through ``detect_caps({"TMUX": "1"})`` end-to-end to prove the tmux ->
   ``False`` -> parenthetical-fallback chain holds all the way through
   ``Markdown.render()``.
2. ``markdown-it-py`` needs a gfm-like preset (``table``/``strikethrough``
   enabled on top of ``"commonmark"``, plus ``linkify-it-py`` wired in) and
   its token stream is flat open/close pairs (``table_open``/``thead_open``/
   ``tr_open``/``th_open``/``inline``/``th_close``/...), unlike upstream's
   nested ``marked`` token tree (``Tokens.Table.header``/``.rows`` are
   already nested arrays) — verified empirically against the real,
   installed ``markdown_it`` (see ``TestBuildTreeAdapter`` below, which
   feeds real ``MarkdownIt("commonmark").enable(["table"]).parse(...)``
   output directly into ``_build_tree`` and asserts the resulting nested
   ``{"type": "table", "header": [...], "rows": [...]}`` shape).

A third, self-discovered heads-up worth recording for the GREEN
implementer: markdown-it-py's block parser has **no equivalent of
upstream ``marked``'s explicit ``{type: "space"}`` blank-line token** —
blank lines between blocks are not their own token in the flat stream (they
only show up implicitly via the gap between adjacent tokens'
``.map`` line-range metadata). markdown.ts's spacing rule
(``if (nextTokenType && nextTokenType !== "space") lines.push("")``,
repeated at lines 358-360, 368-370, 394-396, 457-459, 465-467) is therefore
not a direct token-type check in this port — ``_build_tree``/``_render_node``
must derive "was there a blank source line here" from ``token.map`` gaps
instead. This file's assertions pin only the *observable*
``Markdown.render()`` output (exactly one blank rendered line between
blocks, none at the very start/end of the document), not the internal
mechanism, so either translation strategy satisfies these tests.

Also verified empirically (informs ``TestStrictStrikethroughPlugin``/
``TestStrictStrikethroughRegex`` below): markdown-it-py already ships a
built-in ``"strikethrough"`` inline rule (registered but disabled under the
``"commonmark"`` preset — see ``.venv/.../markdown_it/rules_inline/
strikethrough.py``) whose default (non-``strikethrough_single_tilde``) mode
already rejects space-adjacent delimiters (``~~ x ~~``, ``~~x ~~``,
``~~ x~~``) exactly like upstream's ``STRICT_STRIKETHROUGH_REGEX``
(translated 1:1 from ``marked``'s ``StrictStrikethroughTokenizer.del()``
regex, markdown.ts:6) — confirmed by running both side by side on the same
inputs. So the simplest correct ``strict_strikethrough_plugin`` is just
``md.enable(["strikethrough"])``; this file's tests assert only the
*observable* token stream (``s_open``/``text``/``s_close``, markdown-it's
own established type names for this rule), not that specific mechanism, so
a from-scratch override rule is equally acceptable as long as it produces
the same token shape.

Upstream markdown.ts citations used throughout:
- Heading: lines 336-362 (H1 = heading+bold+underline; H2-H6 = heading+bold;
  H3+ additionally renders a separately-wrapped ``"### "`` marker prefix,
  line 356).
- List: lines 604-654 (4-space indent per nesting depth, continuation prefix
  = spaces matching marker's visible width, tight lists renumber via
  ``token.start``).
- Code block: lines 378-398 (codeBlockBorder wraps the fence lines,
  codeBlock + 2-space indent wraps each content line, no defaultTextStyle
  or per-token wrapping beyond the generic post-process wrap).
- Blockquote: lines 414-461 (quoteBorder("│ ") prefix per rendered line,
  content wrapped in quote(italic(...)), default text style explicitly
  suppressed inside blockquotes).
- Table: lines 685-857 (``renderTable``) — column widths computed from
  ``visibleWidth`` (CJK-aware), header cells wrapped in ``theme.bold``,
  data cells unstyled, border characters (``┌─┬─┐``/``├─┼─┤``/``└─┴─┘``/
  ``│``) carry **no** theme styling at all (no ``theme.*`` call touches them
  anywhere in the function) — and critically, **no column-alignment
  support**: ``token.align``/``:---:``/``---:`` markers are parsed by the
  markdown grammar but never read anywhere in ``renderTable``, so every
  column is always left-padded regardless of alignment markers (see
  ``TestTableAlignmentIgnored``).
- Strikethrough tokenizer: markdown.ts lines 6-23 (``STRICT_STRIKETHROUGH_
  REGEX`` + ``StrictStrikethroughTokenizer.del()``).
- Link: lines 537-557 (OSC-8 hyperlink when ``caps.hyperlinks``; otherwise a
  parenthetical ``" (url)"`` fallback when text != href).
"""

from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt

from pipython.tui.components.markdown import (
    STRICT_STRIKETHROUGH_REGEX,
    Markdown,
    _build_tree,
    strict_strikethrough_plugin,
)
from pipython.tui.engine.term_caps import TermCaps, detect_caps
from pipython.tui.engine.utils import visible_width, wrap_text_with_ansi

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# ==============================================================================
# THEME ORACLE — pi's real default (dark) theme, fixed module-top constants.
# See module docstring "Style derivation" section for full citation chain.
# ==============================================================================


class _Theme:
    """Byte-exact ANSI wraps matching pi's real default markdown theme.

    Every function below is ``f"{color}{text}\\x1b[39m"`` (``Theme.fg``,
    theme.ts:351-354) with the truecolor hex from ``dark.json``, or a plain
    chalk SGR on/off pair (ansi-styles index.js:13,15,16,18,20).
    """

    FG_RESET = "\x1b[39m"
    BOLD_ON, BOLD_OFF = "\x1b[1m", "\x1b[22m"
    ITALIC_ON, ITALIC_OFF = "\x1b[3m", "\x1b[23m"
    UNDERLINE_ON, UNDERLINE_OFF = "\x1b[4m", "\x1b[24m"
    STRIKE_ON, STRIKE_OFF = "\x1b[9m", "\x1b[29m"

    _HEADING = "\x1b[38;2;240;198;116m"  # dark.json:47 mdHeading "#f0c674"
    _LINK = "\x1b[38;2;129;162;190m"  # dark.json:48 mdLink "#81a2be"
    _LINK_URL = "\x1b[38;2;102;102;102m"  # dark.json:49,12 mdLinkUrl=dimGray "#666666"
    _CODE = "\x1b[38;2;138;190;183m"  # dark.json:50,14 mdCode=accent "#8abeb7"
    _CODE_BLOCK = "\x1b[38;2;181;189;104m"  # dark.json:51,7 mdCodeBlock=green "#b5bd68"
    _CODE_BLOCK_BORDER = "\x1b[38;2;128;128;128m"  # dark.json:52,11 mdCodeBlockBorder=gray
    _QUOTE = "\x1b[38;2;128;128;128m"  # dark.json:53 mdQuote=gray
    _QUOTE_BORDER = "\x1b[38;2;128;128;128m"  # dark.json:54 mdQuoteBorder=gray
    _HR = "\x1b[38;2;128;128;128m"  # dark.json:55 mdHr=gray
    _LIST_BULLET = "\x1b[38;2;138;190;183m"  # dark.json:56,14 mdListBullet=accent

    @classmethod
    def bold(cls, text: str) -> str:
        return f"{cls.BOLD_ON}{text}{cls.BOLD_OFF}"

    @classmethod
    def italic(cls, text: str) -> str:
        return f"{cls.ITALIC_ON}{text}{cls.ITALIC_OFF}"

    @classmethod
    def underline(cls, text: str) -> str:
        return f"{cls.UNDERLINE_ON}{text}{cls.UNDERLINE_OFF}"

    @classmethod
    def strikethrough(cls, text: str) -> str:
        return f"{cls.STRIKE_ON}{text}{cls.STRIKE_OFF}"

    @classmethod
    def heading(cls, text: str) -> str:
        return f"{cls._HEADING}{text}{cls.FG_RESET}"

    @classmethod
    def link(cls, text: str) -> str:
        return f"{cls._LINK}{text}{cls.FG_RESET}"

    @classmethod
    def link_url(cls, text: str) -> str:
        return f"{cls._LINK_URL}{text}{cls.FG_RESET}"

    @classmethod
    def code(cls, text: str) -> str:
        return f"{cls._CODE}{text}{cls.FG_RESET}"

    @classmethod
    def code_block(cls, text: str) -> str:
        return f"{cls._CODE_BLOCK}{text}{cls.FG_RESET}"

    @classmethod
    def code_block_border(cls, text: str) -> str:
        return f"{cls._CODE_BLOCK_BORDER}{text}{cls.FG_RESET}"

    @classmethod
    def quote(cls, text: str) -> str:
        return f"{cls._QUOTE}{text}{cls.FG_RESET}"

    @classmethod
    def quote_border(cls, text: str) -> str:
        return f"{cls._QUOTE_BORDER}{text}{cls.FG_RESET}"

    @classmethod
    def list_bullet(cls, text: str) -> str:
        return f"{cls._LIST_BULLET}{text}{cls.FG_RESET}"


TRUE_COLOR_NO_HYPERLINKS = TermCaps(true_color=True, hyperlinks=False)
TRUE_COLOR_HYPERLINKS = TermCaps(true_color=True, hyperlinks=True)


# ==============================================================================
# HEADINGS (fixture: heading_levels.md) — markdown.ts:336-362
# ==============================================================================


class TestHeadings:
    def test_h1_is_heading_bold_underline(self):
        """H1 = ``theme.heading(theme.bold(theme.underline(text)))``,
        markdown.ts:344-345 — no ``"# "`` marker prefix rendered at all
        (only H3+ renders a marker, line 356)."""
        md = Markdown("# H1 Heading", TRUE_COLOR_NO_HYPERLINKS)
        expected = _Theme.heading(_Theme.bold(_Theme.underline("H1 Heading")))
        assert md.render(80) == [expected]

    def test_h2_is_heading_bold_only(self):
        """H2-H6 = ``theme.heading(theme.bold(text))``, markdown.ts:347 —
        no underline, still no marker prefix (headingLevel < 3)."""
        md = Markdown("## H2 Heading", TRUE_COLOR_NO_HYPERLINKS)
        expected = _Theme.heading(_Theme.bold("H2 Heading"))
        assert md.render(80) == [expected]

    def test_h3_renders_styled_marker_as_separate_span(self):
        """H3+ (markdown.ts:356): ``styledHeading = headingStyleFn(prefix)
        + headingText`` — the ``"### "`` marker and the heading text are
        two *independently* wrapped (and independently reset) spans
        concatenated, not one combined wrap."""
        md = Markdown("### H3 Heading", TRUE_COLOR_NO_HYPERLINKS)
        expected = _Theme.heading(_Theme.bold("### ")) + _Theme.heading(_Theme.bold("H3 Heading"))
        assert md.render(80) == [expected]

    def test_fixture_exact_lines_single_blank_between_headings(self):
        """Blank source lines between blocks collapse to exactly one
        rendered blank line (markdown.ts:358-360's own spacing rule is
        suppressed when the next block is a blank-line gap, so the gap
        itself contributes the single blank — no double blank, no blank at
        EOF since H3 is the last block)."""
        source = _load_fixture("heading_levels.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        h1 = _Theme.heading(_Theme.bold(_Theme.underline("H1 Heading")))
        h2 = _Theme.heading(_Theme.bold("H2 Heading"))
        h3 = _Theme.heading(_Theme.bold("### ")) + _Theme.heading(_Theme.bold("H3 Heading"))
        assert md.render(80) == [h1, "", h2, "", h3]


# ==============================================================================
# NESTED LISTS (fixture: nested_list.md) — markdown.ts:604-654
# ==============================================================================


class TestNestedList:
    def test_unordered_nested_list_block_exact_lines(self):
        """4-space indent per nesting depth (indent = ``"    ".repeat(depth)``,
        markdown.ts:606); marker "- " wrapped in ``theme.listBullet``, item
        text unstyled (no ``defaultTextStyle`` in this port's narrower
        interface); tight list (no blank source lines between items) so no
        extra blank lines between list items."""
        source = "- Item 1\n  - Nested 1.1\n  - Nested 1.2\n- Item 2"
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- ")
        expected = [
            f"{bullet}Item 1",
            f"    {bullet}Nested 1.1",
            f"    {bullet}Nested 1.2",
            f"{bullet}Item 2",
        ]
        assert md.render(80) == expected

    def test_ordered_nested_list_block_exact_lines(self):
        """Ordered markers always renumber from ``token.start`` (this
        port's interface has no ``preserveOrderedListMarkers`` option at
        all — matches upstream's own *default*, non-preserve behavior,
        markdown.ts:613-616)."""
        source = "1. First\n   1. Nested first\n   2. Nested second\n2. Second"
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        b1 = _Theme.list_bullet("1. ")
        b2 = _Theme.list_bullet("2. ")
        expected = [
            f"{b1}First",
            f"    {b1}Nested first",
            f"    {b2}Nested second",
            f"{b2}Second",
        ]
        assert md.render(80) == expected

    def test_fixture_exact_lines_single_blank_between_blocks(self):
        """Full fixture: unordered block, one blank line (the source's
        blank-line gap), ordered block — no trailing blank at EOF."""
        source = _load_fixture("nested_list.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- ")
        b1 = _Theme.list_bullet("1. ")
        b2 = _Theme.list_bullet("2. ")
        expected = [
            f"{bullet}Item 1",
            f"    {bullet}Nested 1.1",
            f"    {bullet}Nested 1.2",
            f"{bullet}Item 2",
            "",
            f"{b1}First",
            f"    {b1}Nested first",
            f"    {b2}Nested second",
            f"{b2}Second",
        ]
        assert md.render(80) == expected


# ==============================================================================
# TASK-LIST CHECKBOXES (hand-rolled, no mdit-py-plugins dep) — markdown.ts:620-622
# ==============================================================================


class TestTaskListCheckbox:
    """Upstream concatenates ``taskMarker`` (``"[ ] "``/``"[x] "``) into the
    list marker and styles the *whole* ``"- [ ] "`` prefix with
    ``theme.listBullet`` (markdown.ts:620-622: ``const taskMarker = item.task
    ? `[${item.checked ? "x" : " "}] ` : ""; const marker = bullet +
    taskMarker;``). This port has no ``mdit-py-plugins`` tasklist dependency,
    so detection is hand-rolled directly off the item's first paragraph's
    leading inline text (see module docstring deviation note)."""

    def test_unchecked_checkbox_styled_with_bullet(self):
        md = Markdown("- [ ] todo", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- [ ] ")
        assert md.render(80) == [f"{bullet}todo"]

    def test_checked_checkbox_styled_with_bullet(self):
        md = Markdown("- [x] done", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- [x] ")
        assert md.render(80) == [f"{bullet}done"]

    def test_uppercase_x_checkbox_normalizes_to_lowercase_marker(self):
        """Upstream's rendered marker is always ``item.checked ? "x" : " "``
        (lowercase literal) regardless of source case — verified against
        ``marked``'s own checked derivation (``checked: p[0] !== "[ ]"``,
        no case-preservation of the bracket content)."""
        md = Markdown("- [X] DONE", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- [x] ")
        assert md.render(80) == [f"{bullet}DONE"]

    def test_ordered_list_checkbox_also_styled(self):
        """``taskMarker`` applies to ordered lists too (markdown.ts:620-622
        reads ``item.task``/``item.checked`` regardless of ``token.ordered``)."""
        md = Markdown("1. [ ] first\n2. [x] second", TRUE_COLOR_NO_HYPERLINKS)
        b1 = _Theme.list_bullet("1. [ ] ")
        b2 = _Theme.list_bullet("2. [x] ")
        assert md.render(80) == [f"{b1}first", f"{b2}second"]

    def test_mid_text_bracket_pair_left_untouched(self):
        """A ``[ ]`` that is not the item's very first content must not be
        detected as a checkbox (upstream/marked anchors task detection at the
        item's start, ``listIsTask: /^\\[[ xX]\\] +\\S/``)."""
        md = Markdown("- todo [ ] not a checkbox", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- ")
        assert md.render(80) == [f"{bullet}todo [ ] not a checkbox"]

    def test_checkbox_followed_by_inline_markup_still_detected(self):
        """A checkbox immediately followed by inline markup (bold/italic/
        code/link/...) must still be detected, even though markdown-it-py
        splits the paragraph's inline children at that markup boundary —
        the checkbox's own leading ``text`` token ends up as exactly
        ``"[ ] "`` with no trailing ``\\S`` of its own (the real content
        lives in a *later* sibling token, e.g. ``strong_open``/``text``/
        ``strong_close``). A naive single-token ``\\S``-lookahead check
        would miss this (regression guard)."""
        md = Markdown("- [ ] **bold** rest of line", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- [ ] ")
        expected = f"{bullet}{_Theme.bold('bold')} rest of line"
        assert md.render(80) == [expected]

    def test_empty_checkbox_with_no_content_is_not_a_task(self):
        """A checkbox with nothing (or only whitespace) after it anywhere in
        the item is not a real task per GFM's trailing ``\\S`` requirement
        (``listIsTask: /^\\[[ xX]\\] +\\S/``) — rendered as a plain bullet
        with the literal ``"[ ]"`` text untouched."""
        md = Markdown("- [ ]", TRUE_COLOR_NO_HYPERLINKS)
        bullet = _Theme.list_bullet("- ")
        assert md.render(80) == [f"{bullet}[ ]"]


# ==============================================================================
# FENCED CODE (fixture: fenced_code.md) — markdown.ts:378-398
# ==============================================================================


class TestFencedCode:
    def test_fence_open_and_close_border_styling(self):
        """Fence markers (with language tag) wrapped in
        ``theme.codeBlockBorder`` (markdown.ts:380, 393)."""
        md = Markdown("```python\nx = 1\n```", TRUE_COLOR_NO_HYPERLINKS)
        lines = md.render(80)
        assert lines[0] == _Theme.code_block_border("```python")
        assert lines[-1] == _Theme.code_block_border("```")

    def test_fence_lang_trimmed_of_trailing_whitespace(self):
        """``node["lang"]`` must be ``.strip()``-ped (upstream marked's own
        ``fences()`` tokenizer trims its lang/info capture) — markdown-it-py's
        own ``tok.info`` does *not* strip trailing whitespace on its own
        (verified empirically: fencing with ``python   `` (trailing spaces)
        parses to ``tok.info == "python   "``), so an untrimmed lang would
        leak into the rendered border line."""
        md = Markdown("```python   \nx = 1\n```", TRUE_COLOR_NO_HYPERLINKS)
        lines = md.render(80)
        assert lines[0] == _Theme.code_block_border("```python")

    def test_code_content_lines_styled_and_indented(self):
        """Each content line wrapped in ``theme.codeBlock`` with the
        default 2-space ``codeBlockIndent`` prefix (markdown.ts:379, 390);
        the indent itself is a literal, unstyled prefix."""
        md = Markdown("```python\ndef add(a, b):\n    return a + b\n```", TRUE_COLOR_NO_HYPERLINKS)
        lines = md.render(80)
        assert lines[1] == "  " + _Theme.code_block("def add(a, b):")
        assert lines[2] == "  " + _Theme.code_block("    return a + b")

    def test_fixture_exact_lines_one_blank_around_code_block(self):
        """Full fixture: paragraph, one blank, fenced code (no extra
        internal empty line even though the fence's own trailing-newline
        normalization must strip the source's final ``"\\n"`` inside the
        fence content — matches upstream's ``token.text`` never carrying a
        trailing newline), one blank, paragraph — no trailing blank at
        EOF."""
        source = _load_fixture("fenced_code.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        expected = [
            "Before code.",
            "",
            _Theme.code_block_border("```python"),
            "  " + _Theme.code_block("def add(a, b):"),
            "  " + _Theme.code_block("    return a + b"),
            _Theme.code_block_border("```"),
            "",
            "After code.",
        ]
        assert md.render(80) == expected


# ==============================================================================
# BLOCKQUOTE (fixture: blockquote.md) — markdown.ts:414-461
# ==============================================================================


class TestBlockquote:
    def test_fixture_exact_two_quoted_lines_no_trailing_blank(self):
        """A 2-line lazy/explicit blockquote paragraph is ONE inline token
        whose content embeds a literal ``"\\n"`` (markdown-it's
        ``softbreak`` child token, analogous to upstream's ``br`` case at
        markdown.ts:559-561). Per markdown.ts:450-451, the quote+italic
        style wraps the *entire* (multi-line) rendered paragraph text
        ONCE — ``quoteStyle(lineWithReappliedStyle)`` — not once per
        source line; the border+styled result is only split back into 2
        physical lines afterwards, by the generic ``wrapTextWithAnsi``
        post-process splitting on ``"\\n"`` (markdown.ts:452). Concretely
        (and this is the important, non-obvious bit, confirmed by actually
        running the real, already-merged ``wrap_text_with_ansi`` — Task 1
        — on this exact input): because the opening codes sit at the very
        *start* of the whole two-line string and the closing codes
        (``\\x1b[23m\\x1b[39m``) sit at the very *end*, the wrap-emitted
        line 1 has **no trailing reset** of its own (``_wrap_single_line``
        returns a fitting line unchanged) — only line 2 carries the
        closing codes, and line 2's *opening* codes are
        ``_AnsiCodeTracker.get_active_codes()``'s own combined-SGR form
        (``\\x1b[3;38;2;128;128;128m``, italic+fg merged into one escape),
        not a replay of the two separate original opening codes. Blockquote
        is the sole/last block, so no trailing blank line (markdown.ts:457's
        ``if (nextTokenType ...)`` guard is false when there is no next
        token)."""
        source = _load_fixture("blockquote.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        full_text = "This is a quote\nspanning two lines"
        styled_whole = _Theme.quote(_Theme.italic(full_text))
        segments = wrap_text_with_ansi(styled_whole, 78)  # width(80) - border(2)
        assert len(segments) == 2, "oracle sanity: one segment per source line, no word-wrap"
        expected = [_Theme.quote_border("│ ") + seg for seg in segments]
        assert md.render(80) == expected

    def test_wrapped_blockquote_line_keeps_border_on_each_wrapped_line(self):
        """Long single-line blockquote wrapped at a narrow width: every
        wrapped segment gets its own ``quoteBorder("│ ")`` prefix
        (markdown.ts:450-455). Exact wrapped segments computed via the
        real, already-merged ``wrap_text_with_ansi`` (Task 1) as the
        oracle for the ANSI-aware word-wrap + style-reopen math — note the
        continuation lines re-open with ``wrap_text_with_ansi``'s own
        *combined* SGR form (``\\x1b[3;38;2;128;128;128m``, italic+fg in
        one escape) rather than replaying the two separate opening codes,
        which is ``_AnsiCodeTracker.get_active_codes()``'s real, already-
        tested behavior (``engine/utils.py``), not a guess."""
        long_text = "This is a very long blockquote line that should wrap here"
        md = Markdown(f"> {long_text}", TRUE_COLOR_NO_HYPERLINKS)
        styled = _Theme.quote(_Theme.italic(long_text))
        segments = wrap_text_with_ansi(styled, 28)  # width(30) - border(2)
        expected = [_Theme.quote_border("│ ") + seg for seg in segments]
        assert len(segments) == 3, "oracle sanity: expected 3 wrapped segments at width 30"
        lines = md.render(30)
        assert lines == expected
        for line in lines:
            assert visible_width(line) <= 30


# ==============================================================================
# TABLE with CJK cells (fixture: table_cjk.md) — markdown.ts:685-857
# ==============================================================================


class TestTableCJK:
    def test_fixture_exact_seven_lines_cjk_column_width(self):
        """Column widths computed from ``visibleWidth`` (CJK-aware: each of
        "备注"/"你好"/"再见" is 2 graphemes * 2 cols = 4 visible columns,
        matching "Name"'s own 4-char width so column 2 needs no extra
        growth) — natural widths [5, 4] (col 1 driven by "Alice", 5 chars).
        Header cells wrapped in ``theme.bold``; data cells unstyled. Table
        is the last/only block: no trailing blank line (markdown.ts:853's
        guard)."""
        source = _load_fixture("table_cjk.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        expected = [
            "┌───────┬──────┐",
            f"│ {_Theme.bold('Name ')} │ {_Theme.bold('备注')} │",
            "├───────┼──────┤",
            "│ Alice │ 你好 │",
            "├───────┼──────┤",
            "│ Bob   │ 再见 │",
            "└───────┴──────┘",
        ]
        assert md.render(80) == expected

    def test_table_borders_are_unstyled_plain_characters(self):
        """No ``theme.*`` call anywhere in ``renderTable`` touches border
        characters (┌─┬─┐/├─┼─┤/└─┴─┘/│) — verified by reading the full
        686-857 line range, not assumed. Only header cell *text* is bold;
        borders carry zero ANSI escapes."""
        source = _load_fixture("table_cjk.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        lines = md.render(80)
        border_lines = [lines[0], lines[2], lines[4], lines[6]]
        for line in border_lines:
            assert "\x1b" not in line, f"border line should carry no ANSI: {line!r}"


class TestTableAlignmentIgnored:
    def test_colon_alignment_markers_are_ignored_left_padded(self):
        """``:---``/``:---:``/``---:`` alignment markers are parsed by the
        markdown grammar but never consulted in ``renderTable`` (no
        ``token.align`` reference anywhere in markdown.ts:685-857) — every
        column always left-pads, so the "right-aligned" column's short
        value "C" gets *trailing* padding, not leading padding."""
        source = "| Left | Center | Right |\n| :--- | :---: | ---: |\n| A | B | C |\n"
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        expected = [
            "┌──────┬────────┬───────┐",
            f"│ {_Theme.bold('Left')} │ {_Theme.bold('Center')} │ {_Theme.bold('Right')} │",
            "├──────┼────────┼───────┤",
            "│ A    │ B      │ C     │",
            "└──────┴────────┴───────┘",
        ]
        assert md.render(80) == expected


# ==============================================================================
# MIXED CJK + strict strikethrough + link (fixture: mixed_cjk_strike_link.md)
# ==============================================================================


class TestMixedCjkStrikeLink:
    def test_fixture_exact_single_line(self):
        """One paragraph combining: plain CJK text (unstyled), a *tight*
        strikethrough ``~~严格删除线~~`` (SGR 9/29, content preserved,
        delimiters consumed), a *loose* ``~~ 非严格 ~~`` that is NOT
        strikethrough (space-adjacent, upstream's tight-adjacency regex
        rejects it — kept as literal text including both tilde pairs), and
        a markdown link rendered with the ``hyperlinks=False`` parenthetical
        fallback (text != href)."""
        source = _load_fixture("mixed_cjk_strike_link.md")
        md = Markdown(source, TRUE_COLOR_NO_HYPERLINKS)
        expected = (
            "中文文本包含 "
            + _Theme.strikethrough("严格删除线")
            + " 和 ~~ 非严格 ~~ 以及 "
            + _Theme.link(_Theme.underline("链接"))
            + _Theme.link_url(" (https://example.com)")
            + "。"
        )
        assert visible_width(re.sub(r"\x1b\[[0-9;]*m", "", expected)) <= 80, (
            "oracle sanity: line must fit width 80 unwrapped"
        )
        assert md.render(80) == [expected]

    def test_tight_strikethrough_triggers(self):
        """Minimal isolated case: ``~~x~~`` (no adjacent space) ->
        strikethrough, delimiters removed."""
        md = Markdown("~~x~~", TRUE_COLOR_NO_HYPERLINKS)
        assert md.render(80) == [_Theme.strikethrough("x")]

    def test_loose_strikethrough_stays_literal(self):
        """``~~ x ~~`` (space immediately inside both delimiters) is NOT
        strikethrough — rendered as literal, unstyled text including the
        tildes, per upstream's ``STRICT_STRIKETHROUGH_REGEX``'s
        ``(?=[^\\s~])`` / trailing-non-space requirement (markdown.ts:6)."""
        md = Markdown("~~ x ~~", TRUE_COLOR_NO_HYPERLINKS)
        assert md.render(80) == ["~~ x ~~"]


# ==============================================================================
# OSC-8 hyperlinks — two ``caps.hyperlinks`` states (markdown.ts:537-557)
# ==============================================================================


class TestOSC8TwoStates:
    LINK_SOURCE = "[click here](https://example.com)"

    def test_hyperlinks_true_emits_osc8_sequence(self):
        """``caps.hyperlinks=True``: OSC-8 wraps the styled link text; the
        raw URL is never printed inline (markdown.ts:541-543)."""
        md = Markdown(self.LINK_SOURCE, TRUE_COLOR_HYPERLINKS)
        styled_text = _Theme.link(_Theme.underline("click here"))
        expected = f"\x1b]8;;https://example.com\x1b\\{styled_text}\x1b]8;;\x1b\\"
        assert md.render(80) == [expected]

    def test_hyperlinks_false_emits_parenthetical_fallback(self):
        """``caps.hyperlinks=False``: styled link text + a
        ``theme.linkUrl(" (url)")`` parenthetical suffix, since the link
        text ("click here") differs from the href (markdown.ts:545-554)."""
        md = Markdown(self.LINK_SOURCE, TRUE_COLOR_NO_HYPERLINKS)
        styled_text = _Theme.link(_Theme.underline("click here"))
        expected = styled_text + _Theme.link_url(" (https://example.com)")
        assert md.render(80) == [expected]

    def test_tmux_env_forces_hyperlinks_false_through_render(self):
        """Heads-up note #1: tmux -> ``detect_caps`` always returns
        ``hyperlinks=False`` (a pure function over env, term_caps.py:57-60,
        no OSC-8-forwarding probe) -> ``Markdown.render()`` must take the
        same parenthetical-fallback branch as the direct
        ``hyperlinks=False`` case above, end to end through the real
        ``detect_caps`` (not a hand-built ``TermCaps``)."""
        caps = detect_caps({"TMUX": "1"})
        assert caps.hyperlinks is False
        md = Markdown(self.LINK_SOURCE, caps)
        styled_text = _Theme.link(_Theme.underline("click here"))
        expected = styled_text + _Theme.link_url(" (https://example.com)")
        assert md.render(80) == [expected]


# ==============================================================================
# _build_tree ADAPTER — direct unit tests on the flat-token-stream -> nested
# node adapter layer (heads-up note #2). Feeds *real* markdown-it-py token
# output (MarkdownIt("commonmark").enable(["table"]).parse(...)) directly
# into ``_build_tree``, bypassing ``Markdown``/``_parse`` entirely.
# ==============================================================================


def _table_tokens(source: str):
    md = MarkdownIt("commonmark").enable(["table"])
    return md.parse(source)


class TestBuildTreeAdapter:
    def test_table_token_stream_builds_header_rows_structure(self):
        """Flat ``table_open/thead_open/tr_open/th_open/inline/th_close/...
        /tbody_open/tr_open/td_open/inline/td_close/.../table_close`` stream
        (verified empirically against the real, installed markdown-it-py)
        must rebuild into ``{"type": "table", "header": [[Token,...],...],
        "rows": [[[Token,...],...],...]}`` — each cell a list of the
        inline token's *children* (parallel to upstream's
        ``Tokens.TableCell.tokens``, markdown.ts:717, 723, 808, 831)."""
        source = "| Name | 备注 |\n| --- | --- |\n| Alice | 你好 |\n| Bob | 再见 |\n"
        tokens = _table_tokens(source)
        tree = _build_tree(tokens)

        assert len(tree) == 1
        node = tree[0]
        assert node["type"] == "table"
        assert len(node["header"]) == 2

        def cell_text(cell_tokens) -> str:
            return "".join(t.content for t in cell_tokens)

        assert [cell_text(c) for c in node["header"]] == ["Name", "备注"]
        assert len(node["rows"]) == 2
        assert [cell_text(c) for c in node["rows"][0]] == ["Alice", "你好"]
        assert [cell_text(c) for c in node["rows"][1]] == ["Bob", "再见"]

    def test_table_with_zero_data_rows_builds_empty_rows_list(self):
        """A header-only table (no ``tbody_open``/``tbody_close`` tokens at
        all in the real markdown-it-py stream, verified empirically) must
        still build a table node with ``rows == []``, not crash on the
        missing tbody."""
        source = "| Name |\n| --- |\n"
        tokens = _table_tokens(source)
        tree = _build_tree(tokens)

        assert len(tree) == 1
        assert tree[0]["type"] == "table"
        assert tree[0]["rows"] == []

    def test_paragraph_then_table_preserves_block_order(self):
        """A flat stream with a leading paragraph followed by a table must
        build a 2-node list in source order — the table reconstruction is
        local to its own open/close span, it does not swallow or reorder
        preceding sibling blocks."""
        source = "Intro text.\n\n| Name |\n| --- |\n| Alice |\n"
        tokens = _table_tokens(source)
        tree = _build_tree(tokens)

        assert len(tree) == 2
        assert tree[0]["type"] != "table"
        assert tree[1]["type"] == "table"
        assert len(tree[1]["rows"]) == 1

        def cell_text(cell_tokens) -> str:
            return "".join(t.content for t in cell_tokens)

        assert [cell_text(c) for c in tree[1]["rows"][0]] == ["Alice"]


# ==============================================================================
# STRICT STRIKETHROUGH — regex (direct, string-level) + ruler plugin (direct,
# real MarkdownIt instance). markdown.ts:6-23.
# ==============================================================================


class TestStrictStrikethroughRegex:
    """``STRICT_STRIKETHROUGH_REGEX`` must be a 1:1 translation of upstream's
    ``STRICT_STRIKETHROUGH_REGEX`` (markdown.ts:6):
    ``/^(~~)(?=[^\\s~])((?:\\\\.|[^\\\\])*?(?:\\\\.|[^\\s~\\\\]))\\1(?=[^~]|$)/``
    """

    def test_tight_strikethrough_matches(self):
        m = STRICT_STRIKETHROUGH_REGEX.match("~~x~~")
        assert m is not None
        assert m.group(0) == "~~x~~"
        assert m.group(2) == "x"

    def test_leading_space_does_not_match(self):
        assert STRICT_STRIKETHROUGH_REGEX.match("~~ x~~") is None

    def test_trailing_space_does_not_match(self):
        assert STRICT_STRIKETHROUGH_REGEX.match("~~x ~~") is None

    def test_single_tilde_does_not_match(self):
        assert STRICT_STRIKETHROUGH_REGEX.match("~x~") is None

    def test_cjk_content_matches_and_stops_before_trailing_text(self):
        m = STRICT_STRIKETHROUGH_REGEX.match("~~严格删除线~~ tail")
        assert m is not None
        assert m.group(0) == "~~严格删除线~~"
        assert m.group(2) == "严格删除线"


class TestStrictStrikethroughPlugin:
    """Direct test of the ruler-plugin registration (heads-up note #2's
    "为适配层写直接单测" extended to the strikethrough rule): construct a
    bare ``MarkdownIt("commonmark")``, apply ``strict_strikethrough_plugin``,
    and inspect the resulting *inline token* stream via ``.parse()``
    (no HTML rendering involved) — asserting only the observable
    ``s_open``/``text``/``s_close`` shape (markdown-it-py's own established
    type names for this rule, verified against the real, installed
    ``markdown_it.rules_inline.strikethrough`` module), not the internal
    mechanism used to get there.
    """

    @staticmethod
    def _parse(source: str):
        md = MarkdownIt("commonmark")
        strict_strikethrough_plugin(md)
        return md.parse(source)

    def test_tight_delimiters_produce_s_open_close_tokens(self):
        tokens = self._parse("Use ~~strikethrough~~ here")
        inline = next(t for t in tokens if t.type == "inline")
        assert inline.children is not None
        kinds = [c.type for c in inline.children]
        assert "s_open" in kinds
        assert "s_close" in kinds
        text_contents = [c.content for c in inline.children if c.type == "text"]
        assert "strikethrough" in text_contents
        assert not any("~~strikethrough~~" in t for t in text_contents)

    def test_loose_delimiters_stay_plain_text(self):
        tokens = self._parse("Use ~~ strikethrough ~~ here")
        inline = next(t for t in tokens if t.type == "inline")
        assert inline.children is not None
        kinds = [c.type for c in inline.children]
        assert "s_open" not in kinds
        assert "s_close" not in kinds
        combined = "".join(c.content for c in inline.children)
        assert "~~ strikethrough ~~" in combined


# ==============================================================================
# Component protocol compliance (Task 7) — cheap supplementary checks.
# ==============================================================================


class TestComponentProtocol:
    def test_render_returns_list_of_str(self):
        md = Markdown("hello world", TRUE_COLOR_NO_HYPERLINKS)
        lines = md.render(80)
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_invalidate_is_callable_and_does_not_raise(self):
        md = Markdown("hello world", TRUE_COLOR_NO_HYPERLINKS)
        md.render(80)
        md.invalidate()  # must not raise
