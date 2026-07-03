from pipython.agent.events import Deny, EventBus, TextDelta, ToolCallEvent
from pipython.ai.types import ToolCallContent


def tc():
    return ToolCallEvent(tool_call=ToolCallContent(id="1", name="bash", arguments={}))


async def test_handlers_called_in_order():
    bus, seen = EventBus(), []
    bus.on("text_delta", lambda e: seen.append("a"))
    bus.on("text_delta", lambda e: seen.append("b"))
    await bus.emit(TextDelta(text="x"))
    assert seen == ["a", "b"]


async def test_first_deny_short_circuits():
    bus, seen = EventBus(), []
    bus.on("tool_call", lambda e: Deny(reason="no"))
    bus.on("tool_call", lambda e: seen.append("late"))
    result = await bus.emit(tc())
    assert result == Deny(reason="no") and seen == []


async def test_async_handler_and_none_passes():
    bus = EventBus()

    async def h(e):
        return None

    bus.on("tool_call", h)
    assert await bus.emit(tc()) is None


async def test_non_toolcall_return_values_ignored():
    bus = EventBus()
    bus.on("text_delta", lambda e: Deny(reason="ignored"))
    assert await bus.emit(TextDelta(text="x")) is None
