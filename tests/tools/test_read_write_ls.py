from pathlib import Path

from pipython.tools.base import ToolContext
from pipython.tools.ls import ls_tool
from pipython.tools.read import read_tool
from pipython.tools.write import write_tool


async def test_write_then_read_with_line_numbers(tmp_path: Path):
    ctx = ToolContext(cwd=tmp_path)
    p = write_tool.params_model(path="a/b.txt", content="x\ny\n")
    assert not (await write_tool.execute(p, ctx)).is_error  # 自动建父目录
    r = await read_tool.execute(read_tool.params_model(path="a/b.txt"), ctx)
    assert r.content.splitlines()[0] == "1\tx" and r.content.splitlines()[1] == "2\ty"


async def test_read_offset_limit(tmp_path: Path):
    ctx = ToolContext(cwd=tmp_path)
    (tmp_path / "f.txt").write_text("".join(f"L{i}\n" for i in range(10)))
    r = await read_tool.execute(read_tool.params_model(path="f.txt", offset=3, limit=2), ctx)
    assert r.content.splitlines() == ["4\tL3", "5\tL4"]


async def test_read_missing_is_error_not_raise(tmp_path: Path):
    r = await read_tool.execute(read_tool.params_model(path="nope.txt"), ToolContext(cwd=tmp_path))
    assert r.is_error and "nope.txt" in r.content


async def test_read_large_file_truncation_notice(tmp_path: Path):
    (tmp_path / "big.txt").write_text("".join(f"L{i}\n" for i in range(2500)))
    r = await read_tool.execute(read_tool.params_model(path="big.txt"), ToolContext(cwd=tmp_path))
    lines = r.content.splitlines()
    assert lines[0] == "1\tL0" and lines[1999] == "2000\tL1999"
    assert len(lines) == 2001  # 2000 内容行 + 1 行截断提示
    assert "more lines" in lines[-1] and "offset=2000" in lines[-1]


async def test_ls_lists_entries(tmp_path: Path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f.txt").touch()
    r = await ls_tool.execute(ls_tool.params_model(path="."), ToolContext(cwd=tmp_path))
    assert "d/" in r.content and "f.txt" in r.content
