"""Tree operations over session entries: leaf-to-root path rebuild via parentId (spec §5.4)."""

from collections.abc import Sequence

from .store import Entry, SessionHeader, entry_id, entry_parent_id


def find_entry(entries: Sequence[Entry], eid: str) -> Entry:
    for e in entries:
        if entry_id(e) == eid:
            return e
    raise KeyError(eid)


def current_path(entries: Sequence[Entry], leaf_id: str | None) -> list[Entry]:
    if leaf_id is None:
        return []
    by_id = {entry_id(e): e for e in entries if entry_id(e) and not isinstance(e, SessionHeader)}
    path: list[Entry] = []
    cursor: str | None = leaf_id
    seen: set[str] = set()
    while cursor is not None:
        if cursor in seen:
            raise ValueError(f"parentId cycle detected at {cursor!r}")
        seen.add(cursor)
        if cursor not in by_id:
            raise ValueError(f"broken parent chain at {cursor!r}")
        node = by_id[cursor]
        path.append(node)
        cursor = entry_parent_id(node)
    path.reverse()
    return path
