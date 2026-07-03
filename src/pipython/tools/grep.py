import asyncio
import re
import shutil

from pydantic import BaseModel

from ..ai.types import CamelModel
from .base import ToolContext, ToolResult

_HAS_RG = shutil.which("rg") is not None


class GrepParams(CamelModel):
    pattern: str
    path: str = "."
    glob: str | None = None
    ignore_case: bool = False
    literal: bool = False
    context: int = 0
    limit: int = 100


class GrepTool:
    name = "grep"
    description = "Search file contents (regex by default; set literal for exact strings)."
    params_model: type[BaseModel] = GrepParams

    async def execute(self, params: GrepParams, ctx: ToolContext) -> ToolResult:
        try:
            lines = await self._rg(params, ctx) if _HAS_RG else self._pure(params, ctx)
            if not lines:
                return ToolResult(content="No matches found.")
            capped = lines[: params.limit]
            note = (
                f"\n... ({len(lines)} matches, showing {len(capped)})"
                if len(lines) > len(capped)
                else ""
            )
            return ToolResult(content="\n".join(capped) + note)
        except Exception as e:
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)

    async def _rg(self, p: GrepParams, ctx: ToolContext) -> list[str]:
        args = ["rg", "-n", "--no-heading"]
        if p.ignore_case:
            args.append("-i")
        if p.literal:
            args.append("-F")
        if p.context:
            args.append(f"-C{p.context}")
        if p.glob:
            args += ["-g", p.glob]
        args += [p.pattern, p.path]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=ctx.cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode not in (0, 1):  # 1 = no matches
            raise RuntimeError(err.decode(errors="replace").strip())
        return out.decode(errors="replace").splitlines()

    def _pure(self, p: GrepParams, ctx: ToolContext) -> list[str]:
        flags = re.IGNORECASE if p.ignore_case else 0
        rx = re.compile(re.escape(p.pattern) if p.literal else p.pattern, flags)
        root = (ctx.cwd / p.path).resolve()
        files = (
            [root]
            if root.is_file()
            else sorted(f for f in root.rglob(p.glob or "*") if f.is_file())
        )
        results = []
        for f in files:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    results.append(f"{f.relative_to(ctx.cwd)}:{i}:{line}")
        return results


grep_tool = GrepTool()
