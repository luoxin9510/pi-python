"""Completers for the pi-python TUI: fuzzy @path and /command completion."""

import asyncio
import os
import re
from pathlib import Path

import pathspec
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from rapidfuzz import process as fuzz_process

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


class PiCompleter(Completer):
    def __init__(self, commands: dict[str, str]):
        self.commands = commands
        self.file_list: list[str] = []

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        if document.text.startswith("/") and "\n" not in document.text:
            frag = text[1:]
            for name, desc in sorted(self.commands.items()):
                if name.startswith(frag):
                    yield Completion(f"/{name}", start_position=-len(text), display_meta=desc)
            return
        m = AT_FRAGMENT_RE.search(text)
        if not m:
            return
        frag = m.group(1)
        if not frag:
            candidates = self.file_list[:10]
        else:
            candidates = [x for x, _, _ in fuzz_process.extract(frag, self.file_list, limit=10)]
        for path in candidates:
            yield Completion(path, start_position=-len(frag), display_meta="file")
