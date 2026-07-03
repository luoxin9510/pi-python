"""Public testing helpers — the only allowed stand-in for the LLM API."""

from collections.abc import AsyncIterator

from .ai.client import ClientEvent, ClientMessageEnd, ClientTextDelta
from .ai.types import AssistantMessage, Message


class FakeClient:
    def __init__(self, script: list[AssistantMessage]):
        self._script = list(script)
        self.calls: list[list[Message]] = []  # 供断言检查每轮实际收到的消息

    async def stream(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tool_schemas: list[dict],
    ) -> AsyncIterator[ClientEvent]:
        assert self._script, "FakeClient script exhausted"
        self.calls.append(list(messages))
        msg = self._script.pop(0)
        for c in msg.content:
            if c.type == "text":
                yield ClientTextDelta(text=c.text)
        yield ClientMessageEnd(message=msg)
