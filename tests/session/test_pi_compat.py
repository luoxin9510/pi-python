from pathlib import Path

from pipython.session.store import MessageEntry, SessionHeader, SessionStore

FIXTURE = Path(__file__).parent.parent / "fixtures" / "pi_v3_sample.jsonl"


def test_loads_real_pi_v3_shape():
    store = SessionStore.open(FIXTURE)
    assert isinstance(store.entries[0], SessionHeader) and store.entries[0].version == 3
    assert any(isinstance(e, MessageEntry) for e in store.entries)
    assert any(isinstance(e, dict) for e in store.entries)  # 未知类型透传


def test_reserialize_preserves_unknown_fields():
    store = SessionStore.open(FIXTURE)
    unknown = next(e for e in store.entries if isinstance(e, dict))
    assert unknown["type"] == "thinking_level_change" and unknown["thinkingLevel"] == "high"
