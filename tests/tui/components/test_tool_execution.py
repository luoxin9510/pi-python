"""RED-phase tests for the ToolExecution component — a **generic
approximation** (not a faithful per-tool port) of upstream pi's
``packages/coding-agent/src/modes/interactive/components/tool-execution.ts``
(377 lines) fallback path, plus the real bash tool's own call-header format
from ``core/tools/bash.ts``. See ``tool_execution.py``'s module docstring
for the full scoping rationale (independent review found all 7 built-in
tools define their own ``renderCall``/``renderResult`` upstream, making
tool-execution.ts's fallback path dead code there — this port has no such
per-tool system, so it always takes that path, uniformly for every tool).

Upstream citations:
- ``tool-execution.ts``: ``createCallFallback``/``createResultFallback``
  (135-145) — ``theme.fg("toolTitle", theme.bold(toolName))`` /
  ``theme.fg("toolOutput", output)``; ``updateDisplay``'s state->bgFn
  selection (253-258); ``setExpanded`` (201-204).
- ``core/tools/bash.ts``: ``formatBashCall`` (201-206, bash's real
  ``"$ <command>"`` header); ``BASH_PREVIEW_LINES = 5`` (174); collapsed
  tail-preview vs expanded full (``rebuildBashResultRenderComponent``,
  206-260); hint-before-content ordering (253-256).
- ``theme/dark.json``: ``toolPendingBg="#282832"``,
  ``toolSuccessBg="#283228"``, ``toolErrorBg="#3c2828"``,
  ``toolTitle="text"->"#d4d4d4"``, ``toolOutput="gray"->"#808080"``.

Exact-byte assertions per this repo's established convention (bg bytes,
header bold+color bytes).
"""

from __future__ import annotations

from pipython.tui.components.tool_execution import ToolExecution
from pipython.tui.engine.utils import visible_width

_BOLD_ON = "\x1b[1m"
_BOLD_OFF = "\x1b[22m"
_TITLE_FG = "\x1b[38;2;212;212;212m"
_OUTPUT_FG = "\x1b[38;2;128;128;128m"
_FG_RESET = "\x1b[39m"

_PENDING_BG = "\x1b[48;2;40;40;50m"
_SUCCESS_BG = "\x1b[48;2;40;50;40m"
_ERROR_BG = "\x1b[48;2;60;40;40m"
_RESET = "\x1b[0m"


def _bg_line(bg: str, content: str, width: int) -> str:
    pad = " " * max(0, width - visible_width(content))
    return f"{bg}{content}{pad}{_RESET}"


class TestHeaderAndState:
    def test_running_state_uses_pending_background_and_bold_title_header(self):
        comp = ToolExecution("ls", {})
        lines = comp.render(40)
        header = f"{_BOLD_ON}{_TITLE_FG}ls{_FG_RESET}{_BOLD_OFF}"
        assert lines == [_bg_line(_PENDING_BG, header, 40)]

    def test_success_state_switches_to_success_background(self):
        comp = ToolExecution("ls", {})
        comp.set_result("file1.txt\nfile2.txt", is_error=False)
        lines = comp.render(40)
        assert all(line.startswith(_SUCCESS_BG) for line in lines)
        assert not any(_ERROR_BG in line for line in lines)

    def test_error_state_switches_to_error_background(self):
        comp = ToolExecution("bogus_tool", {})
        comp.set_result("Unknown tool: bogus_tool", is_error=True)
        lines = comp.render(40)
        assert all(line.startswith(_ERROR_BG) for line in lines)
        assert any("Unknown tool: bogus_tool" in line for line in lines)

    def test_header_includes_truncated_args_json(self):
        comp = ToolExecution("grep", {"pattern": "x" * 500})
        lines = comp.render(200)
        # Header line (first) must not contain the full 500-char pattern.
        assert "x" * 500 not in lines[0]
        assert "grep" in lines[0]

    def test_args_empty_dict_produces_no_trailing_json(self):
        comp = ToolExecution("ls", {})
        header = comp._header_text()  # noqa: SLF001 -- exact-format assertion
        assert header == f"{_BOLD_ON}{_TITLE_FG}ls{_FG_RESET}{_BOLD_OFF}"


