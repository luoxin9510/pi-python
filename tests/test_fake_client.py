import pytest

from pipython.ai.client import ClientMessageEnd, ClientTextDelta
from pipython.ai.types import AssistantMessage, TextContent
from pipython.testing import FakeClient


async def collect(it):
    return [e async for e in it]


async def test_fake_client_replays_script():
    msg = AssistantMessage(content=[TextContent(text="hello")])
    fake = FakeClient(script=[msg])
    events = await collect(fake.stream(model="m", system=None, messages=[], tool_schemas=[]))
    assert events[0] == ClientTextDelta(text="hello")
    assert events[-1] == ClientMessageEnd(message=msg)


async def test_fake_client_exhausted_raises():
    fake = FakeClient(script=[])
    with pytest.raises(AssertionError):
        await collect(fake.stream(model="m", system=None, messages=[], tool_schemas=[]))
