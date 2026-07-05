"""Clipboard copy with platform tools + OSC 52 remote fallback (ported from pi's clipboard.ts).

Local tools: pbcopy (macOS), wl-copy (Wayland), xclip/xsel (X11). On a remote
session (SSH/mosh) or when no local tool works, falls back to the OSC 52 escape
sequence written to stdout, which the outer terminal forwards to the real
clipboard. Only raises if every path fails.
"""

import base64
import os
import shutil
import subprocess
import sys

_OSC52_MAX = 100_000  # cap payload: very large clipboards can hang some terminals over OSC 52


class ClipboardError(Exception):
    pass


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _is_remote() -> bool:
    return any(os.environ.get(v) for v in ("SSH_CONNECTION", "SSH_TTY", "MOSH_CONNECTION"))


def _osc52(text: str) -> str:
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(b64) > _OSC52_MAX:
        raise ClipboardError("Text too large for OSC 52 clipboard")
    sys.stdout.write(f"\x1b]52;c;{b64}\x07")
    sys.stdout.flush()
    return "osc52"


def _local_tools() -> list[tuple[str, list[str]]]:
    if sys.platform == "darwin":
        return [("pbcopy", ["pbcopy"])]
    if sys.platform.startswith("win"):
        return [("clip", ["clip"])]
    tools: list[tuple[str, list[str]]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        tools.append(("wl-copy", ["wl-copy"]))
    tools.append(("xclip", ["xclip", "-selection", "clipboard"]))
    tools.append(("xsel", ["xsel", "--clipboard", "--input"]))
    return tools


def copy_to_clipboard(text: str) -> str:
    if _is_remote():
        return _osc52(text)
    for name, cmd in _local_tools():
        if not _which(name):
            continue
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return name
        except (OSError, subprocess.SubprocessError):
            continue
    return _osc52(text)
