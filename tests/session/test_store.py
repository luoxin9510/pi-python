import json
from pathlib import Path

from pipython.session.store import (
    CompactionEntry,
    MessageEntry,
    SessionStore,
    parse_entry,
)


def test_dir_and_filename_convention(tmp_path: Path):
    store = SessionStore.create(session_dir=tmp_path, cwd=Path("/a/b"))
    assert store.path.parent.name == "-a-b--"
    assert store.path.suffix == ".jsonl" and "_" in store.path.stem


def test_header_first_line_camelcase(tmp_path: Path):
    store = SessionStore.create(session_dir=tmp_path, cwd=Path("/a/b"))
    first = json.loads(store.path.read_text().splitlines()[0])
    assert first["type"] == "session" and first["version"] == 3 and first["cwd"] == "/a/b"


def test_append_load_roundtrip_and_leaf(tmp_path: Path):
    store = SessionStore.create(session_dir=tmp_path, cwd=Path("/a/b"))
    e1 = MessageEntry(
        id="aaaa0001", parent_id=None, timestamp="t", message={"role": "user", "content": "hi"}
    )
    store.append(e1)
    loaded = SessionStore.open(store.path)
    assert loaded.leaf_id == "aaaa0001"
    m = loaded.entries[1]
    assert isinstance(m, MessageEntry) and m.message["content"] == "hi"


def test_unknown_entry_type_passthrough(tmp_path: Path):
    d = {"type": "thinking_level_change", "id": "x", "parentId": None, "thinkingLevel": "high"}
    assert parse_entry(d) == d  # 原样 dict


def test_corrupt_last_line_tolerated(tmp_path: Path):
    store = SessionStore.create(session_dir=tmp_path, cwd=Path("/a/b"))
    store.append(
        MessageEntry(
            id="aaaa0001", parent_id=None, timestamp="t", message={"role": "user", "content": "hi"}
        )
    )
    with store.path.open("a") as f:
        f.write('{"type":"message","id":"brok')  # 模拟进程被杀
    loaded = SessionStore.open(store.path)
    assert loaded.leaf_id == "aaaa0001" and len(loaded.entries) == 2


def test_compaction_requires_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CompactionEntry.model_validate(
            {"type": "compaction", "id": "x", "parentId": None, "timestamp": "t", "summary": "s"}
        )  # 缺 firstKeptEntryId/tokensBefore


def test_invalid_known_entry_midfile_raises(tmp_path: Path):
    import pytest
    from pydantic import ValidationError

    store = SessionStore.create(session_dir=tmp_path, cwd=Path("/a/b"))
    with store.path.open("a") as f:
        f.write('{"type":"compaction","id":"x","parentId":null,"timestamp":"t","summary":"s"}\n')
        f.write('{"type":"message","id":"y","parentId":null,"timestamp":"t","message":{}}\n')
    with pytest.raises(ValidationError):  # 缺字段的已知类型不许被静默吞掉
        SessionStore.open(store.path)
