from .base import ToolContext, ToolError, tool


@tool
async def ls(path: str = ".", ctx: ToolContext | None = None) -> str:
    """List directory entries; directories get a trailing slash."""
    assert ctx is not None
    p = (ctx.cwd / path).resolve()
    if not p.is_dir():
        raise ToolError(f"Not a directory: {path}")
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries)


ls_tool = ls
