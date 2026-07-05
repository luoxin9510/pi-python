import asyncio
import subprocess
from pathlib import Path

import pytest

from pipython.tui.components import git_branch
from pipython.tui.components.git_branch import (
    GitBranchProvider,
    find_git_head,
    read_branch,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("x")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_read_branch_returns_current(repo: Path):
    assert read_branch(repo) == "main"


def test_read_branch_after_switch(repo: Path):
    _git(repo, "checkout", "-b", "feature")
    assert read_branch(repo) == "feature"


def test_read_branch_detached_returns_detached(repo: Path):
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(repo, "checkout", sha)
    assert read_branch(repo) == "detached"


def test_read_branch_non_git_returns_none(tmp_path: Path):
    assert read_branch(tmp_path) is None


def test_find_git_head_regular(repo: Path):
    head = find_git_head(repo)
    assert head is not None and head.name == "HEAD" and head.parent.name == ".git"


def test_find_git_head_worktree(repo: Path, tmp_path: Path):
    wt = tmp_path.parent / "wt"
    _git(repo, "worktree", "add", str(wt))
    head = find_git_head(wt)
    assert head is not None and head.name == "HEAD" and head.read_text().strip()
    # worktree read_branch works through the .git-file gitdir indirection
    assert read_branch(wt) is not None


def test_find_git_head_walks_up(repo: Path):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert find_git_head(sub) is not None


async def test_provider_initial_branch(repo: Path):
    p = GitBranchProvider(repo)
    assert p.current_branch == "main"


async def test_provider_polls_and_calls_on_change(repo: Path):
    p = GitBranchProvider(repo, poll_interval=0.02)
    changed = asyncio.Event()
    await p.start(on_change=changed.set)
    try:
        _git(repo, "checkout", "-b", "feature")
        await asyncio.wait_for(changed.wait(), timeout=3.0)
        assert p.current_branch == "feature"
    finally:
        await p.stop()


async def test_provider_stop_cancels_cleanly(repo: Path):
    p = GitBranchProvider(repo, poll_interval=0.02)
    await p.start(on_change=lambda: None)
    await p.stop()
    await p.stop()  # idempotent, no raise


def test_read_branch_invalid_sentinel_falls_back(repo: Path):
    # HEAD holding the .invalid sentinel must route to the git-subprocess
    # fallback (upstream footer-data-provider.ts:243-245), not return
    # ".invalid" as a literal branch name.
    head = find_git_head(repo)
    assert head is not None
    head.write_text("ref: refs/heads/.invalid\n")
    # subprocess symbolic-ref on this bogus HEAD fails/empty → "detached"
    assert read_branch(repo) == "detached"


def test_read_branch_returns_none_on_transient_os_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    # TOCTOU: HEAD exists at the is_file() check but becomes unreadable by
    # the time read_text() runs. Minor #4 fix: read_branch must swallow that
    # OSError and return None, not propagate it.
    head = find_git_head(repo)
    assert head is not None
    original_read_text = Path.read_text

    def flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == head:
            raise OSError("transient fs hiccup")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert read_branch(repo) is None


def test_find_git_head_returns_none_on_transient_os_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    # Same TOCTOU class, one level up: a transient error while walking up
    # from cwd (e.g. checking .git) must return None, not propagate.
    git_dir = repo / ".git"
    original_is_dir = Path.is_dir

    def flaky_is_dir(self: Path) -> bool:
        if self == git_dir:
            raise OSError("transient fs hiccup")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", flaky_is_dir)
    assert find_git_head(repo) is None


async def test_provider_poll_survives_transient_read_branch_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    # Force read_branch itself to raise once (simulating an error escaping
    # its internal guard) right as _poll picks up a real branch change, then
    # let it succeed on the next mtime-triggered read. The polling task must
    # survive the first failure and still detect the later, real change.
    real_read_branch = git_branch.read_branch
    calls = {"n": 0}

    def flaky_read_branch(cwd: Path) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient read_branch failure")
        return real_read_branch(cwd)

    p = GitBranchProvider(repo, poll_interval=0.02)
    monkeypatch.setattr(git_branch, "read_branch", flaky_read_branch)
    changed = asyncio.Event()
    await p.start(on_change=changed.set)
    try:
        _git(repo, "checkout", "-b", "feature")
        # Give _poll a chance to hit the injected raise and survive it.
        await asyncio.sleep(0.2)
        assert p._task is not None and not p._task.done()
        assert calls["n"] >= 1

        _git(repo, "checkout", "-b", "feature2")
        await asyncio.wait_for(changed.wait(), timeout=3.0)
        assert p.current_branch == "feature2"
    finally:
        await p.stop()
