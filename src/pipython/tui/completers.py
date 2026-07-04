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


def _walk_with_pathspec(cwd: Path) -> list[str]:
    gitignore = cwd / ".gitignore"
    spec = None
    if gitignore.is_file():
        spec = pathspec.GitIgnoreSpec.from_lines(gitignore.read_text().splitlines())
    results: list[str] = []
    for root, dirs, files in os.walk(cwd):
        rel_root = Path(root).relative_to(cwd)
        dirs[:] = [
            d
            for d in dirs
            if d != ".git" and not (spec and spec.match_file(str(rel_root / d) + "/"))
        ]
        for f in files:
            rel = str(rel_root / f) if str(rel_root) != "." else f
            if spec and spec.match_file(rel):
                continue
            results.append(rel)
            if len(results) >= _FILE_LIMIT:
                return results
    return results


async def build_file_list(cwd: Path, limit: int = _FILE_LIMIT) -> list[str]:
    files = await _git_ls_files(cwd)
    if files is None:
        files = await asyncio.get_running_loop().run_in_executor(None, _walk_with_pathspec, cwd)
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
