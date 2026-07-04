"""Terminal capability detection (true-color, OSC 8 hyperlinks) subset.

Ports a slice of upstream pi's ``packages/tui/src/terminal-image.ts``:
``detectCapabilities`` -> ``detect_caps``, ``hyperlink``, ``isImageLine`` ->
``is_image_line``. Image *rendering* (Kitty/iTerm2 protocol encoding, PNG/
JPEG/GIF/WebP dimension sniffing, cell-size math) is out of scope for this
port per spec §3 — only the ``TermCaps(true_color, hyperlinks)`` subset of
upstream's ``TerminalCapabilities`` (which also carries an ``images`` field)
is produced here.

Deviations from upstream, both intentional per the task-2 brief's interface:

- ``detect_caps`` is a pure function over an explicit ``env`` dict (brief
  requirement), unlike upstream's ``detectCapabilities`` which reads
  ``process.env`` directly and (for tmux) shells out to
  ``tmux display-message`` via ``probeTmuxHyperlinks`` (terminal-image.ts:
  49-63) to check OSC-8 forwarding. That subprocess probe isn't reproducible
  as a pure function, so the tmux branch here conservatively returns
  ``hyperlinks=False`` rather than probing — matching upstream's own
  conservative fallback behaviour for terminals it can't positively confirm
  hyperlink support for.
- ``hyperlink(url, text, caps)`` reorders upstream's ``hyperlink(text, url)``
  (terminal-image.ts:478-480) to put ``url`` first, and adds the ``caps``
  gate: upstream always emits the OSC 8 sequence unconditionally; this port
  falls back to plain ``text`` when ``caps.hyperlinks`` is ``False``.
"""

from dataclasses import dataclass

__all__ = ["TermCaps", "detect_caps", "hyperlink", "is_image_line"]


@dataclass(frozen=True)
class TermCaps:
    true_color: bool
    hyperlinks: bool


def _lower_env(env: dict[str, str], key: str) -> str:
    """terminal-image.ts:66-69 lowercasing of env var lookups."""
    return env.get(key, "").lower()


def detect_caps(env: dict[str, str]) -> TermCaps:
    """Determine true-color/hyperlink support from an environment dict.

    Ported from upstream ``detectCapabilities`` (terminal-image.ts:65-125),
    same decision order, minus image-protocol detection (out of scope) and
    the tmux subprocess probe (see module docstring).
    """
    term_program = _lower_env(env, "TERM_PROGRAM")
    terminal_emulator = _lower_env(env, "TERMINAL_EMULATOR")
    term = _lower_env(env, "TERM")
    color_term = _lower_env(env, "COLORTERM")
    has_true_color_hint = color_term in ("truecolor", "24bit")  # line 70

    # lines 72-76: tmux — only forwards OSC 8 when it says it does; we can't
    # probe that purely from env, so default hyperlinks to False (see docstring).
    if "TMUX" in env or term.startswith("tmux"):
        return TermCaps(true_color=has_true_color_hint, hyperlinks=False)

    # lines 78-81: screen never forwards OSC 8 hyperlinks.
    if term.startswith("screen"):
        return TermCaps(true_color=has_true_color_hint, hyperlinks=False)

    # lines 83-85: Kitty.
    if "KITTY_WINDOW_ID" in env or term_program == "kitty":
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 87-89: Ghostty.
    if term_program == "ghostty" or "ghostty" in term or "GHOSTTY_RESOURCES_DIR" in env:
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 91-93: WezTerm.
    if "WEZTERM_PANE" in env or term_program == "wezterm":
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 95-98: Warp.
    if (
        term_program == "warpterminal"
        or "WARP_SESSION_ID" in env
        or "WARP_TERMINAL_SESSION_UUID" in env
    ):
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 100-102: iTerm2.
    if "ITERM_SESSION_ID" in env or term_program == "iterm.app":
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 104-106: Windows Terminal.
    if "WT_SESSION" in env:
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 108-110: VS Code.
    if term_program == "vscode":
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 112-114: Alacritty.
    if term_program == "alacritty":
        return TermCaps(true_color=True, hyperlinks=True)

    # lines 116-118: JetBrains (no hyperlinks).
    if terminal_emulator == "jetbrains-jediterm":
        return TermCaps(true_color=True, hyperlinks=False)

    # lines 120-124: conservative fallback for unrecognized terminals.
    return TermCaps(true_color=has_true_color_hint, hyperlinks=False)


def hyperlink(url: str, text: str, caps: TermCaps) -> str:
    """Wrap ``text`` in an OSC 8 hyperlink to ``url`` if supported.

    Returns plain ``text`` when ``caps.hyperlinks`` is ``False``. See module
    docstring for the param-order and capability-gating deviations from
    upstream ``hyperlink(text, url)`` (terminal-image.ts:478-480).
    """
    if not caps.hyperlinks:
        return text
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


_KITTY_PREFIX = "\x1b_G"
_ITERM2_PREFIX = "\x1b]1337;File="


def is_image_line(line: str) -> bool:
    """Detect a Kitty or iTerm2 inline-image escape sequence in ``line``.

    Ported verbatim from upstream ``isImageLine`` (terminal-image.ts:
    146-153): fast path checks the line start (single-row images), slow
    path checks anywhere in the line (multi-row images carry a cursor-up
    prefix before the image sequence).
    """
    if line.startswith(_KITTY_PREFIX) or line.startswith(_ITERM2_PREFIX):
        return True
    return _KITTY_PREFIX in line or _ITERM2_PREFIX in line
