import asyncio
import contextlib
import os
import signal
from collections import deque

from .base import ToolContext, ToolError, tool

MAX_OUTPUT_CHARS = 50_000
_CHUNK = 8192


@tool
async def bash(command: str, timeout: float = 120.0, ctx: ToolContext | None = None) -> str:
    """Run a shell command; returns combined stdout+stderr (tail-truncated)."""
    assert ctx is not None
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ctx.cwd,
        start_new_session=True,  # 独立进程组，超时可整树击杀
    )
    assert proc.stdout is not None
    stdout = proc.stdout
    tail: deque[str] = deque()
    tail_len = 0
    truncated = False

    async def pump() -> None:
        nonlocal tail_len, truncated
        while chunk := await stdout.read(_CHUNK):  # 边读边截，不整段攒内存
            text = chunk.decode(errors="replace")
            tail.append(text)
            tail_len += len(text)
            while tail_len > MAX_OUTPUT_CHARS and len(tail) > 1:
                truncated = True
                tail_len -= len(tail.popleft())

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
        code = await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.CancelledError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        raise
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(asyncio.TimeoutError):  # SIGKILL 后极端不可中断 IO 兜底
            await asyncio.wait_for(proc.wait(), timeout=5)
        partial = "".join(tail)
        if truncated:
            partial = "[... output truncated ...]\n" + partial
        msg = f"Command timed out after {timeout}s: {command}"
        if partial:  # 对齐上游 bash.ts：超时也返回挂起前的 partial output
            msg = f"{partial}\n{msg}"
        raise ToolError(msg) from None

    out = "".join(tail)
    if truncated:
        out = "[... output truncated ...]\n" + out
    if code != 0:
        raise ToolError(f"{out}\n(exit code {code})")
    return out or "(no output)"


bash_tool = bash
