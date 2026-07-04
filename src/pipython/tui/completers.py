"""File-list building for the pi-python TUI's ``@path`` completion.

Task 18 (pi-tui engine becomes the only TUI): ``PiCompleter`` — the
``prompt_toolkit.completion.Completer`` subclass that drove the legacy
engine's ``@``-fuzzy (``rapidfuzz``-scored) and ``/``-command completion — is
retired along with the legacy engine and the ``prompt_toolkit``/``rapidfuzz``
dependencies it required. The pi-tui engine's own completion path
(``components/autocomplete.py``'s ``PathProvider``/``CommandProvider``/
``CombinedProvider``, wired into ``Editor.set_autocomplete_provider``) is the
sole surviving completer; it already reuses this module's ``AT_FRAGMENT_RE``
and ``build_file_list`` unmodified (see that module's docstring). Equivalence
for ``PiCompleter``'s retired fuzzy-@ and slash-completion behavior is pinned
by ``tests/tui/components/test_autocomplete_providers.py`` (see
``.superpowers/sdd/task-18-report.md``'s coverage table).
"""

import asyncio
import os
import re
from pathlib import Path

import pathspec

AT_FRAGMENT_RE = re.compile(r"@([^\s@]*)$")
_FILE_LIMIT = 5000


async def _git_ls_files(cwd: Path) -> list[str] | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        return out.decode(errors="replace").splitlines()
    except FileNotFoundError:
        return None


def _walk_with_pathspec(cwd: Path, cap: int = _FILE_LIMIT) -> list[str]:
    gitignore = cwd / ".gitignore"
    spec = None
    if gitignore.is_file():
        spec = pathspec.GitIgnoreSpec.from_lines(gitignore.read_text().splitlines())
    results: list[str] = []
    for root, dirs, files in os.walk(cwd):
        rel_root = Path(root).relative_to(cwd)
        # dirs/files 排序：OS 的 scandir 顺序不可依赖，补全建议必须与文件系统/
        # 平台无关地确定性排序（issue #3），而不是等到最后才排一次。
        dirs[:] = sorted(
            d
            for d in dirs
            if d != ".git" and not (spec and spec.match_file(str(rel_root / d) + "/"))
        )
        for f in sorted(files):
            rel = str(rel_root / f) if str(rel_root) != "." else f
            if spec and spec.match_file(rel):
                continue
            results.append(rel)
            if len(results) >= cap:
                return sorted(results)
    return sorted(results)


async def build_file_list(cwd: Path, limit: int = _FILE_LIMIT) -> list[str]:
    files = await _git_ls_files(cwd)
    if files is None:
        # 内部 walk 的安全上限跟随更小的调用方 limit：避免为一个只要 10 条的
        # 补全请求去走一整棵大到 5000 条的非 git 目录树（issue #3）。
        cap = min(_FILE_LIMIT, limit)
        files = await asyncio.get_running_loop().run_in_executor(
            None, _walk_with_pathspec, cwd, cap
        )
    return files[:limit]
