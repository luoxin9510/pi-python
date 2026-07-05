"""Keyboard input handling — Python port of upstream pi's
``packages/tui/src/keys.ts`` (subset per phase-3 spec §5).

Ports the *parsing* half of upstream keys.ts: legacy terminal sequences +
Kitty CSI-u (base/modifiers/flag-4 alternate keys). Native-modifiers
(``native-modifiers.ts``, a darwin-only precompiled ``.node`` addon polling
physical modifier keys) is explicitly **not** ported — see phase3 spec §5 and
``docs/superpowers/specs/2026-07-04-phase3-pi-tui-port-design.md``.

Interface (binding, per task-4 brief):

- ``KeyEvent(name, ctrl, alt, shift, text)`` frozen dataclass.
- ``parse_key(frame: str, kitty: bool) -> KeyEvent | None`` — one frame, one
  key; paste frames never reach this function (caller's job, see
  ``stdin_buffer.py`` docstring).
- ``key_id(event: KeyEvent) -> str`` — canonical ``"ctrl+shift+enter"``-style
  name for keybinding table lookups.

Declared deviations from the literal brief interface / upstream:

1. **Added ``super: bool = False`` field** (not in the brief's literal
   ``KeyEvent(name, ctrl, alt, shift, text)`` list). Upstream's modifier set
   is exactly ``{shift, alt, ctrl, super}`` (keys.ts:292-297) and the ported
   test suite (translated from keys.test.ts) requires super-modifier
   round-tripping (``"super+k"``, ``"ctrl+super+k"``,
   ``"shift+ctrl+super+k"`` — keys.test.ts:91-100). Omitting it would make
   those upstream-derived cases unrepresentable, so it is added as a trailing
   field to keep the brief's first-five positional order intact.
2. **``KeyEvent.text`` synthesizes upstream's separate ``decodeKittyPrintable``
   / ``decodePrintableKey`` exports** (keys.ts:1349-1400), which upstream
   exposes as standalone functions for a caller to invoke *in addition to*
   ``parseKey`` when deciding whether to insert literal text. This port folds
   that decoding into the same ``parse_key`` call, populating ``.text``
   whenever the frame decodes to an insertable character (no ctrl/alt held)
   and leaving it ``None`` otherwise (arrows, function keys, ctrl/alt combos,
   named keys whose codepoint is a control code).
3. **Unnamed-but-printable fallback** — upstream's ``parseKey`` returns
   ``undefined`` for any CSI-u / modifyOtherKeys codepoint outside its fixed
   ``KeyId`` taxonomy (e.g. a Shift+Ä frame, codepoint 196), even though the
   sibling ``decodePrintableKey`` *would* decode it to ``"Ä"`` for text
   insertion (keys.test.ts:514). Since this port unifies "keybinding name"
   and "insertable text" into one ``KeyEvent``, such a frame is not dropped:
   ``.name`` falls back to the decoded character itself so the event is
   still produced (with ``.text`` set to the same character). This only
   engages when the modifier is unheld or shift-only (ctrl/alt already
   disqualify text decoding, so they still yield ``None`` for genuinely
   unrecognized combinations, matching upstream fidelity there).
4. **``parse_key`` filters out Kitty key-release events (flag 2, "report
   event types") by returning ``None``**, rather than porting upstream's
   ``isKeyRelease(data)``/``wantsKeyRelease`` opt-in gate (keys.ts:520-577,
   tui.ts:829) — this port's ``Component``/``TUI`` never gained a
   ``wantsKeyRelease`` field (out of scope per ``tui.py`` module docstring
   deviation 10) and no component anywhere opts into release events, so
   filtering at the single ``parse_key`` choke point is behaviorally
   equivalent for every caller this port has today. **Bug this fixes:**
   the CSI-u event-type subfield (``;<modifier>:<event>u``, 1=press,
   2=repeat, 3=release) was previously an unused capture group — every
   physical keypress under Kitty flag 2 arrives as a press frame *and* a
   release frame for the same key, and both parsed to an identical
   ``KeyEvent`` and both got dispatched, so every keystroke typed/acted
   twice on any real terminal where Kitty negotiation actually succeeded
   (which it only started doing once the flush fix landed — see
   ``terminal.py``'s ``start()``/``.superpowers/sdd/task-19-report.md``).
   Repeat events are deliberately *not* filtered (they parse exactly like a
   press, matching upstream) — only release. See ``_parse_kitty_sequence``
   and ``parse_key``'s own docstrings for the full trace.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

__all__ = ["KeyEvent", "parse_key", "key_id"]


# =============================================================================
# KeyEvent
# =============================================================================


@dataclass(frozen=True)
class KeyEvent:
    """One parsed key press. ``name`` mirrors upstream's bare key identifiers
    (``"enter"``, "tab", "backspace", "up", ... "a", "1", "/"...).

    ``super`` is an addition beyond the brief's literal field list — see
    module docstring, deviation 1.
    """

    name: str
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    text: str | None = None
    super: bool = False


def key_id(event: KeyEvent) -> str:
    """Canonical ``"ctrl+shift+enter"``-style name for keybinding lookups.

    Modifier order (shift, ctrl, alt, super) matches upstream
    ``formatKeyNameWithModifiers`` (keys.ts:776-786) exactly — this is the
    *ground truth* order (confirmed by upstream's own ``parseKey`` assertions
    at keys.test.ts:100 ``"shift+ctrl+super+k"`` and :283
    ``"shift+ctrl+e"``), not the order-insensitive ``matchesKey(data, keyId)``
    pattern matching (keys.ts:820 ff.) which accepts any ``+``-order.
    """
    mods = []
    if event.shift:
        mods.append("shift")
    if event.ctrl:
        mods.append("ctrl")
    if event.alt:
        mods.append("alt")
    if event.super:
        mods.append("super")
    if not mods:
        return event.name
    return "+".join(mods) + "+" + event.name


# =============================================================================
# Constants (keys.ts:258-421)
# =============================================================================

SYMBOL_KEYS = set("`-=[]\\;',./!@#$%^&*()_+|~{}:<>?")

MOD_SHIFT = 1
MOD_ALT = 2
MOD_CTRL = 4
MOD_SUPER = 8
_SUPPORTED_MODIFIER_MASK = MOD_SHIFT | MOD_CTRL | MOD_ALT | MOD_SUPER
LOCK_MASK = 64 + 128  # Caps Lock + Num Lock

CODEPOINT_ESCAPE = 27
CODEPOINT_TAB = 9
CODEPOINT_ENTER = 13
CODEPOINT_SPACE = 32
CODEPOINT_BACKSPACE = 127
CODEPOINT_KP_ENTER = 57414  # Numpad Enter (Kitty protocol)

ARROW_UP = -1
ARROW_DOWN = -2
ARROW_RIGHT = -3
ARROW_LEFT = -4

FUNC_DELETE = -10
FUNC_INSERT = -11
FUNC_PAGE_UP = -12
FUNC_PAGE_DOWN = -13
FUNC_HOME = -14
FUNC_END = -15

# keys.ts:326-354
KITTY_FUNCTIONAL_KEY_EQUIVALENTS: dict[int, int] = {
    57399: 48,  # KP_0 -> 0
    57400: 49,  # KP_1 -> 1
    57401: 50,  # KP_2 -> 2
    57402: 51,  # KP_3 -> 3
    57403: 52,  # KP_4 -> 4
    57404: 53,  # KP_5 -> 5
    57405: 54,  # KP_6 -> 6
    57406: 55,  # KP_7 -> 7
    57407: 56,  # KP_8 -> 8
    57408: 57,  # KP_9 -> 9
    57409: 46,  # KP_DECIMAL -> .
    57410: 47,  # KP_DIVIDE -> /
    57411: 42,  # KP_MULTIPLY -> *
    57412: 45,  # KP_SUBTRACT -> -
    57413: 43,  # KP_ADD -> +
    57415: 61,  # KP_EQUAL -> =
    57416: 44,  # KP_SEPARATOR -> ,
    57417: ARROW_LEFT,
    57418: ARROW_RIGHT,
    57419: ARROW_UP,
    57420: ARROW_DOWN,
    57421: FUNC_PAGE_UP,
    57422: FUNC_PAGE_DOWN,
    57423: FUNC_HOME,
    57424: FUNC_END,
    57425: FUNC_INSERT,
    57426: FUNC_DELETE,
}

# keys.ts:422-481 — flat legacy-sequence -> key-id table used by parseKey.
LEGACY_SEQUENCE_KEY_IDS: dict[str, str] = {
    "\x1bOA": "up",
    "\x1bOB": "down",
    "\x1bOC": "right",
    "\x1bOD": "left",
    "\x1bOH": "home",
    "\x1bOF": "end",
    "\x1b[E": "clear",
    "\x1bOE": "clear",
    "\x1bOe": "ctrl+clear",
    "\x1b[e": "shift+clear",
    "\x1b[2~": "insert",
    "\x1b[2$": "shift+insert",
    "\x1b[2^": "ctrl+insert",
    "\x1b[3$": "shift+delete",
    "\x1b[3^": "ctrl+delete",
    "\x1b[[5~": "pageUp",
    "\x1b[[6~": "pageDown",
    "\x1b[a": "shift+up",
    "\x1b[b": "shift+down",
    "\x1b[c": "shift+right",
    "\x1b[d": "shift+left",
    "\x1bOa": "ctrl+up",
    "\x1bOb": "ctrl+down",
    "\x1bOc": "ctrl+right",
    "\x1bOd": "ctrl+left",
    "\x1b[5$": "shift+pageUp",
    "\x1b[6$": "shift+pageDown",
    "\x1b[7$": "shift+home",
    "\x1b[8$": "shift+end",
    "\x1b[5^": "ctrl+pageUp",
    "\x1b[6^": "ctrl+pageDown",
    "\x1b[7^": "ctrl+home",
    "\x1b[8^": "ctrl+end",
    "\x1bOP": "f1",
    "\x1bOQ": "f2",
    "\x1bOR": "f3",
    "\x1bOS": "f4",
    "\x1b[11~": "f1",
    "\x1b[12~": "f2",
    "\x1b[13~": "f3",
    "\x1b[14~": "f4",
    "\x1b[[A": "f1",
    "\x1b[[B": "f2",
    "\x1b[[C": "f3",
    "\x1b[[D": "f4",
    "\x1b[[E": "f5",
    "\x1b[15~": "f5",
    "\x1b[17~": "f6",
    "\x1b[18~": "f7",
    "\x1b[19~": "f8",
    "\x1b[20~": "f9",
    "\x1b[21~": "f10",
    "\x1b[23~": "f11",
    "\x1b[24~": "f12",
    "\x1bb": "alt+left",
    "\x1bf": "alt+right",
    "\x1bp": "alt+up",
    "\x1bn": "alt+down",
}


def _event_from_key_id(key_id_str: str) -> KeyEvent:
    """keys.ts:788-801 ``parseKeyId``, applied to our own static tables."""
    parts = key_id_str.split("+")
    name = parts[-1]
    mods = parts[:-1]
    return KeyEvent(
        name=name,
        ctrl="ctrl" in mods,
        alt="alt" in mods,
        shift="shift" in mods,
        super="super" in mods,
    )


def _chr_safe(codepoint: int) -> str | None:
    if codepoint < 0 or codepoint > 0x10FFFF:
        return None
    try:
        return chr(codepoint)
    except ValueError:
        return None


def _is_windows_terminal_session() -> bool:
    """keys.ts:715-719."""
    return (
        bool(os.environ.get("WT_SESSION"))
        and not os.environ.get("SSH_CONNECTION")
        and not os.environ.get("SSH_CLIENT")
        and not os.environ.get("SSH_TTY")
    )


# =============================================================================
# Kitty CSI-u / modifyOtherKeys parsing (keys.ts:497-713)
# =============================================================================

_CSI_U_RE = re.compile(r"^\x1b\[(\d+)(?::(\d*))?(?::(\d+))?(?:;(\d+))?(?::(\d+))?u$")
_ARROW_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([ABCD])$")
_FUNC_RE = re.compile(r"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?~$")
_HOME_END_RE = re.compile(r"^\x1b\[1;(\d+)(?::(\d+))?([HF])$")
_MODIFY_OTHER_KEYS_RE = re.compile(r"^\x1b\[27;(\d+);(\d+)~$")

_FUNC_CODES = {
    2: FUNC_INSERT,
    3: FUNC_DELETE,
    5: FUNC_PAGE_UP,
    6: FUNC_PAGE_DOWN,
    7: FUNC_HOME,
    8: FUNC_END,
}


_EVENT_TYPE_PRESS = "press"
_EVENT_TYPE_REPEAT = "repeat"
_EVENT_TYPE_RELEASE = "release"


def _parse_event_type(event_type_str: str | None) -> str:
    """keys.ts:579-584 ``parseEventType``. Flag 2 ("report event types")
    appends a ``:<event>`` subfield: 1 = press (also the default when the
    subfield is absent — most terminals/modes never send it), 2 = repeat
    (auto-repeat while a key is held; treated identically to a press — see
    ``parse_key``), 3 = release."""
    if not event_type_str:
        return _EVENT_TYPE_PRESS
    event_type = int(event_type_str)
    if event_type == 2:
        return _EVENT_TYPE_REPEAT
    if event_type == 3:
        return _EVENT_TYPE_RELEASE
    return _EVENT_TYPE_PRESS


@dataclass
class _KittySeq:
    codepoint: int
    shifted_key: int | None
    base_layout_key: int | None
    modifier: int  # already 0-indexed (reported value - 1)
    event_type: str = _EVENT_TYPE_PRESS


def _parse_kitty_sequence(data: str) -> _KittySeq | None:
    """keys.ts:587-651 ``parseKittySequence``.

    Parses the CSI-u event-type subfield (flag 2, "report event types":
    1=press, 2=repeat, 3=release) into ``_KittySeq.event_type``. Upstream
    instead stashes this in a module-level ``_lastEventType`` global for its
    separately-exported ``isKeyRelease(data)``/``isKeyRepeat(data)`` query
    functions, which a caller consults *after* calling ``parseKey`` — the
    only consumer in the upstream tree is ``TUI.handleInput``'s dispatch
    gate (tui.ts:829: ``if (isKeyRelease(data) &&
    !this.focusedComponent.wantsKeyRelease) return;``). This port's
    ``Component``/``TUI`` (``tui.py``) never gained a ``wantsKeyRelease``
    field — declared out of scope for task 7 (``tui.py`` module docstring
    deviation 10) — and no component anywhere in this port opts into
    key-release events, so there is no downstream gate left to perform that
    filter. ``parse_key`` therefore performs the equivalent filtering
    itself (see its docstring) rather than threading a second query function
    through every caller for a distinction this port's callers never act on
    differently. This was previously a dropped capture group entirely
    (fix: see keys.py history) — with Kitty flag 2 active, every physical
    keypress arrives as a press frame *and* a release frame for the same
    key; without parsing (and filtering) the release, both frames produced
    an identical ``KeyEvent`` and both got dispatched, typing/acting twice
    per keystroke."""
    m = _CSI_U_RE.match(data)
    if m:
        codepoint = int(m.group(1))
        shifted_key = int(m.group(2)) if m.group(2) else None
        base_layout_key = int(m.group(3)) if m.group(3) else None
        mod_value = int(m.group(4)) if m.group(4) else 1
        event_type = _parse_event_type(m.group(5))
        return _KittySeq(codepoint, shifted_key, base_layout_key, mod_value - 1, event_type)

    m = _ARROW_RE.match(data)
    if m:
        mod_value = int(m.group(1))
        event_type = _parse_event_type(m.group(2))
        arrow_codes = {"A": ARROW_UP, "B": ARROW_DOWN, "C": ARROW_RIGHT, "D": ARROW_LEFT}
        return _KittySeq(arrow_codes[m.group(3)], None, None, mod_value - 1, event_type)

    m = _FUNC_RE.match(data)
    if m:
        key_num = int(m.group(1))
        codepoint = _FUNC_CODES.get(key_num)
        if codepoint is None:
            return None
        mod_value = int(m.group(2)) if m.group(2) else 1
        event_type = _parse_event_type(m.group(3))
        return _KittySeq(codepoint, None, None, mod_value - 1, event_type)

    m = _HOME_END_RE.match(data)
    if m:
        mod_value = int(m.group(1))
        event_type = _parse_event_type(m.group(2))
        codepoint = FUNC_HOME if m.group(3) == "H" else FUNC_END
        return _KittySeq(codepoint, None, None, mod_value - 1, event_type)

    return None


def _parse_modify_other_keys_sequence(data: str) -> tuple[int, int] | None:
    """keys.ts:696-702. Returns (codepoint, modifier) or None."""
    m = _MODIFY_OTHER_KEYS_RE.match(data)
    if not m:
        return None
    mod_value = int(m.group(1))
    codepoint = int(m.group(2))
    return codepoint, mod_value - 1


def _split_modifier(modifier: int) -> tuple[bool, bool, bool, bool] | None:
    """(shift, ctrl, alt, super), or None if unsupported bits are set.

    keys.ts:776-786 ``formatKeyNameWithModifiers``'s validity gate.
    """
    effective = modifier & ~LOCK_MASK
    if effective & ~_SUPPORTED_MODIFIER_MASK:
        return None
    return (
        bool(effective & MOD_SHIFT),
        bool(effective & MOD_CTRL),
        bool(effective & MOD_ALT),
        bool(effective & MOD_SUPER),
    )


def _key_name_for_codepoint(
    codepoint: int, modifier: int, base_layout_key: int | None
) -> str | None:
    """keys.ts:1212-1249 ``formatParsedKey`` minus the trailing
    ``formatKeyNameWithModifiers`` call (modifiers are tracked separately as
    booleans on ``KeyEvent`` in this port; see ``_split_modifier``)."""
    normalized = KITTY_FUNCTIONAL_KEY_EQUIVALENTS.get(codepoint, codepoint)
    effective_mod = modifier & ~LOCK_MASK
    identity = normalized
    if (effective_mod & MOD_SHIFT) and 65 <= normalized <= 90:
        identity = normalized + 32

    is_latin_letter = 97 <= identity <= 122
    is_digit = 48 <= identity <= 57
    identity_ch = _chr_safe(identity)
    is_known_symbol = identity_ch is not None and identity_ch in SYMBOL_KEYS

    if is_latin_letter or is_digit or is_known_symbol:
        effective = identity
    else:
        effective = base_layout_key if base_layout_key is not None else identity

    if effective == CODEPOINT_ESCAPE:
        return "escape"
    if effective == CODEPOINT_TAB:
        return "tab"
    if effective in (CODEPOINT_ENTER, CODEPOINT_KP_ENTER):
        return "enter"
    if effective == CODEPOINT_SPACE:
        return "space"
    if effective == CODEPOINT_BACKSPACE:
        return "backspace"
    if effective == FUNC_DELETE:
        return "delete"
    if effective == FUNC_INSERT:
        return "insert"
    if effective == FUNC_HOME:
        return "home"
    if effective == FUNC_END:
        return "end"
    if effective == FUNC_PAGE_UP:
        return "pageUp"
    if effective == FUNC_PAGE_DOWN:
        return "pageDown"
    if effective == ARROW_UP:
        return "up"
    if effective == ARROW_DOWN:
        return "down"
    if effective == ARROW_LEFT:
        return "left"
    if effective == ARROW_RIGHT:
        return "right"
    if 48 <= effective <= 57:
        return chr(effective)
    if 97 <= effective <= 122:
        return chr(effective)
    ch = _chr_safe(effective)
    if ch is not None and ch in SYMBOL_KEYS:
        return ch
    return None


# =============================================================================
# Printable-text decoding (keys.ts:1328-1400 decodeKittyPrintable /
# decodePrintableKey) — folded into KeyEvent.text; see module docstring
# deviation 2.
# =============================================================================

_KITTY_PRINTABLE_ALLOWED_MODIFIERS = MOD_SHIFT | LOCK_MASK


def _decode_kitty_printable(codepoint: int, shifted_key: int | None, modifier: int) -> str | None:
    if modifier & ~_KITTY_PRINTABLE_ALLOWED_MODIFIERS:
        return None
    if modifier & (MOD_ALT | MOD_CTRL):
        return None
    effective = codepoint
    if (modifier & MOD_SHIFT) and shifted_key is not None:
        effective = shifted_key
    effective = KITTY_FUNCTIONAL_KEY_EQUIVALENTS.get(effective, effective)
    if effective < 32:
        return None
    return _chr_safe(effective)


def _decode_modify_other_keys_printable(codepoint: int, modifier: int) -> str | None:
    mod = modifier & ~LOCK_MASK
    if mod & ~MOD_SHIFT:
        return None
    if codepoint < 32:
        return None
    return _chr_safe(codepoint)


# =============================================================================
# parse_key (keys.ts:1206-1326 ``parseKey``)
# =============================================================================


def parse_key(frame: str, kitty: bool) -> KeyEvent | None:
    """Parse one input frame into a :class:`KeyEvent`, or ``None`` if
    unrecognized. ``kitty`` mirrors upstream's ``_kittyProtocolActive`` global
    (keys.ts:25-40), passed explicitly here for testability (see task-4-report
    RED assertion-shape mapping). Bracketed-paste frames must not reach this
    function (caller's responsibility — see ``stdin_buffer.py``).

    **Kitty key-release events are filtered out (return ``None``)** — a
    deliberate, port-adapted deviation from upstream's ``parseKey``, which
    returns the *same* ``KeyEvent`` regardless of press/repeat/release and
    instead leaves filtering to a caller that consults the separately
    exported ``isKeyRelease(data)`` (keys.ts:1206-1259 vs. tui.ts:829). See
    ``_parse_kitty_sequence``'s docstring for why this port has no
    ``wantsKeyRelease``-gated dispatch layer to put that check in instead,
    and does it here in ``parse_key`` — the single choke point every caller
    in this port (``Editor.handle_input``, currently the only consumer)
    already goes through. Repeat events are *not* filtered — matching
    upstream, they parse identically to a press (auto-repeat while a key is
    held should keep acting like repeated presses)."""

    kitty_seq = _parse_kitty_sequence(frame)
    if kitty_seq is not None:
        if kitty_seq.event_type == "release":
            return None
        mods = _split_modifier(kitty_seq.modifier)
        if mods is None:
            return None
        shift, ctrl, alt, sup = mods
        name = _key_name_for_codepoint(
            kitty_seq.codepoint, kitty_seq.modifier, kitty_seq.base_layout_key
        )
        text = _decode_kitty_printable(
            kitty_seq.codepoint, kitty_seq.shifted_key, kitty_seq.modifier
        )
        if name is None:
            if text is None:
                return None
            name = text
        return KeyEvent(name=name, ctrl=ctrl, alt=alt, shift=shift, text=text, super=sup)

    modify_other = _parse_modify_other_keys_sequence(frame)
    if modify_other is not None:
        codepoint, modifier = modify_other
        mods = _split_modifier(modifier)
        if mods is None:
            return None
        shift, ctrl, alt, sup = mods
        name = _key_name_for_codepoint(codepoint, modifier, None)
        text = _decode_modify_other_keys_printable(codepoint, modifier)
        if name is None:
            if text is None:
                return None
            name = text
        return KeyEvent(name=name, ctrl=ctrl, alt=alt, shift=shift, text=text, super=sup)

    # keys.ts:1266-1268: while Kitty protocol is active, these ambiguous
    # legacy sequences are custom terminal shift+enter mappings.
    if kitty and frame in ("\x1b\r", "\n"):
        return KeyEvent(name="enter", shift=True)

    legacy_key_id = LEGACY_SEQUENCE_KEY_IDS.get(frame)
    if legacy_key_id is not None:
        return _event_from_key_id(legacy_key_id)

    if frame == "\x1b":
        return KeyEvent(name="escape")
    if frame == "\x1c":
        return _event_from_key_id("ctrl+\\")
    if frame == "\x1d":
        return _event_from_key_id("ctrl+]")
    if frame == "\x1f":
        return _event_from_key_id("ctrl+-")
    if frame == "\x1b\x1b":
        return _event_from_key_id("ctrl+alt+[")
    if frame == "\x1b\x1c":
        return _event_from_key_id("ctrl+alt+\\")
    if frame == "\x1b\x1d":
        return _event_from_key_id("ctrl+alt+]")
    if frame == "\x1b\x1f":
        return _event_from_key_id("ctrl+alt+-")
    if frame == "\t":
        return KeyEvent(name="tab")
    if frame == "\r" or (not kitty and frame == "\n") or frame == "\x1bOM":
        return KeyEvent(name="enter")
    if frame == "\x00":
        return KeyEvent(name="space", ctrl=True)
    if frame == " ":
        return KeyEvent(name="space", text=" ")
    if frame == "\x7f":
        return KeyEvent(name="backspace")
    if frame == "\x08":
        return KeyEvent(name="backspace", ctrl=_is_windows_terminal_session())
    if frame == "\x1b[Z":
        return KeyEvent(name="tab", shift=True)
    if not kitty and frame == "\x1b\r":
        return KeyEvent(name="enter", alt=True)
    if not kitty and frame == "\x1b ":
        return KeyEvent(name="space", alt=True)
    if frame in ("\x1b\x7f", "\x1b\b"):
        return KeyEvent(name="backspace", alt=True)
    if not kitty and frame == "\x1bB":
        return KeyEvent(name="left", alt=True)
    if not kitty and frame == "\x1bF":
        return KeyEvent(name="right", alt=True)
    if not kitty and len(frame) == 2 and frame[0] == "\x1b":
        code = ord(frame[1])
        if 1 <= code <= 26:
            return KeyEvent(name=chr(code + 96), ctrl=True, alt=True)
        if (97 <= code <= 122) or (48 <= code <= 57):
            return KeyEvent(name=chr(code), alt=True)
    if frame == "\x1b[A":
        return KeyEvent(name="up")
    if frame == "\x1b[B":
        return KeyEvent(name="down")
    if frame == "\x1b[C":
        return KeyEvent(name="right")
    if frame == "\x1b[D":
        return KeyEvent(name="left")
    if frame in ("\x1b[H", "\x1bOH"):
        return KeyEvent(name="home")
    if frame in ("\x1b[F", "\x1bOF"):
        return KeyEvent(name="end")
    if frame == "\x1b[3~":
        return KeyEvent(name="delete")
    if frame == "\x1b[5~":
        return KeyEvent(name="pageUp")
    if frame == "\x1b[6~":
        return KeyEvent(name="pageDown")

    if len(frame) == 1:
        code = ord(frame)
        if 1 <= code <= 26:
            return KeyEvent(name=chr(code + 96), ctrl=True)
        if 32 <= code <= 126:
            return KeyEvent(name=frame, text=frame)

    return None
