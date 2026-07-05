"""Git branch detection + polling, ported from pi's footer-data-provider.ts.

Deviation: upstream uses fs watch (Node watchFile); this port polls HEAD's
mtime on an asyncio task (POSIX-portable, low churn). reftable-backend ref
switches that don't touch HEAD mtime are not observed (phase-4 follow-up).
"""

import asyncio
import contextlib
import subprocess
from collections.abc import Callable
from pathlib import Path


def find_git_head(cwd: Path) -> Path | None:
    try:
        d = cwd.resolve()
        while True:
            git = d / ".git"
            if git.is_dir():
                return git / "HEAD"
            if git.is_file():
                content = git.read_text(errors="replace").strip()
                if content.startswith("gitdir: "):
                    git_dir = (d / content[len("gitdir: ") :].strip()).resolve()
                    return git_dir / "HEAD"
                return None
            if d.parent == d:
                return None
            d = d.parent
    except OSError:
        # transient fs hiccup walking up (permission race, unmount, etc.) —
        # treat like "not a git repo" instead of propagating (matches
        # upstream's findGitPaths catch -> null).
        return None


def read_branch(cwd: Path) -> str | None:
    try:
        head = find_git_head(cwd)
        if head is None or not head.is_file():
            return None
        content = head.read_text(errors="replace").strip()
    except OSError:
        # TOCTOU: HEAD (or the .git indirection file) can vanish or become
        # unreadable between the checks above and the read — matches
        # upstream's resolveGitBranchSync/Async catch -> null.
        return None
    if content.startswith("ref: refs/heads/"):
        branch = content[len("ref: refs/heads/") :]
        if branch != ".invalid":
            return branch
        # rare .invalid sentinel: fall back to git subprocess (upstream :243-245)
        try:
            r = subprocess.run(
                ["git", "--no-optional-locks", "symbolic-ref", "--quiet", "--short", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = r.stdout.strip()
            return out or "detached"
        except (subprocess.SubprocessError, OSError):
            return "detached"
    # detached HEAD: content is a raw commit sha, not a ref
    return "detached"


class GitBranchProvider:
    def __init__(self, cwd: Path, poll_interval: float = 2.0):
        self._cwd = Path(cwd)
        self._interval = poll_interval
        self._head = find_git_head(self._cwd)
        self.current_branch: str | None = read_branch(self._cwd)
        # B2 fix: capture mtime baseline at construction (same instant as
        # current_branch), NOT inside _poll — start() has no await, so _poll's
        # body first runs only after the caller yields, by which point the
        # branch may already have changed → a body-local baseline would miss it.
        self._last_mtime = self._mtime()
        self._task: asyncio.Task[None] | None = None

    async def start(self, on_change: Callable[[], None]) -> None:
        self._task = asyncio.ensure_future(self._poll(on_change))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _poll(self, on_change: Callable[[], None]) -> None:
        while True:
            await asyncio.sleep(self._interval)
            m = self._mtime()
            if m == self._last_mtime:
                continue
            self._last_mtime = m
            try:
                # read_branch's rare .invalid-sentinel fallback shells out to
                # git synchronously (subprocess.run, timeout=2s); offload to a
                # worker thread so that rare stall never blocks this event
                # loop (upstream keeps a matching sync/async split precisely
                # to avoid this).
                new_branch = await asyncio.get_running_loop().run_in_executor(
                    None, read_branch, self._cwd
                )
            except OSError:
                # read_branch already guards OSError internally and returns
                # None instead of raising; this is belt-and-suspenders so a
                # single bad read can never take down the background poll
                # task.
                continue
            if new_branch != self.current_branch:
                self.current_branch = new_branch
                on_change()

    def _mtime(self) -> float | None:
        if self._head is None:
            return None
        try:
            return self._head.stat().st_mtime
        except OSError:
            return None
