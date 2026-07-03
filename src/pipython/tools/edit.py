from ..ai.types import CamelModel
from .base import ToolContext, ToolError, ToolResult


class Edit(CamelModel):
    old_text: str
    new_text: str


class EditParams(CamelModel):
    path: str
    edits: list[Edit]


class EditTool:
    name = "edit"
    description = (
        "Apply one or more targeted text replacements to a file. Each edit is matched "
        "against the original file, not incrementally; edits must not overlap; each "
        "oldText must appear exactly once."
    )
    params_model = EditParams

    async def execute(self, params: EditParams, ctx: ToolContext) -> ToolResult:
        try:
            p = (ctx.cwd / params.path).resolve()
            if not p.is_file():
                raise ToolError(f"File not found: {params.path}")
            original = p.read_text()
            spans: list[tuple[int, int, str]] = []
            for e in params.edits:
                n = original.count(e.old_text)
                if n == 0:
                    raise ToolError(f"oldText not found: {e.old_text!r}")
                if n > 1:
                    raise ToolError(f"oldText is not unique ({n} matches): {e.old_text!r}")
                i = original.index(e.old_text)
                spans.append((i, i + len(e.old_text), e.new_text))
            spans.sort()
            for (_, end_prev, _), (start, _, _) in zip(spans, spans[1:]):
                if start < end_prev:
                    raise ToolError("edits overlap; merge them into one edit")
            out, cursor = [], 0
            for start, end, new in spans:
                out += [original[cursor:start], new]
                cursor = end
            out.append(original[cursor:])
            p.write_text("".join(out))
            return ToolResult(content=f"Applied {len(spans)} edit(s) to {params.path}")
        except ToolError as e:
            return ToolResult(content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)


edit_tool = EditTool()
