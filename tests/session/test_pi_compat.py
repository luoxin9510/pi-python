# Phase-1 scope: pi interop is *envelope-level* only — the outer JSONL entry
# shape (type/id/parentId/timestamp + known envelope fields) round-trips
# byte-for-byte, but the `message` body inside a MessageEntry is kept as a
# raw, unparsed dict (real pi ships array-content, Usage.input/output, nested
# cost objects, etc.). Body-typing + resume live in phase 2 (spec §9).

import json
from pathlib import Path

from pipython.session.store import MessageEntry, SessionHeader, SessionStore, _dump

FIXTURE = Path(__file__).parent.parent / "fixtures" / "pi_v3_sample.jsonl"


def test_loads_real_pi_v3_shape():
    store = SessionStore.open(FIXTURE)
    assert isinstance(store.entries[0], SessionHeader) and store.entries[0].version == 3
    assert any(isinstance(e, MessageEntry) for e in store.entries)
    unknown = next(e for e in store.entries if isinstance(e, dict))
    assert unknown["type"] == "thinking_level_change" and unknown["thinkingLevel"] == "high"

    messages = [e for e in store.entries if isinstance(e, MessageEntry)]
    assert len(messages) == 2

    user_msg = next(m for m in messages if m.message["role"] == "user")
    assert user_msg.message["content"] == [{"type": "text", "text": "hello"}]

    assistant_msg = next(m for m in messages if m.message["role"] == "assistant")
    assert assistant_msg.message["content"] == [{"type": "text", "text": "hi"}]
    assert assistant_msg.message["usage"] == {
        "input": 10,
        "output": 5,
        "cacheRead": 0,
        "cacheWrite": 0,
        "cost": {
            "input": 0.0001,
            "output": 0.0002,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": 0.0003,
        },
    }
    assert assistant_msg.message["stopReason"] == "stop"


def test_dump_roundtrip_preserves_entries():
    original_lines = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    store = SessionStore.open(FIXTURE)
    assert len(store.entries) == len(original_lines)
    for entry, original in zip(store.entries, original_lines, strict=True):
        assert json.loads(_dump(entry)) == original
