import time
from pathlib import Path

import pytest

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


async def test_timeout_includes_partial_output(tmp_path: Path):
    r = await bash_tool.execute(
        p(command="echo before-hang && sleep 30", timeout=0.5), ToolContext(cwd=tmp_path)
    )
    assert r.is_error and "timed out" in r.content.lower()
    assert "before-hang" in r.content


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


async def test_cancel_kills_process_tree(tmp_path: Path):
    import asyncio
    import subprocess

    marker = f"pi-python-cancel-{tmp_path.name}"
    task = asyncio.create_task(
        bash_tool.execute(
            p(command=f"sleep 30; echo {marker} & sleep 30; echo {marker}"),
            ToolContext(cwd=tmp_path),
        )
    )
    await asyncio.sleep(0.3)  # 让子进程真正跑起来
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)  # 给 SIGKILL 一点收尸时间
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    assert out.stdout.strip() == ""  # 进程组已死，无孤儿
