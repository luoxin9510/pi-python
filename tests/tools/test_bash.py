import time
from pathlib import Path

from pipython.tools.base import ToolContext
from pipython.tools.bash import bash_tool


def p(**kw):
    return bash_tool.params_model(**kw)


async def test_stdout_and_exit_ok(tmp_path: Path):
    r = await bash_tool.execute(p(command="echo hi"), ToolContext(cwd=tmp_path))
    assert not r.is_error and "hi" in r.content


async def test_nonzero_exit_is_error_not_raise(tmp_path: Path):
    r = await bash_tool.execute(p(command="ls /definitely-missing-dir"), ToolContext(cwd=tmp_path))
    assert r.is_error and "exit" in r.content.lower()


async def test_timeout_kills_process_tree(tmp_path: Path):
    start = time.monotonic()
    r = await bash_tool.execute(
        p(command="sleep 30 & sleep 30", timeout=0.5), ToolContext(cwd=tmp_path)
    )
    assert r.is_error and "timed out" in r.content.lower()
    assert time.monotonic() - start < 5


async def test_streaming_truncation_keeps_tail(tmp_path: Path):
    r = await bash_tool.execute(
        p(
            command="python3 -c \"print('x' * 100); print('\\n'.join(str(i) for i in range(20000)))\""
        ),
        ToolContext(cwd=tmp_path),
    )
    assert "19999" in r.content and "truncated" in r.content
    assert len(r.content) < 60_000


async def test_runs_in_cwd(tmp_path: Path):
    (tmp_path / "marker.txt").touch()
    r = await bash_tool.execute(p(command="ls"), ToolContext(cwd=tmp_path))
    assert "marker.txt" in r.content
