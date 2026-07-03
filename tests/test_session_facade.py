import json
from pathlib import Path
from typing import cast

from pipython import AgentSessionConfig, create_agent_session
from pipython.agent.events import Deny
from pipython.ai.types import AssistantMessage, TextContent, ToolCallContent
from pipython.testing import FakeClient


def toolcall_msg():
    return AssistantMessage(content=[ToolCallContent(id="t1", name="ls", arguments={"path": "."})])


def done_msg():
    return AssistantMessage(content=[TextContent(text="done")])


async def make(tmp_path, script, **kw):
    return await create_agent_session(AgentSessionConfig(
        model="fake", cwd=tmp_path, session_dir=tmp_path / "sessions",
        client=FakeClient(script=script), **kw))


async def drain(session, text="go"):
    return [e async for e in session.prompt(text)]


async def test_persists_messages_and_tool_results(tmp_path: Path):
    session = await make(tmp_path, [toolcall_msg(), done_msg()])
    await drain(session)
    lines = [json.loads(x) for x in session.store.path.read_text().splitlines()]
    types = [x["type"] for x in lines]
    assert types[0] == "session" and types.count("message") >= 3  # assistant×2 + toolResult
    assert all("parentId" in x for x in lines[1:])


async def test_on_registers_same_bus_deny_works(tmp_path: Path):
    session = await make(tmp_path, [toolcall_msg(), done_msg()])
    session.on("tool_call", lambda e: Deny(reason="blocked"))
    await drain(session)
    text = session.store.path.read_text()
    assert "Tool call denied: blocked" in text  # deny 结과도 落盤


async def test_set_model_appends_entry(tmp_path: Path):
    session = await make(tmp_path, [done_msg()])
    session.set_model("openai/gpt-5.2")
    lines = [json.loads(x) for x in session.store.path.read_text().splitlines()]
    mc = [x for x in lines if x["type"] == "model_change"]
    assert mc and mc[-1]["modelId"] == "gpt-5.2" and mc[-1]["provider"] == "openai"
    assert session.agent.model == "openai/gpt-5.2"


async def test_branch_moves_leaf_and_prunes_llm_context(tmp_path: Path):
    session = await make(tmp_path, [done_msg(), done_msg()])
    await drain(session, "first")
    lines = [json.loads(x) for x in session.store.path.read_text().splitlines()]
    first_msg_id = next(x["id"] for x in lines if x["type"] == "message")  # user "first"
    session.branch(first_msg_id)
    await drain(session, "second")
    # 磁盤上：新分叉挂在舊節點
    lines = [json.loads(x) for x in session.store.path.read_text().splitlines()]
    assert [x for x in lines if x.get("parentId") == first_msg_id]
    # LLM 侧：上下文真的被剪枝——第二次请求只含两条 user，没有第一轮的 assistant 回复
    last_call = cast(FakeClient, session.agent.client).calls[-1]
    assert [m.role for m in last_call] == ["user", "user"]
    assert last_call[0].content == "first" and last_call[1].content == "second"


async def test_compact_folds_llm_context(tmp_path: Path):
    session = await make(tmp_path, [done_msg(), done_msg()])
    await drain(session, "first")
    lines = [json.loads(x) for x in session.store.path.read_text().splitlines()]
    last_msg_id = [x["id"] for x in lines if x["type"] == "message"][-1]  # assistant "done"
    session.compact(summary="SUM", first_kept_entry_id=last_msg_id, tokens_before=42)
    await drain(session, "second")
    last_call = cast(FakeClient, session.agent.client).calls[-1]
    assert "SUM" in last_call[0].content  # summary 注入为首条 user 消息
    assert last_call[0].role == "user" and last_call[-1].content == "second"


async def test_default_tools_are_builtin_7(tmp_path: Path):
    session = await make(tmp_path, [done_msg()])
    assert sorted(session.agent.registry.names) == sorted(
        ["read", "bash", "edit", "write", "grep", "find", "ls"])
