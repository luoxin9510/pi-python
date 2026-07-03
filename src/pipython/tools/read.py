from .base import ToolContext, ToolError, tool


@tool
async def read(path: str, offset: int = 0, limit: int = 2000, ctx: ToolContext | None = None) -> str:
    """Read a text file with line numbers. offset is 0-based line index."""
    assert ctx is not None  # FunctionTool 总会注入；断言供 pyright 收窄
    p = (ctx.cwd / path).resolve()
    if not p.is_file():
        raise ToolError(f"File not found: {path}")
    lines = p.read_text(errors="replace").splitlines()
    window = lines[offset : offset + limit]
    return "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(window))


read_tool = read
