from pathlib import Path

from pipython.tools.base import ToolContext
from pipython.tools.edit import edit_tool


def p(**kw):
    return edit_tool.params_model(**kw)


async def test_multi_edit_against_original(tmp_path: Path):
    (tmp_path / "f.py").write_text("aaa\nbbb\nccc\n")
    r = await edit_tool.execute(
        p(
            path="f.py",
            edits=[
                {"oldText": "aaa", "newText": "AAA"},
                {"oldText": "ccc", "newText": "CCC"},
            ],
        ),
        ToolContext(cwd=tmp_path),
    )
    assert not r.is_error and (tmp_path / "f.py").read_text() == "AAA\nbbb\nCCC\n"


async def test_non_unique_match_is_error_and_no_write(tmp_path: Path):
    (tmp_path / "f.py").write_text("dup dup\n")
    r = await edit_tool.execute(
        p(path="f.py", edits=[{"oldText": "dup", "newText": "x"}]), ToolContext(cwd=tmp_path)
    )
    assert r.is_error and "unique" in r.content.lower()
    assert (tmp_path / "f.py").read_text() == "dup dup\n"


async def test_overlapping_edits_rejected(tmp_path: Path):
    (tmp_path / "f.py").write_text("abcdef\n")
    r = await edit_tool.execute(
        p(
            path="f.py",
            edits=[{"oldText": "abcd", "newText": "x"}, {"oldText": "cdef", "newText": "y"}],
        ),
        ToolContext(cwd=tmp_path),
    )
    assert r.is_error and "overlap" in r.content.lower()


async def test_missing_text_is_error(tmp_path: Path):
    (tmp_path / "f.py").write_text("hello\n")
    r = await edit_tool.execute(
        p(path="f.py", edits=[{"oldText": "bye", "newText": "x"}]), ToolContext(cwd=tmp_path)
    )
    assert r.is_error and "not found" in r.content.lower()
