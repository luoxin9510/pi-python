"""tmux e2e for the pipython TUI.

Task 18 (pi-tui engine becomes the only TUI): this file was
``test_tui_tmux_engine.py`` through Task 17 — rewritten copies of the 5
legacy-engine scenarios (stream, tool line, markdown re-render, /tree,
byte-path Ctrl+C interrupt) that used to live in ``test_tui_tmux.py``
against ``pipython --engine=pi``, plus 3 new scenarios from spec §7.4:
autocomplete overlay appears and selection writes back; **scrollback
preservation** (three turns, then ``capture-pane -S -`` must still contain
the first turn's user echo — the soul assertion of this port); multiline
submit composed with Ctrl+J. Task 18 deleted the legacy engine and its
``test_tui_tmux.py`` outright (its 2 scenarios are strict subsets of the 5
rewritten here — see ``.superpowers/sdd/task-18-report.md``'s coverage
table) and renamed this file into the vacated ``test_tui_tmux.py`` slot,
dropping ``--engine=pi`` from the ``pipython`` invocation below (the pi-tui
engine is now the only engine, so there is no flag left to select it with).

Engine notes:

- Ready probe: the TUI prints no ``pipython · <model>`` banner — its first
  frame is the editor's border row (``"─" * width``), so readiness is
  polled as a long ``─`` run.
- Esc/Ctrl+C are asserted through the REAL byte path (Task 16 C1, issue
  #14): raw mode clears ISIG, so tmux ``send-keys Escape``/``C-c`` deliver
  the literal ``\\x1b``/``\\x03`` stdin bytes (verified with an instrumented
  ``RealTerminal``+``StdinBuffer`` dump under this exact tmux:
  ``kitty_enabled=False``, ``frame='\\x03'``) — exercising
  ``app._on_stdin_frame``'s byte branches, not a signal. Since issue #14,
  Escape is the one that interrupts an in-flight turn (routed through the
  key pipeline, ``"app.interrupt"``); Ctrl+C only clears the editor / double-
  tap-exits — see ``test_esc_interrupts_and_continues`` and
  ``test_ctrl_c_does_not_interrupt_but_double_tap_exits``.
- IME/CURSOR_MARKER pinning is a manual acceptance item (spec §7.5) and is
  not automated here; what IS asserted is that the marker bytes never leak
  into terminal output (``_extract_cursor_position`` must strip them before
  writing) — checked against ``capture-pane -e`` raw captures.
- All assertions are poll-based via ``tmux_util`` (no bare sleeps).
"""

import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from .tmux_util import TmuxPane

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux required")

FIXTURES = Path(__file__).parent / "fixtures"
TWO_TURN = FIXTURES / "fake_two_turn.json"
THREE_TURNS = FIXTURES / "fake_three_turns.json"
LONG_BASH_OUTPUT = FIXTURES / "fake_bash_long_output.json"

REPO_ROOT = Path(__file__).resolve().parents[2]

# 新引擎无启动横幅：首帧就是 editor 的边框行（"─"*width）——以长 ─ 连串为
# ready 探针（TTY 硬要求由 tmux pty 满足）。
READY = r"─{10,}"

# engine/tui.py CURSOR_MARKER = "\x1b_pi:c\x07"（APC 序列）。不 import 引擎
# 模块——e2e 与被测进程隔离，这里按字面钉住：若引擎哪天改 marker 字面量，
# 这两个常量必须同步改（等价于金标准断言）。
CURSOR_MARKER = "\x1b_pi:c\x07"
CURSOR_MARKER_PAYLOAD = "_pi:c"


def _start_pane(agent_cwd: Path, fixture: Path) -> TmuxPane:
    p = TmuxPane()
    # shell cwd = 项目根（uv 需要 pyproject）；agent 目标目录走 --cwd
    p.start(
        f"uv run --extra tui pipython --model fake/model --cwd {shlex.quote(str(agent_cwd))}",
        env={"PI_PYTHON_FAKE_SCRIPT": str(fixture)},
        cwd=str(REPO_ROOT),
    )
    p.wait_for(READY)
    return p


