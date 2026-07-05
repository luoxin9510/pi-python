"""Tests for ``pipython.tui.completers``: file-list building + the shared
``AT_FRAGMENT_RE`` regex.

Task 18 (pi-tui engine becomes the only TUI): this file used to also test
``PiCompleter`` (the ``prompt_toolkit.completion.Completer`` subclass the
legacy engine used for ``@``-fuzzy and ``/``-command completion). ``rich``/
``prompt_toolkit``/``rapidfuzz`` are dropped from ``pyproject.toml``
entirely along with the legacy engine, so those tests are deleted rather
than kept — their regression coverage is not lost, though: it has an
existing, already-passing equivalent in
``tests/tui/components/test_autocomplete_providers.py``, whose module
docstring explicitly documents itself as the translation target for this
file's ``@``-fuzzy-completion and multiline-suppression cases (see e.g.
``TestPathProviderRealFsIntegration.test_bridges_real_build_file_list_over_tmp_path``
and ``TestCommandProviderTrigger.test_suppressed_in_multiline_buffer``).
``build_file_list``/``AT_FRAGMENT_RE`` themselves have zero
prompt_toolkit/rapidfuzz dependency and are still the completion path's
shared foundation (``components/autocomplete.py`` imports both unmodified),
so their tests below are unchanged.
"""

import subprocess
from pathlib import Path

import pytest

from pipython.tui.completers import AT_FRAGMENT_RE, build_file_list


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/calculator.py").touch()
    (tmp_path / "src/calibrate.py").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/junk.js").touch()
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    return tmp_path


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


def test_at_fragment_boundary():
    assert AT_FRAGMENT_RE.search("see @src/ab") is not None
    assert AT_FRAGMENT_RE.search("email a@b c") is None  # 空白断开，光标前无活动片段
