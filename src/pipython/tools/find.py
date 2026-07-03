import asyncio
import shutil
from pathlib import Path

from pydantic import BaseModel

from ..ai.types import CamelModel
from .base import ToolContext, ToolResult

_HAS_RG = shutil.which("rg") is not None


class FindParams(CamelModel):
    pattern: str
    path: str = "."
    limit: int = 1000


class FindTool:
    name = "find"
    description = "Find files by glob pattern, e.g. '**/*.py'."
    params_model: type[BaseModel] = FindParams

    async def execute(self, params: FindParams, ctx: ToolContext) -> ToolResult:
        try:
            cwd = ctx.cwd.resolve()
            root = (cwd / params.path).resolve()
            if _HAS_RG:
                proc = await asyncio.create_subprocess_exec(
                    "rg",
                    "--files",
                    "-g",
                    params.pattern,
                    str(root),
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                paths = out.decode(errors="replace").splitlines()
            else:
                paths = [str(f) for f in sorted(root.rglob(params.pattern)) if f.is_file()]
            rels = [str(Path(x).resolve().relative_to(cwd)) for x in paths]
            if not rels:
                return ToolResult(content="No files found.")
            return ToolResult(content="\n".join(rels[: params.limit]))
        except Exception as e:
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)


find_tool = FindTool()
