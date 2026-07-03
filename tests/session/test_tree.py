import pytest

from pipython.session.store import MessageEntry, entry_id
from pipython.session.tree import current_path, find_entry


def e(eid, parent):
    return MessageEntry(
        id=eid, parent_id=parent, timestamp="t", message={"role": "user", "content": eid}
    )


def test_path_follows_parent_chain():
    entries = [e("a1", None), e("b2", "a1"), e("c3", "b2"), e("d4", "a1")]  # d4 是休眠分支
    path = current_path(entries, "c3")
    assert [entry_id(x) for x in path] == ["a1", "b2", "c3"]


def test_branch_switch_via_other_leaf():
    entries = [e("a1", None), e("b2", "a1"), e("d4", "a1")]
    assert [entry_id(x) for x in current_path(entries, "d4")] == ["a1", "d4"]


def test_broken_chain_raises():
    with pytest.raises(ValueError):
        current_path([e("b2", "missing")], "b2")


def test_cycle_raises():
    entries = [e("a1", "b2"), e("b2", "a1")]  # 损坏 session：parentId 成环
    with pytest.raises(ValueError, match="cycle"):
        current_path(entries, "a1")


def test_find_entry_missing_raises():
    with pytest.raises(KeyError):
        find_entry([e("a1", None)], "zz")
