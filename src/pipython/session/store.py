"""Session entry models and append-only JSONL persistence layer (pi v3 compat)."""

import json
from pathlib import Path
from typing import Literal, Union

from ..ai.types import CamelModel
from . import ids


class SessionHeader(CamelModel):
    type: Literal["session"] = "session"
    version: int = 3
    id: str
    timestamp: str
    cwd: str


class MessageEntry(CamelModel):
    type: Literal["message"] = "message"
    id: str
    parent_id: str | None
    timestamp: str
    message: dict


class ModelChangeEntry(CamelModel):
    type: Literal["model_change"] = "model_change"
    id: str
    parent_id: str | None
    timestamp: str
    provider: str
    model_id: str


class CompactionEntry(CamelModel):
    type: Literal["compaction"] = "compaction"
    id: str
    parent_id: str | None
    timestamp: str
    summary: str
    first_kept_entry_id: str
    tokens_before: int


Entry = Union[SessionHeader, MessageEntry, ModelChangeEntry, CompactionEntry, dict]

_KNOWN = {
    "session": SessionHeader,
    "message": MessageEntry,
    "model_change": ModelChangeEntry,
    "compaction": CompactionEntry,
}


def parse_entry(d: dict) -> Entry:
    """Dispatch by `type`; known types get strict validation, unknown pass through raw (spec §5.3)."""
    cls = _KNOWN.get(d.get("type", ""))
    return cls.model_validate(d) if cls else d


def entry_id(e: Entry) -> str | None:
    return e.get("id") if isinstance(e, dict) else e.id


def entry_parent_id(e: Entry) -> str | None:
    if isinstance(e, dict):
        return e.get("parentId")
    return getattr(e, "parent_id", None)


def entry_type(e: Entry) -> str | None:
    if isinstance(e, dict):
        return e.get("type")
    return getattr(e, "type", None)


def _dump(e: Entry) -> str:
    if isinstance(e, dict):
        return json.dumps(e, ensure_ascii=False)
    return e.model_dump_json(by_alias=True)


class SessionStore:
    """Append-only JSONL session store: one file per session, header first line."""

    def __init__(self, path: Path, entries: list[Entry]):
        self.path = path
        self.entries = entries
        non_header = [x for x in entries if entry_id(x) and not isinstance(x, SessionHeader)]
        self.leaf_id: str | None = entry_id(non_header[-1]) if non_header else None

    @classmethod
    def create(cls, *, session_dir: Path, cwd: Path) -> "SessionStore":
        # pi 真实格式（session-manager.ts:464）：cwd 的每个 "/" 换 "-"，再前缀 "-"、
        # 后缀 "--"；对 /a/b 产出 "--a-b--"（双前导横线，与 ~/.pi/agent/sessions 互通）
        dirname = "-" + str(cwd).replace("/", "-") + "--"
        session_id = ids.new_session_id()
        ts = ids.iso_now().replace(":", "-").replace(".", "-")
        path = session_dir / dirname / f"{ts}_{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = SessionHeader(id=session_id, timestamp=ids.iso_now(), cwd=str(cwd))
        store = cls(path, [header])
        with path.open("w", encoding="utf-8") as f:
            f.write(_dump(header) + "\n")
            f.flush()
        return store

    @classmethod
    def open(cls, path: Path) -> "SessionStore":
        lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        entries: list[Entry] = []
        for i, line in enumerate(lines):
            try:
                parsed_json = json.loads(line)
            except json.JSONDecodeError:
                if i == len(lines) - 1:
                    continue  # tolerate a corrupt/truncated last line only (killed-process case, spec §7.3)
                raise
            # ValidationError of a known type always propagates — that's a format
            # error, not the truncated-last-line case (spec §5.4). Not caught here.
            entries.append(parse_entry(parsed_json))
        return cls(path, entries)

    def append(self, e: Entry) -> None:
        self.entries.append(e)
        eid = entry_id(e)
        if eid is not None:
            self.leaf_id = eid
        with self.path.open("a", encoding="utf-8") as f:
            f.write(_dump(e) + "\n")
            f.flush()
