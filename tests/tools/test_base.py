from pathlib import Path

from pipython.tools.base import Tool, ToolContext, ToolResult, tool


@tool
async def deploy(service: str, env: str = "staging") -> str:
    """Deploy a service."""
    return f"{service}->{env}"


def test_decorator_builds_metadata():
    assert deploy.name == "deploy"
    assert deploy.description == "Deploy a service."
    schema = deploy.params_model.model_json_schema()
    assert schema["properties"]["service"]["type"] == "string"
    assert "service" in schema["required"] and "env" not in schema.get("required", [])


async def test_execute_returns_toolresult(tmp_path: Path):
    params = deploy.params_model(service="api")
    result = await deploy.execute(params, ToolContext(cwd=tmp_path))
    assert result == ToolResult(content="api->staging")


def test_functiontool_satisfies_protocol():
    assert isinstance(deploy, Tool)
