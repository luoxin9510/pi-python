from pipython.ai.client import merge_tool_call_deltas, to_litellm_messages
from pipython.ai.types import (
    AssistantMessage,
    TextContent,
    ToolCallContent,
    ToolResultMessage,
    UserMessage,
)


def test_roles_map_to_openai_style():
    msgs = [
        UserMessage(content="hi"),
        AssistantMessage(
            content=[
                TextContent(text="ok"),
                ToolCallContent(id="t1", name="ls", arguments={"path": "."}),
            ]
        ),
        ToolResultMessage(tool_call_id="t1", tool_name="ls", content="a.py", is_error=False),
    ]
    out = to_litellm_messages("sys", msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}
    a = out[2]
    assert a["role"] == "assistant" and a["content"] == "ok"
    assert a["tool_calls"][0]["function"]["name"] == "ls"
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "a.py"}


def test_merge_tool_call_deltas_by_index():
    chunks = [
        {"index": 0, "id": "t1", "function": {"name": "grep", "arguments": '{"pat'}},
        {"index": 0, "id": None, "function": {"name": None, "arguments": 'tern": "x"}'}},
        {"index": 1, "id": "t2", "function": {"name": "ls", "arguments": "{}"}},
    ]
    calls = merge_tool_call_deltas(chunks)
    assert calls[0] == ToolCallContent(id="t1", name="grep", arguments={"pattern": "x"})
    assert calls[1].name == "ls" and calls[1].arguments == {}


def test_merge_bad_json_becomes_empty_args_with_raw():
    chunks = [{"index": 0, "id": "t1", "function": {"name": "ls", "arguments": "{oops"}}]
    calls = merge_tool_call_deltas(chunks)
    assert calls[0].arguments == {"_raw": "{oops"}