class TestBashHeaderVariant:
    def test_bash_header_shows_dollar_command_not_json_args(self):
        comp = ToolExecution("bash", {"command": "echo hi"})
        header = comp._header_text()  # noqa: SLF001
        assert header == f"{_BOLD_ON}{_TITLE_FG}$ echo hi{_FG_RESET}{_BOLD_OFF}"
        assert "command" not in header  # no raw JSON key leaking into the header

    def test_bash_long_command_is_truncated_in_header(self):
        long_cmd = "x" * 500
        comp = ToolExecution("bash", {"command": long_cmd})
        lines = comp.render(600)
        assert long_cmd not in "\n".join(lines), (
            "a long bash command must be truncated, never echoed in full"
        )
        assert "$ " in lines[0]


class TestCollapsedExpandedPreview:
    """_PREVIEW_LINES = 5, matching core/tools/bash.ts's real
    BASH_PREVIEW_LINES (see tool_execution.py's module docstring — an
    earlier revision of this test suite used 20, mis-citing
    bash-execution.ts's unrelated "!command" quick-mode constant)."""

    def _long_output(self, n: int) -> str:
        # Fixed-width, zero-padded markers (L01..Lnn) so no marker is ever
        # a substring of another (unlike "LINE_1" inside "LINE_10").
        return "\n".join(f"L{i:02d}" for i in range(1, n + 1))

    def test_collapsed_shows_last_5_lines_with_hint_before_content(self):
        comp = ToolExecution("bash", {"command": "seq 1 25"})
        comp.set_result(self._long_output(25), is_error=False)
        lines = comp.render(80)
        text = "\n".join(lines)
        assert "L01" not in text  # hidden (only L21..L25 shown)
        assert "L20" not in text
        assert "L21" in text
        assert "L25" in text
        assert "20 more lines" in text
        assert "ctrl+o to expand" in text
        # Hint must come BEFORE the shown content (bash.ts:253-256's own
        # `["", hint, ...cachedLines]` ordering), not after.
        hint_idx = next(i for i, line in enumerate(lines) if "more lines" in line)
        first_shown_idx = next(i for i, line in enumerate(lines) if "L21" in line)
        assert hint_idx < first_shown_idx

    def test_expanded_shows_all_lines_with_collapse_hint(self):
        comp = ToolExecution("bash", {"command": "seq 1 25"})
        comp.set_result(self._long_output(25), is_error=False)
        comp.set_expanded(True)
        lines = comp.render(80)
        text = "\n".join(lines)
        assert "L01" in text
        assert "L25" in text
        assert "ctrl+o to collapse" in text

    def test_short_output_shows_all_lines_no_hint(self):
        comp = ToolExecution("ls", {})
        comp.set_result(self._long_output(3), is_error=False)
        lines = comp.render(80)
        text = "\n".join(lines)
        assert "L01" in text and "L03" in text
        assert "ctrl+o" not in text

    def test_running_state_shows_no_body_even_before_result(self):
        comp = ToolExecution("bash", {"command": "sleep 1"})
        lines = comp.render(80)
        assert len(lines) == 1  # header only, no result yet


class TestDiffWiringForEditTool:
    def test_edit_tool_diff_shaped_content_gets_colored_as_diff(self):
        comp = ToolExecution("edit", {"path": "f.py"})
        comp.set_result("-1 old line\n+1 new line", is_error=False)
        lines = comp.render(80)
        text = "\n".join(lines)
        # green added / red removed markers from diff.py, not plain toolOutput gray
        assert "\x1b[38;2;181;189;104m" in text  # toolDiffAdded
        assert "\x1b[38;2;204;102;102m" in text  # toolDiffRemoved

    def test_non_edit_tool_never_uses_diff_coloring(self):
        comp = ToolExecution("bash", {"command": "echo -1"})
        comp.set_result("-1 old line\n+1 new line", is_error=False)
        lines = comp.render(80)
        text = "\n".join(lines)
        assert "\x1b[38;2;181;189;104m" not in text
        assert _OUTPUT_FG in text

    def test_edit_tool_plain_summary_content_not_treated_as_diff(self):
        # Today's real EditTool output ("Applied 1 edit(s) to f.py") is not
        # diff-shaped -- must render as plain toolOutput text, not crash or
        # misfire diff coloring (see module docstring's disclosed gap).
        comp = ToolExecution("edit", {"path": "f.py"})
        comp.set_result("Applied 1 edit(s) to f.py", is_error=False)
        lines = comp.render(80)
        text = "\n".join(lines)
        assert "Applied 1 edit(s) to f.py" in text
        assert "\x1b[38;2;181;189;104m" not in text


class TestExpandToggle:
    def test_set_expanded_is_idempotent_and_readable(self):
        comp = ToolExecution("ls", {})
        assert comp.expanded is False
        comp.set_expanded(True)
        assert comp.expanded is True
        comp.set_expanded(False)
        assert comp.expanded is False
