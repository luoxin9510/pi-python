from typing import Literal, Union

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


class TextContent(CamelModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingContent(CamelModel):
    type: Literal["thinking"] = "thinking"
    thinking: str


class ToolCallContent(CamelModel):
    type: Literal["toolCall"] = "toolCall"
    id: str
    name: str
    arguments: dict


class Usage(CamelModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None


class UserMessage(CamelModel):
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(CamelModel):
    role: Literal["assistant"] = "assistant"
    content: list[Union[TextContent, ThinkingContent, ToolCallContent]] = []
    usage: Usage | None = None


class ToolResultMessage(CamelModel):
    role: Literal["toolResult"] = "toolResult"
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False


Message = Union[UserMessage, AssistantMessage, ToolResultMessage]
