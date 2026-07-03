import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from .types import AssistantMessage, Message, TextContent, ToolCallContent, Usage


@dataclass(frozen=True)
class ClientTextDelta:
    text: str


@dataclass(frozen=True)
class ClientMessageEnd:
    message: AssistantMessage


ClientEvent = ClientTextDelta | ClientMessageEnd


class ModelClient(Protocol):
    def stream(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tool_schemas: list[dict],
    ) -> AsyncIterator[ClientEvent]: ...


def to_litellm_messages(system: str | None, messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            text = "".join(c.text for c in m.content if c.type == "text")
            calls = [c for c in m.content if c.type == "toolCall"]
            entry: dict = {"role": "assistant", "content": text}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in calls
                ]
            out.append(entry)
        else:  # toolResult
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
    return out


def merge_tool_call_deltas(chunks: list[dict]) -> list[ToolCallContent]:
    acc: dict[int, dict] = {}
    for c in chunks:
        slot = acc.setdefault(c["index"], {"id": "", "name": "", "args": ""})
        if c.get("id"):
            slot["id"] = c["id"]
        fn = c.get("function") or {}
        if fn.get("name"):
            slot["name"] += "" if slot["name"] else fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]
    calls = []
    for i in sorted(acc):
        s = acc[i]
        try:
            args = json.loads(s["args"]) if s["args"] else {}
        except json.JSONDecodeError:
            args = {"_raw": s["args"]}
        calls.append(ToolCallContent(id=s["id"], name=s["name"], arguments=args))
    return calls


class LiteLLMClient:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def stream(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[Message],
        tool_schemas: list[dict],
    ) -> AsyncIterator[ClientEvent]:
        import litellm

        from .models import resolve_model

        response: Any = None  # 让 pyright 确信循环后已绑定
        for attempt in range(self.max_retries + 1):
            try:
                response = await litellm.acompletion(
                    model=resolve_model(model),
                    messages=to_litellm_messages(system, messages),
                    tools=tool_schemas or None,
                    stream=True,
                    stream_options={"include_usage": True},
                    num_retries=0,  # 只保留本层重试（spec §4.4）
                )
                break
            except Exception:
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(2**attempt)
        assert response is not None

        texts: list[str] = []
        tc_chunks: list[dict] = []
        usage = None
        async for chunk in response:
            # 下面对 delta 混用属性/下标访问：依赖 litellm 的 SafeAttributeModel 兼容层
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.get("content"):
                texts.append(delta["content"])
                yield ClientTextDelta(text=delta["content"])
            if delta and delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    tc_chunks.append(
                        {
                            "index": tc["index"],
                            "id": tc.get("id"),
                            "function": tc.get("function") or {},
                        }
                    )
            if getattr(chunk, "usage", None):
                cost = None
                try:
                    cost = litellm.completion_cost(completion_response=chunk)
                except Exception:
                    pass  # 价格表缺失容错（spec §9）
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens,
                    output_tokens=chunk.usage.completion_tokens,
                    cost=cost,
                )
        content: list = []
        if texts:
            content.append(TextContent(text="".join(texts)))
        content.extend(merge_tool_call_deltas(tc_chunks))
        yield ClientMessageEnd(message=AssistantMessage(content=content, usage=usage))