def _start_pane_sized(agent_cwd: Path, fixture: Path, *, cols: int, rows: int) -> TmuxPane:
    """Task 3 (phase-4 footer) narrow-pane scenario: `TmuxPane.start` itself
    hardcodes a fixed 100x30 `-x`/`-y` (its own module docstring), so this
    duplicates its two `tmux` calls (new-session + remain-on-exit) verbatim
    with a caller-chosen size instead of touching `tmux_util.py` (out of
    this task's file list) -- everything *after* the pane exists (`wait_for`/
    `capture`/`kill`, all from the shared `TmuxPane` instance) is still the
    real, unduplicated `tmux_util` machinery."""
    p = TmuxPane()
    env_prefix = f"PI_PYTHON_FAKE_SCRIPT={shlex.quote(str(fixture))}"
    cmd = f"uv run --extra tui pipython --model fake/model --cwd {shlex.quote(str(agent_cwd))}"
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            p.name,
            "-x",
            str(cols),
            "-y",
            str(rows),
            "-c",
            str(REPO_ROOT),
            f"{env_prefix} {cmd}",
        ],
        check=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-t", p.name, "remain-on-exit", "on"],
        check=True,
    )
    p.wait_for(READY)
    return p


def _send_raw(pane: TmuxPane, *keys: str) -> None:
    """send-keys 不带 Enter（TmuxPane.send 总是追加 Enter，编辑器内组稿/触发
    补全需要裸键）。"""
    subprocess.run(["tmux", "send-keys", "-t", pane.name, *keys], check=True)


def _capture_history(pane: TmuxPane) -> str:
    """整个 scrollback + 可见屏（capture -S -）——滚动历史保留断言专用。"""
    out = subprocess.run(
        ["tmux", "capture-pane", "-p", "-J", "-S", "-", "-t", pane.name],
        capture_output=True,
        text=True,
    )
    return out.stdout


def _capture_raw(pane: TmuxPane) -> str:
    """带转义序列的 capture（-e）——CURSOR_MARKER 泄漏检查用。"""
    out = subprocess.run(
        ["tmux", "capture-pane", "-p", "-e", "-t", pane.name],
        capture_output=True,
        text=True,
    )
    return out.stdout


