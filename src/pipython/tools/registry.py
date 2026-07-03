"""ToolRegistry: name-based lookup and OpenAI function-schema export for a set of tools."""

from .base import Tool


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self._tools[t.name] = t  # 后注册覆盖先注册

    def get(self, name: str) -> Tool:
        return self._tools[name]

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.params_model.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]
