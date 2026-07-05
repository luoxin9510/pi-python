"""Diff rendering for edit-tool results — Python port of upstream pi's
``packages/coding-agent/src/modes/interactive/components/diff.ts`` (147
lines, read in full): colors a pi-style line-numbered diff string
(context/removed/added lines, e.g. ``" 12 unchanged"`` / ``"-13 old"`` /
``"+13 new"``) and, for a single-line replacement (exactly one removed line
immediately followed by exactly one added line), highlights the changed
words within that pair via inverse video.

Upstream citations:
- ``diff.ts``: ``parseDiffLine`` (regex ``/^([+-\\s])(\\s*\\d*)\\s(.*)$/``),
  ``replaceTabs`` (tabs -> 3 spaces), ``renderIntraLineDiff`` (word-level
  diff via the ``diff`` npm package's ``Diff.diffWords``), ``renderDiff``
  (the main line-grouping loop).
- ``theme/theme.ts``: ``Theme.fg(color, text)`` (352-356) ->
  ``f"{ansi}{text}\\x1b[39m"`` (foreground-only reset); ``fgAnsi`` truecolor
  branch (261-274) -> hex ``\\x1b[38;2;R;G;Bm``. ``Theme.inverse``
  (376-378) delegates to ``chalk.inverse``, whose SGR pair is the standard
  ``\\x1b[7m``/``\\x1b[27m`` (reverse-video on/off) — deliberately **not**
  the bare ``\\x1b[0m`` full reset this port's ``editor.py`` uses for its
  (never-nested) cursor marker: here the inverse span sits *inside* an
  outer ``theme.fg`` color, so a full reset would also cancel that outer
  color for the rest of the line. ``\\x1b[27m`` only turns inverse back
  off, matching upstream's actual chalk behavior.
- ``theme/dark.json``: ``colors.toolDiffAdded = "green"`` ->
  ``vars.green = "#b5bd68"``; ``colors.toolDiffRemoved = "red"`` ->
  ``vars.red = "#cc6666"``; ``colors.toolDiffContext = "gray"`` ->
  ``vars.gray = "#808080"``.

Deviation (library substitution, not semantics — matches this port's
established "borrow parsing libs, port rendering logic faithfully"
precedent, spec §2 of the phase-3 design doc): upstream's word-level
intra-line diff uses the ``diff`` npm package's ``Diff.diffWords``
(whitespace-aware word tokenizer); this port uses stdlib
``difflib.SequenceMatcher`` over the same whitespace-preserving word
tokenization (``re.findall(r"\\s+|\\S+", text)``) instead of adding a new
runtime dependency (CLAUDE.md: new runtime deps need a spec change +
maintainer sign-off first). The opcode-driven equal/replace/delete/insert
walk preserves upstream's exact "strip leading whitespace off only the
first removed/added part" rule (avoids highlighting pure indentation
changes) and matches upstream for the common case (word-level token
substitutions).

**Known, narrower divergence** (found by independent review, empirically
confirmed against the real ``diff`` npm package via
``node -e "require('diff').diffWords(...)"``): upstream's ``diffWords``
compares tokens using **trimmed** equality and, for a "common"/unchanged
span, emits text sourced from the **new** string — so a pure whitespace-run
difference (e.g. ``"  foo"`` -> ``"    foo"``, both trim to the same
non-whitespace content) is classified as *unchanged* upstream, and the
*new* indentation silently overwrites the old on both rendered lines
(verified: ``diffWords("  foo", "    foo")`` returns one ``keep`` part,
value ``"    foo"``, on both sides). ``difflib.SequenceMatcher`` uses exact
(non-trimmed) token equality, so this port instead shows each side's *own*
real whitespace (``"  foo"`` / ``"    foo"``) — arguably more informative
(you can actually see the indent changed), but a real, disclosed divergence
from upstream's specific behavior for whitespace-only diffs. Left as-is:
this path is currently unreachable end-to-end (see the gap below), and
replicating jsdiff's trim-then-new-sourced quirk exactly would need a
bespoke comparator, not a proportionate fix for dead code.

Known, disclosed gap (see ``tool_execution.py``'s module docstring):
``tools/edit.py`` does not yet emit content in this line-numbered format,
so ``render_diff`` is unit-tested here against synthetic input but not yet
reachable from a real ``edit`` tool call.
"""

from __future__ import annotations

import difflib
import re

__all__ = ["render_diff"]

_FG_RESET = "\x1b[39m"
_INVERSE_ON = "\x1b[7m"
_INVERSE_OFF = "\x1b[27m"

_DIFF_ADDED_FG = "\x1b[38;2;181;189;104m"  # dark.json toolDiffAdded=green "#b5bd68"
_DIFF_REMOVED_FG = "\x1b[38;2;204;102;102m"  # dark.json toolDiffRemoved=red "#cc6666"
_DIFF_CONTEXT_FG = "\x1b[38;2;128;128;128m"  # dark.json toolDiffContext=gray "#808080"

