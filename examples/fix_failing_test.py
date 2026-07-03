"""Acceptance demo (spec §1): agent autonomously fixes a failing test.

Usage: ANTHROPIC_API_KEY=... uv run python examples/fix_failing_test.py
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from pipython import AgentEnd, AgentSessionConfig, TextDelta, ToolCallEvent, create_agent_session

SAMPLE = Path(__file__).parent / "sample_repo"


async def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="pi-python-demo-")) / "repo"
    shutil.copytree(SAMPLE, workdir)
    session = await create_agent_session(
        AgentSessionConfig(model="anthropic/claude-sonnet-5", cwd=workdir)
    )
    task = (
        "Run `python3 -m pytest test_calc.py` to see the failing test, find the bug, "
        "fix it, and re-run the tests until they pass."
    )
    async for event in session.prompt(task):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, ToolCallEvent):
            print(f"\n[tool] {event.tool_call.name} {event.tool_call.arguments}")
        elif isinstance(event, AgentEnd):
            print(f"\n[end] reason={event.reason}")
    print(f"\nsession file: {session.store.path}")


if __name__ == "__main__":
    asyncio.run(main())
