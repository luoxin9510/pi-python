import subprocess
from pathlib import Path

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from pipython.tui.completers import AT_FRAGMENT_RE, PiCompleter, build_file_list


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/calculator.py").touch()
    (tmp_path / "src/calibrate.py").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/junk.js").touch()
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    return tmp_path


def completions(completer, text):
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, CompleteEvent())]


async def test_build_file_list_git(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    files = await build_file_list(repo)
    assert "src/calculator.py" in files and "node_modules/junk.js" not in files


async def test_build_file_list_fallback_pathspec(repo):
    files = await build_file_list(repo)  # 非 git → walk + pathspec
    assert "src/calculator.py" in files
    assert "node_modules/junk.js" not in files and ".gitignore" in files


async def test_build_file_list_fallback_sorted(tmp_path: Path):
    # 乱序创建，验证非 git fallback walk 输出确定性排序（issue #3）——OS/文件系统
    # 的 scandir 顺序不可依赖，输出必须与创建顺序无关，始终字典序。
    for name in ["zeta.txt", "alpha.txt", "mu.txt", "beta.txt"]:
        (tmp_path / name).touch()
    files = await build_file_list(tmp_path)
    assert files == sorted(files)
    assert files == ["alpha.txt", "beta.txt", "mu.txt", "zeta.txt"]


async def test_build_file_list_fallback_limit_honored(tmp_path: Path):
    # caller limit 小于文件总数时，必须精确返回排序后的前 limit 个（issue #3）。
    names = [f"file{i:02d}.txt" for i in range(12)]
    for name in names:
        (tmp_path / name).touch()
    files = await build_file_list(tmp_path, limit=10)
    assert files == sorted(names)[:10]


async def test_at_fuzzy_completion(repo):
    completer = PiCompleter(commands={})
    completer.file_list = await build_file_list(repo)
    got = completions(completer, "please look at @calc")
    assert got and got[0] == "src/calculator.py"


def test_at_fragment_boundary():
    assert AT_FRAGMENT_RE.search("see @src/ab") is not None
    assert AT_FRAGMENT_RE.search("email a@b c") is None  # 空白断开，光标前无活动片段


def test_slash_completion_with_meta():
    completer = PiCompleter(commands={"model": "切换模型", "tree": "查看会话树"})
    got = completions(completer, "/mo")
    assert got == ["/model"]
    assert completions(completer, "hello /mo") == []  # 仅行首


def test_slash_completion_suppressed_in_multiline():
    completer = PiCompleter(commands={"model": "切换模型", "tree": "查看会话树"})
    # 多行缓冲：光标位于内嵌换行之前（"/model" 末尾），不应触发斜杠补全
    doc = Document(text="/model\nsecond line", cursor_position=6)
    got = [c.text for c in completer.get_completions(doc, CompleteEvent())]
    assert got == []
