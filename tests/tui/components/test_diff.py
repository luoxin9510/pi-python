"""RED-phase tests for diff rendering (± line coloring for edit-tool
results) — Python port of upstream pi's
``packages/coding-agent/src/modes/interactive/components/diff.ts`` (147
lines, read in full).

Upstream citations:
- ``diff.ts``: ``parseDiffLine`` (regex ``/^([+-\\s])(\\s*\\d*)\\s(.*)$/``),
  ``replaceTabs`` (tabs -> 3 spaces), ``renderIntraLineDiff`` (word-level
  diff via the ``diff`` npm package's ``diffWords``, inverse-highlighting
  changed spans while stripping leading whitespace from the first
  removed/added part), ``renderDiff`` (the main line-grouping loop: context
  lines are colored gray, a lone "-" line immediately followed by a lone
  "+" line gets intra-line highlighting, anything else shows removed lines
  then added lines plainly colored).
- ``theme/dark.json``: ``toolDiffAdded="green"`` -> ``#b5bd68``;
  ``toolDiffRemoved="red"`` -> ``#cc6666``; ``toolDiffContext="gray"`` ->
  ``#808080``. ``theme.fg`` emits ``\\x1b[38;2;R;G;Bm...\\x1b[39m``
  (foreground-only reset, theme.ts:352-356/261-274).

Exact-byte assertions per this repo's established convention (see
components/select_list.py, components/markdown.py).
"""

from __future__ import annotations

from pipython.tui.components.diff import render_diff

_ADDED_FG = "\x1b[38;2;181;189;104m"  # #b5bd68
_REMOVED_FG = "\x1b[38;2;204;102;102m"  # #cc6666
_CONTEXT_FG = "\x1b[38;2;128;128;128m"  # #808080
_FG_RESET = "\x1b[39m"
_INVERSE_ON = "\x1b[7m"
_INVERSE_OFF = "\x1b[27m"


def test_context_line_colored_gray():
    result = render_diff(" 12 unchanged line")
    assert result == f"{_CONTEXT_FG} 12 unchanged line{_FG_RESET}"


def test_standalone_added_line_colored_green():
    result = render_diff("+5 brand new line")
    assert result == f"{_ADDED_FG}+5 brand new line{_FG_RESET}"


def test_multi_line_removal_and_addition_no_intra_line_highlight():
    # 2 removed + 2 added -> not a single-line replacement, so upstream
    # shows all removed lines then all added lines, plainly colored (no
    # inverse spans at all).
    diff_text = "-1 old a\n-2 old b\n+1 new a\n+2 new b"
    result = render_diff(diff_text)
    lines = result.split("\n")
    assert lines == [
        f"{_REMOVED_FG}-1 old a{_FG_RESET}",
        f"{_REMOVED_FG}-2 old b{_FG_RESET}",
        f"{_ADDED_FG}+1 new a{_FG_RESET}",
        f"{_ADDED_FG}+2 new b{_FG_RESET}",
    ]
    assert _INVERSE_ON not in result


def test_single_line_replacement_gets_intra_line_inverse_highlight():
    # Exactly one removed + one added line -> word-level diff with inverse
    # highlighting on the changed word only ("quick" -> "slow"), context
    # words ("the", "fox") stay plain within the colored line.
    diff_text = "-3 the quick fox\n+3 the slow fox"
    result = render_diff(diff_text)
    lines = result.split("\n")
    assert lines[0] == (f"{_REMOVED_FG}-3 the {_INVERSE_ON}quick{_INVERSE_OFF} fox{_FG_RESET}")
    assert lines[1] == (f"{_ADDED_FG}+3 the {_INVERSE_ON}slow{_INVERSE_OFF} fox{_FG_RESET}")


def test_intra_line_diff_strips_leading_whitespace_from_highlight():
    # Pure indentation change: the whole changed token is leading
    # whitespace, so it must NOT be wrapped in inverse (upstream strips
    # leading whitespace off the first removed/added part specifically to
    # avoid highlighting indentation).
    #
    # Known, disclosed divergence from upstream for this exact case (see
    # diff.py's module docstring): real diffWords uses trimmed equality and
    # sources "unchanged" text from the *new* string, so real pi would show
    # "    foo" (the new indent) on BOTH lines here, hiding that the old
    # line had 2 spaces. difflib's exact-equality comparator instead shows
    # each side's own real indentation, which is what this test pins.
    diff_text = "-1   foo\n+1     foo"
    result = render_diff(diff_text)
    lines = result.split("\n")
    assert _INVERSE_ON not in lines[0]
    assert _INVERSE_ON not in lines[1]
    assert lines[0] == f"{_REMOVED_FG}-1   foo{_FG_RESET}"
    assert lines[1] == f"{_ADDED_FG}+1     foo{_FG_RESET}"


def test_tabs_replaced_with_three_spaces():
    diff_text = "-1 \told\n+1 \tnew"
    result = render_diff(diff_text)
    assert "\t" not in result
    lines = result.split("\n")
    assert lines[0] == f"{_REMOVED_FG}-1{' '}{'   '}{_INVERSE_ON}old{_INVERSE_OFF}{_FG_RESET}"
    assert lines[1] == f"{_ADDED_FG}+1{' '}{'   '}{_INVERSE_ON}new{_INVERSE_OFF}{_FG_RESET}"


def test_unparseable_line_falls_back_to_context_coloring():
    # A line with no recognizable prefix/lineNum/space structure at all
    # (parseDiffLine returns null upstream) is still colored as context,
    # verbatim, per diff.ts's `if (!parsed) result.push(theme.fg
    # ("toolDiffContext", line))`.
    result = render_diff("totally not a diff line")
    assert result == f"{_CONTEXT_FG}totally not a diff line{_FG_RESET}"


def test_mixed_context_and_change_blocks():
    diff_text = " 1 keep\n-2 bye\n+2 hi\n 3 keep too"
    result = render_diff(diff_text)
    lines = result.split("\n")
    assert lines[0] == f"{_CONTEXT_FG} 1 keep{_FG_RESET}"
    assert lines[3] == f"{_CONTEXT_FG} 3 keep too{_FG_RESET}"
