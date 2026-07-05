import base64
import subprocess

import pytest

from pipython.tui.components import clipboard
from pipython.tui.components.clipboard import ClipboardError, copy_to_clipboard


def _clear_remote(monkeypatch):
    for v in ("SSH_CONNECTION", "SSH_TTY", "MOSH_CONNECTION"):
        monkeypatch.delenv(v, raising=False)


def test_macos_uses_pbcopy(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["input"] = kw.get("input")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(clipboard, "_which", lambda name: name == "pbcopy")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    assert copy_to_clipboard("hello") == "pbcopy"
    assert calls["cmd"][0] == "pbcopy"
    assert calls["input"] == b"hello"


def test_linux_wayland_uses_wl_copy(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")  # _local_tools gates wl-copy on this
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "wl-copy")
    ran = {}
    monkeypatch.setattr(
        clipboard.subprocess,
        "run",
        lambda cmd, **kw: ran.setdefault("cmd", cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "wl-copy"
    assert ran["cmd"][0] == "wl-copy"


def test_linux_x11_uses_xclip_first(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)  # force X11 branch (no wl-copy)
    monkeypatch.setattr(clipboard, "_which", lambda name: name in ("xclip", "xsel"))
    monkeypatch.setattr(
        clipboard.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "xclip"


def test_linux_x11_falls_to_xsel_when_xclip_fails(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(clipboard, "_which", lambda name: name in ("xclip", "xsel"))

    def fake_run(cmd, **kw):
        if cmd[0] == "xclip":
            raise subprocess.CalledProcessError(1, cmd)  # xclip present but errors
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    assert copy_to_clipboard("x") == "xsel"


def test_remote_session_uses_osc52(monkeypatch, capsys):
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    # even if pbcopy exists, remote → OSC 52
    monkeypatch.setattr(clipboard, "_which", lambda name: True)
    assert copy_to_clipboard("hi") == "osc52"
    out = capsys.readouterr().out
    expected = "\x1b]52;c;" + base64.b64encode(b"hi").decode("ascii") + "\x07"
    assert out == expected


def test_no_tools_no_remote_falls_to_osc52(monkeypatch, capsys):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_which", lambda name: False)
    assert copy_to_clipboard("z") == "osc52"
    assert "\x1b]52;c;" in capsys.readouterr().out


def test_subprocess_failure_falls_to_osc52(monkeypatch, capsys):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "pbcopy")

    def boom(cmd, **kw):
        raise OSError("no")

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    assert copy_to_clipboard("z") == "osc52"
    assert "\x1b]52;c;" in capsys.readouterr().out


def test_subprocess_timeout_falls_to_osc52(monkeypatch, capsys):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "pbcopy")

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    assert copy_to_clipboard("z") == "osc52"
    assert "\x1b]52;c;" in capsys.readouterr().out


def test_all_paths_fail_raises_clipboard_error(monkeypatch):
    # No local tools + OSC 52 also unavailable (payload cap forced to 0) → raise.
    # Covers spec §3.3 "全部路径失败才 raise"; also makes the pytest/ClipboardError imports used.
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_which", lambda name: False)
    monkeypatch.setattr(
        clipboard, "_OSC52_MAX", 0
    )  # any non-empty payload exceeds → ClipboardError
    with pytest.raises(ClipboardError):
        copy_to_clipboard("x")
