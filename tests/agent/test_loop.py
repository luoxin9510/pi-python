from pathlib import Path
from typing import cast

from pipython.agent.agent import Agent
from pipython.agent.events import AgentEnd, Deny, ErrorEvent, ToolResultEvent
from pipython.ai.types import AssistantMessage, TextContent, ToolCallContent
from pipython.testing import FakeClient
from pipython.tools.base import tool
from pipython.tools.registry import ToolRegistry


@tool
async def echo(text: str) -> str:
    """Echo back."""
    return f"echo:{text}"


def toolcall_msg(name="echo", args=None, cid="t1"):
    return AssistantMessage(
        content=[ToolCallContent(id=cid, name=name, arguments=args or {"text": "hi"})]
    )


def done_msg(text="done"):
    return AssistantMessage(content=[TextContent(text=text)])


def make_agent(script, **kw):
    return Agent(
        client=FakeClient(script=script),
        model="fake",
        registry=ToolRegistry([echo]),
        system_prompt=None,
        cwd=Path.cwd(),
        **kw,
    )


async def run(agent, text="go", **kw):
    return [e async for e in agent.prompt(text, **kw)]


async def test_multiturn_tool_then_done():
    agent = make_agent([toolcall_msg(), done_msg()])
    events = await run(agent)
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results[0].result.content == "echo:hi"
    assert events[-1] == AgentEnd(reason="done")
    # 工具结果确实回灌进了第二轮请求
    second_call = cast(FakeClient, agent.client).calls[1]
    assert any(m.role == "toolResult" and m.content == "echo:hi" for m in second_call)


async def test_deny_feeds_error_result():
    agent = make_agent([toolcall_msg(), done_msg()])
    agent.bus.on("tool_call", lambda e: Deny(reason="not allowed"))
    events = await run(agent)
    r = next(e for e in events if isinstance(e, ToolResultEvent))
    assert r.result.is_error and "Tool call denied: not allowed" in r.result.content


async def test_unknown_tool_is_error_result():
    agent = make_agent([toolcall_msg(name="nope"), done_msg()])
    events = await run(agent)
    r = next(e for e in events if isinstance(e, ToolResultEvent))
    assert r.result.is_error and "nope" in r.result.content


async def test_invalid_params_is_error_result():
    agent = make_agent([toolcall_msg(args={"wrong": 1}), done_msg()])
    events = await run(agent)
    r = next(e for e in events if isinstance(e, ToolResultEvent))
    assert r.result.is_error


async def test_max_turns_stops():
    agent = make_agent([toolcall_msg(cid=f"t{i}") for i in range(5)], max_turns=2)
    events = await run(agent)
    assert events[-1] == AgentEnd(reason="max_turns")


async def test_set_model_midway():
    agent = make_agent([done_msg()])
    agent.set_model("other/model")
    await run(agent)
    assert agent.model == "other/model"


async def test_client_error_becomes_error_event():
    class BoomClient:
        async def stream(self, **kw):
            raise RuntimeError("boom")
            yield  # pragma: no cover  # 让它成为 async generator

    agent = Agent(
        client=BoomClient(),
        model="fake",
        registry=ToolRegistry([echo]),
        system_prompt=None,
        cwd=Path.cwd(),
    )
    events = await run(agent)
    assert any(isinstance(e, ErrorEvent) and "boom" in e.message for e in events)
    assert events[-1] == AgentEnd(reason="error")
