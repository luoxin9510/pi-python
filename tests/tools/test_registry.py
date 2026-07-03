import pytest

from pipython.tools.base import tool
from pipython.tools.registry import ToolRegistry


@tool
async def alpha(x: int) -> str:
    """First."""
    return str(x)


@tool
async def beta(y: str) -> str:
    """Second."""
    return y


def test_lookup_and_names():
    reg = ToolRegistry([alpha, beta])
    assert reg.get("alpha") is alpha and reg.names == ["alpha", "beta"]
    with pytest.raises(KeyError):
        reg.get("nope")


def test_schemas_openai_format():
    s = ToolRegistry([alpha]).schemas()[0]
    assert s["type"] == "function" and s["function"]["name"] == "alpha"
    assert s["function"]["parameters"]["properties"]["x"]["type"] == "integer"


def test_same_name_overrides():
    @tool
    async def alpha(z: str) -> str:  # noqa: F811
        """Override."""
        return z

    reg = ToolRegistry([globals()["alpha"], alpha])
    assert reg.get("alpha").description == "Override."
