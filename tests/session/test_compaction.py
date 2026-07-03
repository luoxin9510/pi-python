from pipython.session.compaction import build_context_entries
from pipython.session.store import CompactionEntry, MessageEntry, entry_id


def m(eid, parent):
    return MessageEntry(
        id=eid, parent_id=parent, timestamp="t", message={"role": "user", "content": eid}
    )


def test_folds_only_before_first_kept():
    path = [
        m("a1", None),
        m("b2", "a1"),
        m("c3", "b2"),
        CompactionEntry(
            id="k9",
            parent_id="c3",
            timestamp="t",
            summary="SUM",
            first_kept_entry_id="b2",
            tokens_before=100,
        ),
        m("d4", "k9"),
    ]
    summary, kept = build_context_entries(path)
    assert summary == "SUM"
    assert [entry_id(x) for x in kept] == ["b2", "c3", "d4"]  # a1 被折叠；b2..c3 保留；d4 照旧


def test_no_compaction_passthrough():
    path = [m("a1", None)]
    summary, kept = build_context_entries(path)
    assert summary is None and kept == path


def test_latest_compaction_wins():
    path = [
        m("a1", None),
        CompactionEntry(
            id="k1",
            parent_id="a1",
            timestamp="t",
            summary="OLD",
            first_kept_entry_id="a1",
            tokens_before=10,
        ),
        m("b2", "k1"),
        CompactionEntry(
            id="k2",
            parent_id="b2",
            timestamp="t",
            summary="NEW",
            first_kept_entry_id="b2",
            tokens_before=20,
        ),
    ]
    summary, kept = build_context_entries(path)
    assert summary == "NEW" and [entry_id(x) for x in kept] == ["b2"]
