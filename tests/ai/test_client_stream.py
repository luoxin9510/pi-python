from collections.abc import AsyncIterator

import litellm

from pipython.ai.client import ClientMessageEnd, LiteLLMClient
from pipython.ai.types import AssistantMessage, TextContent, ThinkingContent


class _Delta(dict):
    """Dict subclass so `.get`/`[]` behave like litellm's SafeAttributeModel."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


class _Choice:
    def __init__(self, delta: dict):
        self.delta = _Delta(delta)


class _Chunk:
    def __init__(self, delta: dict):
        self.choices = [_Choice(delta)]
        self.usage = None


async def _fake_stream() -> AsyncIterator[_Chunk]:
    yield _Chunk({"reasoning_content": "think1", "content": None})
    yield _Chunk({"content": "answer"})


async def _fake_acompletion(*args, **kwargs):
    return _fake_stream()


async def test_stream_captures_thinking_before_text(monkeypatch):
    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)

    client = LiteLLMClient()
    events = [
        event
        async for event in client.stream(model="gpt-4o", system=None, messages=[], tool_schemas=[])
    ]

    end = events[-1]
    assert isinstance(end, ClientMessageEnd)
    assert end.message == AssistantMessage(
        content=[ThinkingContent(thinking="think1"), TextContent(text="answer")]
    )
