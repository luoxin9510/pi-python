from pipython.ai.types import (
    AssistantMessage,
    TextContent,
    ToolCallContent,
    ToolResultMessage,
    Usage,
)


def test_tool_result_serializes_camelcase():
    m = ToolResultMessage(tool_call_id="tc1", tool_name="read", content="ok", is_error=False)
    d = m.model_dump(by_alias=True)
    assert d["role"] == "toolResult"
    assert d["toolCallId"] == "tc1" and d["isError"] is False


def test_assistant_roundtrip_with_toolcall():
    m = AssistantMessage(
        content=[
            TextContent(text="hi"),
            ToolCallContent(id="tc1", name="ls", arguments={"path": "."}),
        ],
        usage=Usage(input_tokens=1, output_tokens=2, cost=None),
    )
    d = m.model_dump(by_alias=True)
    m2 = AssistantMessage.model_validate(d)
    assert m2.content[1].name == "ls" and m2.usage.cost is None  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]


def test_extra_fields_survive_roundtrip():
    d = {"role": "user", "content": "x", "customField": 1}
    from pipython.ai.types import UserMessage

    m = UserMessage.model_validate(d)
    assert m.model_dump(by_alias=True)["customField"] == 1
