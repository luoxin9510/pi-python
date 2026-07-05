"""ToolExecution component — a **generic, uniform approximation** of how
upstream pi renders a tool call, not a faithful per-tool port. This matters:
independent review (re-verified against upstream source) found that all 7 of
pi's built-in tools (``core/tools/{bash,edit,read,write,grep,find,ls}.ts``)
define their own ``renderCall``/``renderResult`` — real pi's
``ToolExecutionComponent.hasRendererDefinition()`` (tool-execution.ts) is
therefore *always true* for actual tool calls, and its fallback path
(``createCallFallback()``/``createResultFallback()``/
``formatToolExecution()``, tool-execution.ts:135-145,361-376) is dead code
upstream, reserved for unregistered/unknown tool names. This port has no
per-tool ``renderCall``/``renderResult`` customization system at all (spec
§1 non-goal of the phase-3 design doc), so it always takes that otherwise-
dead fallback path — meaning every tool (bash, edit, ls, …) gets the exact
same generic header+background+preview treatment here, where real pi gives
each tool its own hand-built renderer (bash's timed/live box, edit's diff
preview, etc.). This is a deliberate, disclosed scope reduction (building 7
per-tool renderers is out of this task's scope), not a claim of full
tool-by-tool fidelity.

Bash gets its own header line format (``$ <command>``) but **not its own
class**. The header format is a faithful port of the REAL bash tool's own
call renderer — ``core/tools/bash.ts:201-206``'s ``formatBashCall``:
``theme.fg("toolTitle", theme.bold(\\`$ ${command}\\`))`` — **not**
``components/bash-execution.ts``, which an earlier draft of this docstring
miscited: that file's ``BashExecutionComponent`` is a *different* feature
(the ``!command`` quick-shell-mode UI wired only from
``interactive-mode.ts``, never from actual LLM-driven bash tool calls — 5
call sites, all there, confirmed by grep). This port's ``ToolResultEvent``
delivers a tool's full output atomically (no incremental streaming chunks,
no ``DynamicBorder`` framing component — both phase-4 items per
``docs/superpowers/specs/2026-07-04-phase3-pi-tui-port-design.md``'s
"路线图升级" roadmap note), so a separate ``BashExecutionComponent``-style
subclass would add no behavioral value here regardless of which upstream
file it modeled.

Upstream citations:
- ``tool-execution.ts``: ``createCallFallback`` (135-137) —
  ``theme.fg("toolTitle", theme.bold(toolName))``; ``createResultFallback``/
  ``getTextOutput`` (139-145, 361-363) — ``theme.fg("toolOutput", output)``;
  ``updateDisplay``'s ``bgFn`` selection (253-258) — pending/error/success
  background by state; ``setExpanded`` (201-204).
- ``core/tools/bash.ts``: ``formatBashCall`` (201-206, bash's real call
  header — see above); ``BASH_PREVIEW_LINES = 5`` (174) and
  ``rebuildBashResultRenderComponent``'s collapsed/expanded split
  (206-260) — tail-preview via ``truncateToVisualLines(styledOutput,
  BASH_PREVIEW_LINES, width)`` (245), hint text placed *before* the shown
  lines (``["", hint, ...cachedLines]``, 253-256).

  **No single upstream constant is "the" generic tool-output preview
  policy** — each of the 7 built-in tools' own ``renderResult`` picks a
  different line count *and* a different truncation direction: bash tail-
  previews at 5 (above); ``ls.ts``/``find.ts`` head-truncate
  (``lines.slice(0, maxLines)``) at 20; ``grep.ts`` head-truncates at 15;
  ``read.ts``/``write.ts`` head-truncate at 10. Since this port's fallback
  path is generic across all tools (see above), it needs exactly one
  policy; this borrows bash's real constant (``BASH_PREVIEW_LINES = 5``,
  tail-truncation, hint-before-content) as the single most load-bearing
  case (bash is the tool most likely to produce long streaming output),
  while disclosing this is still an approximation for the other 6 tools,
  which upstream would show more (and head-first) lines of collapsed by
  default.
- ``diff.py`` (port of ``diff.ts``): edit-tool results whose content is
  already in diff.ts's line-numbered ``"+N "``/``"-N "``/``" N "`` format
  are colored via ``render_diff`` instead of plain ``toolOutput`` gray.
- ``interactive-mode.ts:2513``/``3636``: ``app.tools.expand`` (Ctrl+O)
  toggles ``expanded`` on every live tool component — wired at ``app.py``,
  not here (this component only exposes ``set_expanded``, matching
  upstream's own ``setExpanded`` method on the component itself).
- ``theme/theme.ts``/``theme/dark.json``: see the inline color-constant
  comments below (same citation format as ``select_list.py``/
  ``markdown.py``): ``toolTitle="text"->"#d4d4d4"``,
  ``toolOutput="gray"->"#808080"``, ``toolPendingBg="#282832"``,
  ``toolSuccessBg="#283228"``, ``toolErrorBg="#3c2828"``. ``theme.bold`` ->
  chalk.bold SGR pair ``\\x1b[1m``/``\\x1b[22m`` (already established in
  this port's ``markdown.py``).

Known, disclosed gap (out of this task's stated file scope, not fixed
here): ``tools/edit.py`` does not yet produce diff-formatted content (it
returns a one-line summary, ``f"Applied {n} edit(s) to {path}"``) — so the
``render_diff`` wiring below is real and unit-tested against synthetic
diff-shaped content (``test_tool_execution.py``), but unreachable from an
actual ``edit`` tool call today. Independent review also found that
upstream's real ``edit.ts`` (350-360) puts the diff in a **separate
structured** ``details.diff`` field, never in the LLM-facing ``content``
string this port's ``ToolResult.content: str`` corresponds to — so a
faithful fix here would need a new structured field threaded through
``ToolResultEvent``, not just diff-shaped text appended to ``edit.py``'s
existing content string. Left for a separate task (touches the tool
layer/SDK types, not the TUI).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from ..engine.utils import apply_background_to_line, wrap_text_with_ansi
from .diff import render_diff

__all__ = ["ToolExecution"]

_FG_RESET = "\x1b[39m"
_BOLD_ON = "\x1b[1m"
_BOLD_OFF = "\x1b[22m"

_TOOL_TITLE_FG = "\x1b[38;2;212;212;212m"  # dark.json toolTitle="text" -> vars.text "#d4d4d4"
_TOOL_OUTPUT_FG = "\x1b[38;2;128;128;128m"  # dark.json toolOutput="gray" -> vars.gray "#808080"

_TOOL_PENDING_BG = "\x1b[48;2;40;40;50m"  # dark.json vars.toolPendingBg "#282832"
_TOOL_SUCCESS_BG = "\x1b[48;2;40;50;40m"  # dark.json vars.toolSuccessBg "#283228"
_TOOL_ERROR_BG = "\x1b[48;2;60;40;40m"  # dark.json vars.toolErrorBg "#3c2828"

_ARG_TRUNC = 100
_PREVIEW_LINES = 5  # core/tools/bash.ts BASH_PREVIEW_LINES (see module docstring)

_DIFF_LINE_RE = re.compile(r"^([+\-\s])(\s*\d*)\s")

State = Literal["running", "success", "error"]

_STATE_BG: dict[State, str] = {
    "running": _TOOL_PENDING_BG,
    "success": _TOOL_SUCCESS_BG,
    "error": _TOOL_ERROR_BG,
}


def _bold(text: str) -> str:
    return f"{_BOLD_ON}{text}{_BOLD_OFF}"


def _fg_title(text: str) -> str:
    return f"{_TOOL_TITLE_FG}{text}{_FG_RESET}"


def _fg_output(text: str) -> str:
    return f"{_TOOL_OUTPUT_FG}{text}{_FG_RESET}"


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _looks_like_diff(content: str) -> bool:
    """Heuristic gate for ``render_diff``: real diff.ts input is always
    produced by ``generateDiffString`` upstream (every non-blank line
    matches its line-numbered format), so requiring *all* non-empty lines
    to match avoids misfiring on ordinary tool output that merely happens
    to start one line with a plus/minus/space character."""
    lines = [line for line in content.split("\n") if line]
    if not lines:
        return False
    return all(_DIFF_LINE_RE.match(line) for line in lines)


class ToolExecution:
    """tui.ts ``Component``-compatible: a single tool call's header +
    (once resolved) its result, background-tinted by state. See module
    docstring for the scope of upstream ``tool-execution.ts``/
    ``core/tools/bash.ts`` this class actually ports (fallback-only,
    generic-across-all-tools path)."""

    def __init__(self, tool_name: str, args: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.args = args
        self.state: State = "running"
        self.content = ""
        self.expanded = False

    def set_result(self, content: str, is_error: bool) -> None:
        """tool-execution.ts's ``updateResult`` (164-176), narrowed to this
        port's atomic (non-partial) ``ToolResultEvent`` delivery — there is
        no streaming/partial-result concept to thread through."""
        self.content = content
        self.state = "error" if is_error else "success"

    def set_expanded(self, expanded: bool) -> None:
        """tool-execution.ts's ``setExpanded`` (201-204)."""
        self.expanded = expanded

    def invalidate(self) -> None:
        """No cached render state (matches this port's box.py/text.py
        precedent of dropping upstream's render-output caches — a pure
        perf concern orthogonal to render semantics)."""

    def _header_text(self) -> str:
        """createCallFallback (tool-execution.ts:135-137): ``theme.fg
        ("toolTitle", theme.bold(toolName))``. Bash gets ``$ <command>`` as
        its title — a faithful port of the real bash tool's own call
        renderer, ``core/tools/bash.ts:201-206``'s ``formatBashCall`` —
        instead of a raw tool name + JSON args tail."""
        if self.tool_name == "bash" and isinstance(self.args.get("command"), str):
            title = f"$ {_clip(self.args['command'], _ARG_TRUNC)}"
            return _bold(_fg_title(title))

        header = _bold(_fg_title(self.tool_name))
        args_json = json.dumps(self.args, ensure_ascii=False) if self.args else ""
        if args_json and args_json != "{}":
            header = f"{header} {_clip(args_json, _ARG_TRUNC)}"
        return header

    def _body_lines(self) -> list[str]:
        """createResultFallback/getTextOutput (139-145, 361-363) plus
        ``core/tools/bash.ts``'s real collapsed-tail/expanded-full preview
        split (``rebuildBashResultRenderComponent``, 206-260 — see module
        docstring), adopted uniformly here. Collapsed hint is placed
        *before* the shown lines, matching bash.ts:253-256's own
        ``["", hint, ...cachedLines]`` ordering. The expanded case adds a
        "(ctrl+o to collapse)" hint that bash.ts's real expanded branch
        (236) does *not* show (it just prints the full output, no hint) —
        an intentional, disclosed addition: this port has no persistent
        footer/keybinding status bar (phase-4 item) to otherwise remind a
        user the toggle exists once already expanded."""
        if self.state == "running" or not self.content:
            return []

        if self.tool_name == "edit" and _looks_like_diff(self.content):
            logical_lines = render_diff(self.content).split("\n")
        else:
            logical_lines = [_fg_output(line) for line in self.content.split("\n")]

        total = len(logical_lines)
        if total <= _PREVIEW_LINES:
            return logical_lines

        if self.expanded:
            return [*logical_lines, _fg_output("(ctrl+o to collapse)")]

        hidden = total - _PREVIEW_LINES
        shown = logical_lines[-_PREVIEW_LINES:]
        return [_fg_output(f"... {hidden} more lines (ctrl+o to expand)"), *shown]

    def render(self, width: int) -> list[str]:
        width = max(1, width)
        bg = _STATE_BG[self.state]

        logical: list[str] = [self._header_text(), *self._body_lines()]
        physical: list[str] = []
        for line in logical:
            physical.extend(wrap_text_with_ansi(line, width) or [""])

        return [apply_background_to_line(line, bg, width) for line in physical]
