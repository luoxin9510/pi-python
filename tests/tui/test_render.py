from rich.console import Console

from pipython import (
    AgentEnd,
    AssistantMessage,
    ErrorEvent,
    MessageEnd,
    TextContent,
    TextDelta,
    ToolCallContent,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)
from pipython.tui.render import TurnRenderer, extract_text, summarize_message_dict


def tc(name="bash", args=None):
    return ToolCallContent(id="t1", name=name, arguments=args or {"command": "ls"})


def make():
    # force_terminal=False：显式钉死降级分支，不依赖 pytest 的 stdout 捕获方式
    console = Console(record=True, width=80, force_terminal=False)
    return console, TurnRenderer(console)


def out(console):
    return console.export_text()


async def test_markdown_rendered_on_message_end():
    console, r = make()
    msg = AssistantMessage(content=[TextContent(text="# Title\n\n`code`")])
    await r.handle(TextDelta(text="# Ti"))
    await r.handle(TextDelta(text="tle"))
    await r.handle(MessageEnd(message=msg))
    r.finish()
    text = out(console)
    assert "Title" in text and "# Ti" not in text  # 重排后不是原始增量


async def test_tool_call_line_truncated():
    console, r = make()
    await r.handle(ToolCallEvent(tool_call=tc(args={"command": "x" * 500})))
    r.finish()
    line = out(console)
    assert "[tool] bash" in line and len(line.splitlines()[0]) < 200


async def test_tool_result_only_errors_printed():
    console, r = make()
    ok = ToolResultEvent(tool_call=tc(), result=ToolResult(content="fine"))
    bad = ToolResultEvent(tool_call=tc(), result=ToolResult(content="boom", is_error=True))
    await r.handle(ok)
    await r.handle(bad)
    r.finish()
    text = out(console)
    assert "fine" not in text and "boom" in text


async def test_agent_end_non_done_notice():
    console, r = make()
    await r.handle(AgentEnd(reason="max_turns"))
    r.finish()
    assert "max_turns" in out(console)


async def test_error_event_rendered_in_red():
    # SDK 把耗尽重试的模型失败转成 ErrorEvent + AgentEnd("error")（agent.py）；
    # handle() 此前没有 ErrorEvent 分支，坏 API key 等失败会悄无声息、零诊断。
    console, r = make()
    await r.handle(ErrorEvent(message="AuthenticationError: invalid API key"))
    r.finish()
    assert "AuthenticationError: invalid API key" in out(console)


def test_extract_text_joins_blocks():
    msg = AssistantMessage(content=[TextContent(text="a"), tc(), TextContent(text="b")])
    assert extract_text(msg) == "ab"


def test_summarize_message_dict_rules():
    assert summarize_message_dict({"role": "user", "content": "x" * 80}).endswith("…")
    assert (
        summarize_message_dict(
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}
        )
        == "hello"
    )
    assert (
        summarize_message_dict(
            {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "1", "name": "edit", "arguments": {}}],
            }
        )
        == "[tool: edit]"
    )
