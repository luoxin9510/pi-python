"""Agent: drives the request/tool-execution loop over a ModelClient (spec §4.2-§4.4)."""

from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import ValidationError

from ..ai.client import ClientMessageEnd, ClientTextDelta, ModelClient
from ..ai.types import Message, ToolCallContent, ToolResultMessage, UserMessage
from ..tools.base import ToolContext, ToolResult
from ..tools.registry import ToolRegistry
from .events import (
    AgentEnd,
    AgentStart,
    ErrorEvent,
    Event,
    EventBus,
    MessageEnd,
    MessageStart,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)


class Agent:
    """Owns the message history and drives one prompt() at a time over a ModelClient.

    Everything (client, registry, event bus) is injected — the Agent knows nothing
    about session persistence; that is layered on top (spec §4.2, design principle 1).
    """

    def __init__(
        self,
        *,
        client: ModelClient,
        model: str,
        registry: ToolRegistry,
        system_prompt: str | None,
        cwd: Path,
        max_turns: int = 50,
    ):
        self.client = client
        self.model = model
        self.registry = registry
        self.system_prompt = system_prompt
        self.cwd = Path(cwd)
        self.max_turns = max_turns
        self.bus = EventBus()
        self.messages: list[Message] = []

    def set_model(self, model: str) -> None:
        self.model = model

    async def _dispatch(self, event: Event) -> None:
        await self.bus.emit(event)

    async def prompt(self, text: str, *, max_turns: int | None = None) -> AsyncIterator[Event]:
        """Append a UserMessage and drive the loop until AgentEnd.

        Every event is awaited through bus.emit() *before* being yielded, so
        subscribers observe an event before the caller does (spec §4.3). Only
        tool_call handlers may return Deny to veto execution (spec §4.2).
        """
        limit = max_turns if max_turns is not None else self.max_turns
        self.messages.append(UserMessage(content=text))
        await self._dispatch(AgentStart())
        yield AgentStart()

        turns = 0
        while True:
            turns += 1
            if turns > limit:
                end = AgentEnd(reason="max_turns")
                await self._dispatch(end)
                yield end
                return

            await self._dispatch(MessageStart())
            yield MessageStart()

            assistant = None
            try:
                async for ev in self.client.stream(
                    model=self.model,
                    system=self.system_prompt,
                    messages=self.messages,
                    tool_schemas=self.registry.schemas(),
                ):
                    if isinstance(ev, ClientTextDelta):
                        e = TextDelta(text=ev.text)
                        await self._dispatch(e)
                        yield e
                    elif isinstance(ev, ClientMessageEnd):
                        assistant = ev.message
            except Exception as exc:  # retries exhausted — never a naked exception (spec §4.3)
                err = ErrorEvent(message=f"{type(exc).__name__}: {exc}")
                await self._dispatch(err)
                yield err
                end = AgentEnd(reason="error")
                await self._dispatch(end)
                yield end
                return

            assert assistant is not None, "ModelClient.stream() must yield a ClientMessageEnd"
            self.messages.append(assistant)
            end_msg = MessageEnd(message=assistant)
            await self._dispatch(end_msg)
            yield end_msg

            calls = [c for c in assistant.content if isinstance(c, ToolCallContent)]
            if not calls:
                end = AgentEnd(reason="done")
                await self._dispatch(end)
                yield end
                return

            for call in calls:
                call_event = ToolCallEvent(tool_call=call)
                deny = await self.bus.emit(call_event)
                yield call_event
                if deny is not None:
                    result = ToolResult(content=f"Tool call denied: {deny.reason}", is_error=True)
                else:
                    result = await self._execute(call)
                r_event = ToolResultEvent(tool_call=call, result=result)
                await self._dispatch(r_event)
                yield r_event
                self.messages.append(
                    ToolResultMessage(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        content=result.content,
                        is_error=result.is_error,
                    )
                )

    async def _execute(self, call: ToolCallContent) -> ToolResult:
        try:
            t = self.registry.get(call.name)
        except KeyError:
            return ToolResult(content=f"Unknown tool: {call.name}", is_error=True)
        try:
            params = t.params_model.model_validate(call.arguments)
        except ValidationError as e:
            return ToolResult(content=f"Invalid arguments: {e}", is_error=True)
        return await t.execute(params, ToolContext(cwd=self.cwd, bus=self.bus))
