from pathlib import Path
from typing import cast

import pytest

from pipython.tools.base import ToolContext
from pipython.tools.find import FindParams, find_tool
from pipython.tools.grep import GrepParams, grep_tool


def g(**kw) -> GrepParams:
    return cast(GrepParams, grep_tool.params_model(**kw))


def f(**kw) -> FindParams:
    return cast(FindParams, find_tool.params_model(**kw))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("def hello():\n    return 'Hello World'\n")
    (tmp_path / "src/b.ts").write_text("const hello = 1\n")
    return tmp_path


@pytest.fixture(params=["rg", "fallback"])
def mode(request, monkeypatch):
    if request.param == "rg":
        import shutil

        assert shutil.which("rg"), "ripgrep 未安装——rg 主路径不许静默退化，先 brew install ripgrep"
    else:
        monkeypatch.setattr("pipython.tools.grep._HAS_RG", False)
        monkeypatch.setattr("pipython.tools.find._HAS_RG", False)
    return request.param


async def test_grep_finds_with_line_numbers(repo, mode):
    r = await grep_tool.execute(g(pattern="hello"), ToolContext(cwd=repo))
    assert not r.is_error and "a.py" in r.content and "1" in r.content and "b.ts" in r.content


async def test_grep_glob_and_ignorecase(repo, mode):
    r = await grep_tool.execute(
        g(pattern="HELLO", glob="*.py", ignoreCase=True), ToolContext(cwd=repo)
    )
    assert "a.py" in r.content and "b.ts" not in r.content


async def test_grep_literal_no_regex(repo, mode):
    (repo / "src/c.txt").write_text("a.b\naxb\n")
    r = await grep_tool.execute(g(pattern="a.b", literal=True), ToolContext(cwd=repo))
    assert "a.b" in r.content and "axb" not in r.content


async def test_grep_no_match_message(repo, mode):
    r = await grep_tool.execute(g(pattern="zzz9"), ToolContext(cwd=repo))
    assert not r.is_error and "no match" in r.content.lower()


async def test_find_glob(repo, mode):
    r = await find_tool.execute(f(pattern="**/*.py"), ToolContext(cwd=repo))
    assert "src/a.py" in r.content and "b.ts" not in r.content


@pytest.fixture
def symlinked_repo(tmp_path: Path) -> Path:
    """cwd 含符号链接组件（如 macOS 的 /tmp → /private/tmp）的回归场景。"""
    real = tmp_path / "real"
    (real / "src").mkdir(parents=True)
    (real / "src/a.py").write_text("def hello():\n    return 'Hello World'\n")
    link = tmp_path / "symlink"
    link.symlink_to(real)
    return link


async def test_grep_symlinked_cwd(symlinked_repo, mode):
    r = await grep_tool.execute(g(pattern="hello"), ToolContext(cwd=symlinked_repo))
    assert not r.is_error and "a.py" in r.content and "ValueError" not in r.content


async def test_find_symlinked_cwd(symlinked_repo, mode):
    r = await find_tool.execute(f(pattern="**/*.py"), ToolContext(cwd=symlinked_repo))
    assert not r.is_error and "src/a.py" in r.content and "ValueError" not in r.content
