"""AgentSession: the public facade wiring Agent + SessionStore + tools together (spec §4.1-§4.3).

store 是唯一真源：每次 prompt() 先从 store.leaf_id 重建 agent.messages（summary 若存在则
注入为首条 user 消息），再把新 user 消息落盘，最后才委托 agent.prompt()（它会自己 append
新 UserMessage）。这个顺序避免了重复，也让 branch()/compact() 真正改变下一轮发给 LLM 的
上下文，而不只是重排磁盘上的 parentId。
"""

from pathlib import Path
from typing import Any, AsyncIterator, Callable

from .agent.agent import Agent
from .agent.events import Event, MessageEnd, ToolResultEvent
from .ai.client import LiteLLMClient
from .ai.types import AssistantMessage, Message, ToolResultMessage, UserMessage
from .config import AgentSessionConfig
from .session import ids
from .session.compaction import build_context_entries
from .session.store import CompactionEntry, MessageEntry, ModelChangeEntry, SessionStore
from .session.tree import current_path, find_entry
from .tools import BUILTIN_TOOLS
from .tools.registry import ToolRegistry

_ROLE_MODELS: dict[str, type] = {
    "user": UserMessage,
    "assistant": AssistantMessage,
    "toolResult": ToolResultMessage,
}


def _parse_message(d: dict) -> Message:
    return _ROLE_MODELS[d["role"]].model_validate(d)


DEFAULT_SESSION_DIR = Path.home() / ".pi-python" / "sessions"
DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent operating in {cwd}. Use the available tools to inspect, "
    "modify and verify code. Work autonomously until the task is complete, then summarize."
)


class AgentSession:
    def __init__(self, agent: Agent, store: SessionStore):
        self.agent = agent
        self.store = store
        agent.bus.on("message_end", self._persist_message)
        agent.bus.on("tool_result", self._persist_tool_result)

    # -- 持久化订阅者（spec §4.2：不侵入 loop）--
    def _persist_message(self, e: MessageEnd) -> None:
        self.store.append(
            MessageEntry(
                id=ids.new_entry_id(),
                parent_id=self.store.leaf_id,
                timestamp=ids.iso_now(),
                message=e.message.model_dump(by_alias=True),
            )
        )

    def _persist_tool_result(self, e: ToolResultEvent) -> None:
        msg = ToolResultMessage(
            tool_call_id=e.tool_call.id,
            tool_name=e.tool_call.name,
            content=e.result.content,
            is_error=e.result.is_error,
        )
        self.store.append(
            MessageEntry(
                id=ids.new_entry_id(),
                parent_id=self.store.leaf_id,
                timestamp=ids.iso_now(),
                message=msg.model_dump(by_alias=True),
            )
        )

    def _rebuild_agent_messages(self) -> None:
        """store 是唯一真源：从当前 leaf 重建 LLM 上下文（branch/compact 由此生效）。"""
        path = current_path(self.store.entries, self.store.leaf_id)
        summary, kept = build_context_entries(path)
        messages: list[Message] = []
        if summary is not None:
            messages.append(UserMessage(content=f"[Summary of earlier conversation]\n{summary}"))
        for e in kept:
            if isinstance(e, MessageEntry):
                messages.append(_parse_message(e.message))
        self.agent.messages = messages

    # -- 公开 API --
    def on(self, name: str, handler: Callable[[Any], Any]) -> None:
        self.agent.bus.on(name, handler)  # 同一份总线，无镜像（spec §4.3）

    async def prompt(self, text: str, *, max_turns: int | None = None) -> AsyncIterator[Event]:
        self._rebuild_agent_messages()  # 先重建，后追加——agent.prompt 会自己 append 新 user 消息
        self.store.append(
            MessageEntry(
                id=ids.new_entry_id(),
                parent_id=self.store.leaf_id,
                timestamp=ids.iso_now(),
                message=UserMessage(content=text).model_dump(by_alias=True),
            )
        )
        async for event in self.agent.prompt(text, max_turns=max_turns):
            yield event

    def set_model(self, model: str) -> None:
        self.agent.set_model(model)
        provider, _, model_id = model.partition("/")
        self.store.append(
            ModelChangeEntry(
                id=ids.new_entry_id(),
                parent_id=self.store.leaf_id,
                timestamp=ids.iso_now(),
                provider=provider,
                model_id=model_id or provider,
            )
        )

    def branch(self, entry_id: str) -> None:
        find_entry(self.store.entries, entry_id)  # 不存在则 KeyError
        self.store.leaf_id = entry_id

    def compact(self, *, summary: str, first_kept_entry_id: str, tokens_before: int) -> None:
        self.store.append(
            CompactionEntry(
                id=ids.new_entry_id(),
                parent_id=self.store.leaf_id,
                timestamp=ids.iso_now(),
                summary=summary,
                first_kept_entry_id=first_kept_entry_id,
                tokens_before=tokens_before,
            )
        )


async def create_agent_session(config: AgentSessionConfig) -> AgentSession:
    cwd = Path(config.cwd).resolve()
    registry = ToolRegistry(config.tools if config.tools is not None else list(BUILTIN_TOOLS))
    agent = Agent(
        client=config.client if config.client is not None else LiteLLMClient(),
        model=config.model,
        registry=registry,
        system_prompt=config.system_prompt or DEFAULT_SYSTEM_PROMPT.format(cwd=cwd),
        cwd=cwd,
        max_turns=config.max_turns,
    )
    session_dir = Path(config.session_dir) if config.session_dir else DEFAULT_SESSION_DIR
    store = SessionStore.create(session_dir=session_dir, cwd=cwd)
    return AgentSession(agent, store)