_LINE_RE = re.compile(r"^([+\-\s])(\s*\d*)\s(.*)$")
_TOKEN_RE = re.compile(r"\s+|\S+")
_LEADING_WS_RE = re.compile(r"^(\s*)")


def _fg(color: str, text: str) -> str:
    return f"{color}{text}{_FG_RESET}"


def _parse_diff_line(line: str) -> tuple[str, str, str] | None:
    """diff.ts's ``parseDiffLine`` (8-12): prefix char, line-number field
    (possibly blank, e.g. the ``...`` skipped-context placeholder), and the
    rest of the content."""
    m = _LINE_RE.match(line)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _replace_tabs(text: str) -> str:
    """diff.ts's ``replaceTabs`` (17-19)."""
    return text.replace("\t", "   ")


def _leading_whitespace(text: str) -> str:
    m = _LEADING_WS_RE.match(text)
    return m.group(1) if m else ""


def _render_intra_line_diff(old_content: str, new_content: str) -> tuple[str, str]:
    """diff.ts's ``renderIntraLineDiff`` (26-66), ported onto
    ``difflib.SequenceMatcher`` opcodes instead of ``Diff.diffWords`` parts
    (see module docstring deviation). Strips leading whitespace from the
    first removed/added part so pure-indentation changes don't get a noisy
    inverse-highlighted run of spaces."""
    old_tokens = _TOKEN_RE.findall(old_content)
    new_tokens = _TOKEN_RE.findall(new_content)
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)

    removed_line = ""
    added_line = ""
    is_first_removed = True
    is_first_added = True

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged = "".join(old_tokens[i1:i2])
            removed_line += unchanged
            added_line += unchanged
            continue

        if tag in ("delete", "replace"):
            value = "".join(old_tokens[i1:i2])
            if is_first_removed:
                leading_ws = _leading_whitespace(value)
                value = value[len(leading_ws) :]
                removed_line += leading_ws
                is_first_removed = False
            if value:
                removed_line += f"{_INVERSE_ON}{value}{_INVERSE_OFF}"

        if tag in ("insert", "replace"):
            value = "".join(new_tokens[j1:j2])
            if is_first_added:
                leading_ws = _leading_whitespace(value)
                value = value[len(leading_ws) :]
                added_line += leading_ws
                is_first_added = False
            if value:
                added_line += f"{_INVERSE_ON}{value}{_INVERSE_OFF}"

    return removed_line, added_line


def render_diff(diff_text: str) -> str:
    """diff.ts's ``renderDiff`` (79-147): colors a line-numbered diff
    string. Context lines are gray; a lone removed line immediately
    followed by a lone added line gets intra-line word highlighting;
    anything else shows all removed lines (red) then all added lines
    (green), plainly."""
    lines = diff_text.split("\n")
    result: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        parsed = _parse_diff_line(lines[i])

        if not parsed:
            result.append(_fg(_DIFF_CONTEXT_FG, lines[i]))
            i += 1
            continue

        prefix = parsed[0]

        if prefix == "-":
            removed: list[tuple[str, str]] = []
            while i < n:
                p = _parse_diff_line(lines[i])
                if not p or p[0] != "-":
                    break
                removed.append((p[1], p[2]))
                i += 1

            added: list[tuple[str, str]] = []
            while i < n:
                p = _parse_diff_line(lines[i])
                if not p or p[0] != "+":
                    break
                added.append((p[1], p[2]))
                i += 1

            if len(removed) == 1 and len(added) == 1:
                r_num, r_content = removed[0]
                a_num, a_content = added[0]
                removed_line, added_line = _render_intra_line_diff(
                    _replace_tabs(r_content), _replace_tabs(a_content)
                )
                result.append(_fg(_DIFF_REMOVED_FG, f"-{r_num} {removed_line}"))
                result.append(_fg(_DIFF_ADDED_FG, f"+{a_num} {added_line}"))
            else:
                for r_num, r_content in removed:
                    result.append(_fg(_DIFF_REMOVED_FG, f"-{r_num} {_replace_tabs(r_content)}"))
                for a_num, a_content in added:
                    result.append(_fg(_DIFF_ADDED_FG, f"+{a_num} {_replace_tabs(a_content)}"))
        elif prefix == "+":
            _, num, content = parsed
            result.append(_fg(_DIFF_ADDED_FG, f"+{num} {_replace_tabs(content)}"))
            i += 1
        else:
            _, num, content = parsed
            result.append(_fg(_DIFF_CONTEXT_FG, f" {num} {_replace_tabs(content)}"))
            i += 1

    return "\n".join(result)
