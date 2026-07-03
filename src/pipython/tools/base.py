"""Tool abstraction: ToolResult/ToolContext data types, Tool protocol, @tool decorator."""

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, create_model


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class ToolContext:
    cwd: Path
    bus: Any = None  # agent.events.EventBus；Any 避免 tools↔agent 循环 import（spec §4.2）


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    params_model: type[BaseModel]

    def execute(self, params: Any, ctx: ToolContext) -> Awaitable[ToolResult]: ...


class ToolError(Exception):
    pass


@dataclass
class FunctionTool:
    name: str
    description: str
    params_model: type[BaseModel]
    _fn: Callable[..., Awaitable[str]] = field(repr=False)

    async def execute(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        kwargs = {k: getattr(params, k) for k in type(params).model_fields}
        if "ctx" in inspect.signature(self._fn).parameters:
            kwargs["ctx"] = ctx
        try:
            return ToolResult(content=str(await self._fn(**kwargs)))
        except ToolError as e:
            return ToolResult(content=str(e), is_error=True)
        except Exception as e:  # 任何意外异常也不外抛（spec §4.4）
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)


def tool(fn: Callable[..., Awaitable[str]]) -> FunctionTool:
    sig = inspect.signature(fn)
    fields: dict[str, Any] = {}
    for pname, p in sig.parameters.items():
        if pname == "ctx":
            continue
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else str
        default = p.default if p.default is not inspect.Parameter.empty else ...
        fields[pname] = (ann, default)
    model = create_model(f"{fn.__name__.title()}Params", **fields)
    desc = (inspect.getdoc(fn) or fn.__name__).split("\n\n")[0]
    return FunctionTool(name=fn.__name__, description=desc, params_model=model, _fn=fn)
