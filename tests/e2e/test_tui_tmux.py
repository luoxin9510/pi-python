import shlex
import shutil
from pathlib import Path

import pytest

from .tmux_util import TmuxPane

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux required")

FIXTURE = Path(__file__).parent / "fixtures" / "fake_two_turn.json"


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pane(tmp_path):
    (tmp_path / "hello.txt").touch()
    p = TmuxPane()
    # shell cwd = 项目根（uv 需要 pyproject）；agent 目标目录走 --cwd
    p.start(
        f"uv run --extra tui pipython --model fake/model --cwd {shlex.quote(str(tmp_path))}",
        env={"PI_PYTHON_FAKE_SCRIPT": str(FIXTURE)},
        cwd=str(REPO_ROOT),
    )
    p.wait_for(r"pipython · fake/model")  # 启动横幅 = ready 探针
    yield p
    p.kill()


def test_full_turn_stream_tool_markdown_tree_exit(pane):
    pane.send("do something")
    pane.wait_for(r"\[tool\] ls")  # 工具行
    pane.wait_for(r"Result")  # markdown 完稿重排（# Result 标题）
    pane.wait_for(r"I saw the files")
    pane.send("/tree")
    pane.wait_for(r"←")  # 树 + 叶子标记
    pane.wait_for(r"do something")  # user 消息摘要在树里
    pane.send_ctrl_d()
    pane.wait_for(r"session: ")  # 统一出口打印路径
    # 滚动区留痕：退出后 capture 仍包含对话内容
    assert "I saw the files" in pane.capture()


def test_ctrl_c_interrupts_back_to_prompt(pane, tmp_path):
    # 让工具真实卡住：脚本第 1 条调用 bash sleep（重写单用例专用 fixture）
    slow = tmp_path / "slow.json"
    slow.write_text(
        '[{"role":"assistant","content":[{"type":"toolCall","id":"t1",'
        '"name":"bash","arguments":{"command":"sleep 30"}}]},'
        '{"role":"assistant","content":[{"type":"text","text":"never"}]}]'
    )
    p2 = TmuxPane()
    p2.start(
        f"uv run --extra tui pipython --model fake/model --cwd {shlex.quote(str(tmp_path))}",
        env={"PI_PYTHON_FAKE_SCRIPT": str(slow)},
        cwd=str(REPO_ROOT),
    )
    try:
        p2.wait_for(r"pipython ·")
        p2.send("go")
        p2.wait_for(r"\[tool\] bash")
        p2.send_ctrl_c()
        p2.wait_for(r"\[interrupted\]")
        p2.send("/quit")
        p2.wait_for(r"session: ")
    finally:
        p2.kill()