def _wait_for_in_history(pane: TmuxPane, pattern: str, timeout: float = 10.0) -> str:
    """Like ``TmuxPane.wait_for``, but polls the full scrollback
    (``capture -S -``) instead of just the current visible screen — needed
    when the awaited content may have already scrolled past the top of a
    fixed-height (30-row) tmux window by the time we poll (e.g. a tool
    header rendered above a long, still-growing collapsed-preview body)."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = _capture_history(pane)
        if re.search(pattern, last):
            return last
        time.sleep(0.2)
    raise AssertionError(
        f"pattern {pattern!r} not seen in scrollback within {timeout}s; last:\n{last}"
    )


def _assert_no_marker_leak(pane: TmuxPane) -> None:
    raw = _capture_raw(pane)
    assert CURSOR_MARKER not in raw
    assert CURSOR_MARKER_PAYLOAD not in raw
    assert CURSOR_MARKER_PAYLOAD not in pane.capture()


@pytest.fixture
def pane(tmp_path):
    (tmp_path / "hello.txt").touch()
    p = _start_pane(tmp_path, TWO_TURN)
    yield p
    p.kill()


# =============================================================================
# 原 5 个 legacy-engine 场景的重写副本（stream / tool line / markdown / tree /
# interrupt；exit 语义并入 stream 场景，与旧文件的组合方式一致）。
# =============================================================================


def test_stream_full_turn_and_exit(pane):
    pane.send("do something")
    pane.wait_for(r"do something")  # user 回显进 transcript
    pane.wait_for(r"let me look")  # 流式期 Text 增量
    pane.wait_for(r"I saw the files")  # 完稿正文
    _assert_no_marker_leak(pane)
    pane.send_ctrl_d()
    pane.wait_for(r"session: ")  # 统一出口打印路径（wrap=False 单行直出）
    pane.wait_dead()  # 进程真正退出，不是卡在打印这行之后
    # 滚动区留痕：退出后 capture 仍包含对话内容
    assert "I saw the files" in pane.capture()


def test_tool_call_line(pane):
    pane.send("do something")
    # Task-19 acceptance follow-up: the tool line is now a styled
    # ToolExecution component (bold header + state-tinted background),
    # not a plain "[tool] <name> <args>" line — header still shows the
    # tool name + truncated args JSON, and (new) a successful result's
    # content is shown too (collapsed inside the component), not silently
    # dropped.
    pane.wait_for(r'ls \{"path"')  # 工具头（含参数 JSON 截断渲染）
    pane.wait_for(r"hello\.txt")  # 成功结果内容现在会显示（收纳进组件背景内）
    pane.wait_for(r"I saw the files")  # 回合完整走完


def test_tool_execution_styled_header_and_ctrl_o_expands(tmp_path):
    """New scenario (task-19 acceptance follow-up): a bash tool call whose
    output exceeds the collapsed preview (5 lines, ``core/tools/bash.ts``'s
    real ``BASH_PREVIEW_LINES``) renders a styled "$ <command>" header,
    collapses to its tail with a "more lines" hint, and
    Ctrl+O (``\\x0f``) expands it to show a marker line from the otherwise-
    hidden head of the output (``seq 1 30``'s first line, "1", polled via
    the full scrollback since the 30-row tmux window may have already
    scrolled the header/early lines past the visible screen by the time
    the turn finishes)."""
    p = _start_pane(tmp_path, LONG_BASH_OUTPUT)
    try:
        p.send("count please")
        _wait_for_in_history(p, r"\$ seq 1 30")  # styled bash header
        p.wait_for(r"counted them all")  # turn completed
        _wait_for_in_history(p, r"more lines")  # collapsed hint present
        # Trailing spaces are real here: apply_background_to_line pads every
        # row out to the full terminal width so the tinted background fills
        # it — "1" is followed by padding, never immediately by "$".
        assert not re.search(r"(?m)^1\s*$", _capture_history(p)), (
            "line '1' (seq's first output line) must be hidden while collapsed"
        )

        _send_raw(p, "C-o")  # Ctrl+O: expand

        _wait_for_in_history(p, r"(?m)^1\s*$")  # now visible: full output expanded
    finally:
        p.kill()


def test_markdown_rerender_at_message_end(pane):
    pane.send("do something")
    # message_end 原地替换后，"# Result" 源文本变成样式化的 "Result" 标题行
    pane.wait_for(r"(?m)^Result")
    assert "# Result" not in pane.capture()
    pane.wait_for(r"I saw the files")


def test_tree_command(pane):
    pane.send("do something")
    pane.wait_for(r"I saw the files")
    pane.send("/tree")
    pane.wait_for(r"←")  # 叶子标记（纯 ANSI 树渲染路径）
    pane.wait_for(r"└──")  # 连接符
    pane.wait_for(r"user: do something")  # user 消息摘要在树里


def test_hotkeys_and_session_commands(pane):
    # Phase-4 self-contained commands (task-2): /hotkeys renders the grouped
    # key-help table (Navigation section + a _format_key-formatted binding),
    # /session renders the "Session Info" stats block. Neither needs a prior
    # turn — both work standalone against a fresh session. /hotkeys' table
    # is long enough to scroll the "Navigation" section off the fixed
    # 30-row pane before we poll, so this uses the full-scrollback poll
    # helper (_wait_for_in_history), same as the Ctrl+O expand scenario
    # above, instead of pane.wait_for (visible screen only).
    pane.send("/hotkeys")
    _wait_for_in_history(pane, r"Navigation")
    _wait_for_in_history(pane, r"Ctrl\+B")  # formatted cursor-left binding
    pane.send("/session")
    pane.wait_for(r"Session Info")


def test_esc_interrupts_and_continues(tmp_path):
    """Issue #14 (Esc/Ctrl+C parity fix): this test used to be named
    ``test_ctrl_c_interrupts_and_continues`` and drove the interrupt via
    ``send_ctrl_c()`` — backwards relative to upstream (Esc aborts an
    in-flight turn; Ctrl+C only clears the editor + double-tap-exits, see
    ``test_ctrl_c_does_not_interrupt_but_double_tap_exits`` below). Renamed
    and rewritten to drive the interrupt via a real Escape keypress instead,
    exercising the same real byte path (Task 16 C1's tmux verification
    notes still apply: raw mode has ISIG cleared, so ``send-keys Escape``
    delivers the literal ``\\x1b`` stdin byte) all the way through
    ``_on_stdin_frame`` -> ``tui.handle_input`` -> the focused editor's
    ``handle_key`` -> ``"app.interrupt"`` (engine/keybindings.py) ->
    ``editor.on_app_action`` -> ``app.py``'s ``_on_app_action`` ->
    ``turn_task.cancel()``."""
    # 让工具真实卡住：脚本第 1 条调用 bash sleep；第 2 条是中断后下一轮的应答
    slow = tmp_path / "slow.json"
    slow.write_text(
        '[{"role":"assistant","content":[{"type":"toolCall","id":"t1",'
        '"name":"bash","arguments":{"command":"sleep 30"}}]},'
        '{"role":"assistant","content":[{"type":"text","text":"resumed fine"}]}]'
    )
    p2 = _start_pane(tmp_path, slow)
    try:
        p2.send("go")
        # Task-19 acceptance follow-up: bash's ToolExecution header is
        # "$ <command>" (bash-execution.ts format), not the old
        # "[tool] bash ..." plain-text line.
        p2.wait_for(r"\$ sleep 30")
        # Issue #14: Ctrl+C must NOT interrupt the turn anymore — send it
        # first and confirm the tool call is still running before the real
        # interrupt key (Escape) below.
        p2.send_ctrl_c()
        time.sleep(0.5)  # give the (now turn-unaffected) Ctrl+C byte a moment to be processed
        assert "[interrupted]" not in p2.capture()
        assert "$ sleep 30" in p2.capture()  # the tool call is still running
        # 真字节路径（Task 16 C1）：raw mode 已清 ISIG，send-keys Escape 送达的是
        # stdin 字节 \x1b，走 "app.interrupt" -> `_on_app_action` -> turn_task.cancel()
        _send_raw(p2, "Escape")
        p2.wait_for(r"\[interrupted\]")
        # 中断后可继续交互：下一轮 prompt 正常出应答
        p2.send("again")
        p2.wait_for(r"resumed fine")
        p2.send("/quit")
        p2.wait_for(r"session: ")
        p2.wait_dead()
    finally:
        p2.kill()


def test_ctrl_c_does_not_interrupt_but_double_tap_exits(tmp_path):
    """Issue #14: Ctrl+C's real production behavior now — a single Ctrl+C
    clears the editor's draft buffer without touching an in-flight turn (see
    ``test_esc_interrupts_and_continues`` above for the tool-call variant),
    and a second Ctrl+C within 500ms quits the app (upstream's
    double-tap-to-exit, ``interactive-mode.ts``'s ``handleCtrlC``)."""
    p2 = _start_pane(tmp_path, TWO_TURN)
    try:
        _send_raw(p2, "an unsent draft")
        p2.wait_for(r"an unsent draft")

        p2.send_ctrl_c()  # first Ctrl+C: clears the draft, does not quit
        # Keep the gap comfortably under the 500ms double-tap window — capture()
        # + send overhead below still has to land the 2nd press inside it.
        time.sleep(0.2)
        scr = p2.capture()
        assert "an unsent draft" not in scr
        assert p2.alive()

        p2.send_ctrl_c()  # second Ctrl+C, well within 500ms: quits
        p2.wait_for(r"session: ")
        p2.wait_dead()
    finally:
        p2.kill()


# =============================================================================
# 三条新场景（spec §7.4）
# =============================================================================


def test_autocomplete_overlay_appears_and_writes_back(tmp_path):
    (tmp_path / "alpha.txt").touch()
    (tmp_path / "hello.txt").touch()
    p2 = _start_pane(tmp_path, TWO_TURN)
    try:
        # "@alp" 中缀触发 PathProvider（防抖 20ms 后浮层出现）
        _send_raw(p2, "look at @alp")
        p2.wait_for(r"→ alpha\.txt")  # 浮层选中行（accent 高亮 + → 前缀）
        _assert_no_marker_leak(p2)
        # Tab 应用选中项：prefix "@alp" 被替换为 "@alpha.txt "（尾随空格），
        # 浮层关闭，编辑器缓冲区回写完成
        _send_raw(p2, "Tab")
        scr = p2.wait_for(r"look at @alpha\.txt")
        assert "→ alpha.txt" not in scr  # 回写帧同时关闭了浮层
    finally:
        p2.kill()


def test_scrollback_preserves_first_turn(tmp_path):
    # 灵魂断言（spec §1/§7.4）：本移植存在的意义就是不清屏、不进备用屏——
    # 三轮长对话把第一轮顶出可见区后，第一轮的 user 回显必须还活在
    # scrollback（capture -S -）里。
    p2 = _start_pane(tmp_path, THREE_TURNS)
    try:
        p2.send("scrollback anchor turn one")
        p2.wait_for(r"reply one paragraph 08")
        p2.send("turn two prompt")
        p2.wait_for(r"reply two paragraph 08")
        p2.send("turn three prompt")
        p2.wait_for(r"reply three paragraph 08")

        # 前提自检：第一轮回显确实已经滚出可见屏（不然下面的断言是空话）
        assert "scrollback anchor turn one" not in p2.capture()
        history = _capture_history(p2)
        assert "scrollback anchor turn one" in history  # 灵魂断言
        assert "reply one paragraph 01" in history  # 第一轮正文同样健在
    finally:
        p2.kill()


def test_multiline_submit_via_ctrl_j(pane):
    _send_raw(pane, "first multiline row")
    _send_raw(pane, "C-j")  # Ctrl+J（裸 \n 帧）在编辑器内组多行，不提交
    _send_raw(pane, "second multiline row")
    # 提交前两行都在编辑器里可见（第二行的按键回显必须实时渲染）
    pane.wait_for(r"second multiline row")
    _send_raw(pane, "Enter")
    pane.wait_for(r"I saw the files")  # 多行文本作为单次提交走完一轮
    cap = pane.capture()
    # 编辑器已清空，两行都以 user 回显形式留在 transcript
    assert "first multiline row" in cap
    assert "second multiline row" in cap


# =============================================================================
# Task 3 (phase-4 footer): footer wired in against a REAL git repo (not the
# fakes tests/tui/test_app.py drives GitBranchProvider through), plus a
# narrow/short real-pty pane proving the footer's 2 extra bottom rows don't
# push the editor's own cursor out of the viewport.
# =============================================================================

_FOOTER_BRANCH = "e2ebranch"


def _make_short_git_repo(branch: str) -> Path:
    """A real `git init`'d repo for `GitBranchProvider` to read HEAD from.
    Deliberately NOT pytest's own `tmp_path` fixture: that fixture nests
    under the test's own (often long, node-id-derived) directory name, and
    the footer truncates its pwd+branch line to the terminal's width
    (footer.py's `truncate_to_width`, keeps the *front*, drops the tail) --
    a long enough tmp_path would silently truncate away the very
    `(<branch>)` suffix this scenario asserts on, even on the default
    100-column pane. A short, manually-managed dir under `/tmp` avoids that
    entirely, on any pane width this test uses."""
    d = Path(tempfile.mkdtemp(prefix="pyfoot-", dir="/tmp"))
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=str(d), check=True)
    return d


