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
- Ctrl+C is asserted through the REAL byte path (Task 16 C1): raw mode
  clears ISIG, so tmux ``send-keys C-c`` delivers the literal ``\\x03``
  stdin byte (verified with an instrumented ``RealTerminal``+``StdinBuffer``
  dump under this exact tmux: ``kitty_enabled=False``, ``frame='\\x03'``) —
  exercising ``app._on_stdin_frame``'s byte branch, not a signal.
- IME/CURSOR_MARKER pinning is a manual acceptance item (spec §7.5) and is
  not automated here; what IS asserted is that the marker bytes never leak
  into terminal output (``_extract_cursor_position`` must strip them before
  writing) — checked against ``capture-pane -e`` raw captures.
- All assertions are poll-based via ``tmux_util`` (no bare sleeps).
"""

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from .tmux_util import TmuxPane

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux required")

FIXTURES = Path(__file__).parent / "fixtures"
TWO_TURN = FIXTURES / "fake_two_turn.json"
THREE_TURNS = FIXTURES / "fake_three_turns.json"

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
    pane.wait_for(r"\[tool\] ls")  # 工具行（含参数 JSON 截断渲染）
    pane.wait_for(r"I saw the files")  # 回合完整走完


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


def test_ctrl_c_interrupts_and_continues(tmp_path):
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
        p2.wait_for(r"\[tool\] bash")
        # 真字节路径（Task 16 C1）：raw mode 已清 ISIG，send-keys C-c 送达的是
        # stdin 字节 \x03，走 _on_stdin_frame 的 turn_task.cancel() 分支
        p2.send_ctrl_c()
        p2.wait_for(r"\[interrupted\]")
        # 中断后可继续交互：下一轮 prompt 正常出应答
        p2.send("again")
        p2.wait_for(r"resumed fine")
        p2.send("/quit")
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
