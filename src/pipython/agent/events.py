import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Union

from ..ai.types import AssistantMessage, ToolCallContent
from ..tools.base import ToolResult


@dataclass(frozen=True)
class AgentStart:
    pass


@dataclass(frozen=True)
class MessageStart:
    pass


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallEvent:
    tool_call: ToolCallContent


@dataclass(frozen=True)
class ToolResultEvent:
    tool_call: ToolCallContent
    result: ToolResult


@dataclass(frozen=True)
class MessageEnd:
    message: AssistantMessage


@dataclass(frozen=True)
class AgentEnd:
    reason: str


@dataclass(frozen=True)
class ErrorEvent:
    message: str


Event = Union[
    AgentStart,
    MessageStart,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
    MessageEnd,
    AgentEnd,
    ErrorEvent,
]

EVENT_NAMES: dict[type, str] = {
    AgentStart: "agent_start",
    MessageStart: "message_start",
    TextDelta: "text_delta",
    ToolCallEvent: "tool_call",
    ToolResultEvent: "tool_result",
    MessageEnd: "message_end",
    AgentEnd: "agent_end",
    ErrorEvent: "error",
}


@dataclass(frozen=True)
class Deny:
    reason: str


@dataclass
class EventBus:
    _handlers: dict[str, list[Callable[[Any], Any]]] = field(default_factory=dict)

    def on(self, name: str, handler: Callable[[Any], Any]) -> None:
        self._handlers.setdefault(name, []).append(handler)

    async def emit(self, event: Event) -> Deny | None:
        name = EVENT_NAMES[type(event)]
        gate = isinstance(event, ToolCallEvent)
        for handler in self._handlers.get(name, []):
            result = handler(event)
            if inspect.isawaitable(result):
                result = await result
            if gate and isinstance(result, Deny):
                return result
        return None
