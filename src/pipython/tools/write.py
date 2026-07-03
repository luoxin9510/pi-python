from .base import ToolContext, tool


@tool
async def write(path: str, content: str, ctx: ToolContext | None = None) -> str:
    """Write content to a file, creating parent directories."""
    assert ctx is not None
    p = (ctx.cwd / path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} chars to {path}"


write_tool = write
