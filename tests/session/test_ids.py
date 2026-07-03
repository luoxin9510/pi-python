import re
from pipython.session import ids


def test_entry_id_is_8_hex():
    assert re.fullmatch(r"[0-9a-f]{8}", ids.new_entry_id())


def test_session_id_is_uuid7():
    sid = ids.new_session_id()
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", sid)


def test_session_ids_monotonic_in_same_ms():
    a = [ids.new_session_id() for _ in range(50)]
    assert a == sorted(a)


def test_iso_now_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ids.iso_now())