def test_footer_shows_real_git_branch_and_survives_narrow_pane():
    repo = _make_short_git_repo(_FOOTER_BRANCH)
    try:
        # -- default-size pane: footer's cwd line shows the real branch,
        # resolved from the repo's actual .git/HEAD (GitBranchProvider,
        # Task 1) -- not a FakeClient/test-double stand-in.
        p = _start_pane(repo, TWO_TURN)
        try:
            p.wait_for(rf"\({re.escape(_FOOTER_BRANCH)}\)")
        finally:
            p.kill()

        # -- narrow/short pane: the footer is wired as the LAST child of
        # the root Container (app.py), after the editor, so it occupies
        # the tree's bottom-most 2 rows -- exactly where engine/tui.py's
        # viewport math (`viewport_top = max(0, len(lines) - height)`,
        # `_extract_cursor_position` only scans the bottom `height` rows)
        # could in principle clip the editor's own cursor row once the
        # terminal is short enough that editor+footer alone approach the
        # full height. A regression here would surface as: what you just
        # typed genuinely never appears in the capture -- editor.py always
        # re-renders its own row with the typed text every frame regardless
        # of hardware-cursor visibility, so a missing echo means the row
        # itself scrolled out of the visible window, not just a hidden
        # cursor.
        p2 = _start_pane_sized(repo, TWO_TURN, cols=50, rows=12)
        try:
            p2.wait_for(rf"\({re.escape(_FOOTER_BRANCH)}\)")
            _send_raw(p2, "narrow pane echo check")
            p2.wait_for(r"narrow pane echo check")
        finally:
            p2.kill()
    finally:
        shutil.rmtree(repo, ignore_errors=True)
