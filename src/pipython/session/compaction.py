"""Compaction fold semantics: rebuild context from a path, folding pre-compaction ancestors (spec §5.4)."""

from collections.abc import Sequence

from .store import CompactionEntry, Entry, entry_id


def build_context_entries(path: Sequence[Entry]) -> tuple[str | None, list[Entry]]:
    last_idx, comp = None, None
    for i, e in enumerate(path):
        if isinstance(e, CompactionEntry):
            last_idx, comp = i, e  # keep the object itself so pyright narrows comp's type
    if last_idx is None or comp is None:
        return None, list(path)
    kept: list[Entry] = []
    found_first_kept = False
    for e in path[:last_idx]:
        if entry_id(e) == comp.first_kept_entry_id:
            found_first_kept = True
        if found_first_kept:
            kept.append(e)
    kept.extend(
        path[last_idx + 1 :]
    )  # entries after compaction stay as-is (compaction itself excluded)
    return comp.summary, kept
