import json

from pipython.testing import FakeClient
from pipython.tui.app import load_fake_client, make_client
from pipython.tui.keys import build_key_bindings


def test_load_fake_client_roundtrip(tmp_path):
    script = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    f = tmp_path / "s.json"
    f.write_text(json.dumps(script))
    client = load_fake_client(str(f))
    assert isinstance(client, FakeClient) and len(client._script) == 1


def test_make_client_env_switch(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text("[]")
    monkeypatch.setenv("PI_PYTHON_FAKE_SCRIPT", str(f))
    assert isinstance(make_client("any/model"), FakeClient)
    monkeypatch.delenv("PI_PYTHON_FAKE_SCRIPT")
    assert make_client("any/model") is None


def test_key_bindings_build():
    kb = build_key_bindings()
    assert kb.bindings  # 至少注册了换行绑定
