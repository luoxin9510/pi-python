"""
Tests for keyboard input handling

Translation from upstream: packages/tui/test/keys.test.ts (614 lines)

Assertion shape mapping (TS -> Python):
- TS: matchesKey(frame, "ctrl+c") -> True
  PY: parse_key(frame, kitty=...) -> KeyEvent(...) where key_id(result) == "ctrl+c"
- TS: parseKey(frame) -> "ctrl+c"
  PY: parse_key(frame, kitty=...) -> KeyEvent(...) where key_id(result) == "ctrl+c"
- TS: parseKey(frame) -> undefined
  PY: parse_key(frame, kitty=...) -> None
- TS: setKittyProtocolActive(True/False) sets global state
  PY: kitty parameter passed to parse_key()

Coverage domains:
- Legacy arrows/function keys/Ctrl combos
- Kitty CSI-u with modifiers and flag-4 alternate keys
- UTF-8 text keys
"""

import os

from pipython.tui.engine.keys import key_id, parse_key


class TestKittyProtocolWithAlternateKeys:
    """Kitty protocol flag 4 (Report alternate keys) sends:
    CSI codepoint:shifted:base ; modifier:event u
    Where base is the key in standard PC-101 layout
    """

    def test_should_match_ctrl_c_when_pressing_cyrillic_with_base_layout_key(self):
        # Cyrillic 'с' = codepoint 1089, Latin 'c' = codepoint 99
        # Format: CSI 1089::99;5u (codepoint::base;modifier with ctrl=4, +1=5)
        cyrillic_ctrl_c = "\x1b[1089::99;5u"
        result = parse_key(cyrillic_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_match_ctrl_d_when_pressing_cyrillic_d_with_base_layout_key(self):
        # Cyrillic 'в' = codepoint 1074, Latin 'd' = codepoint 100
        cyrillic_ctrl_d = "\x1b[1074::100;5u"
        result = parse_key(cyrillic_ctrl_d, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+d"

    def test_should_match_ctrl_z_when_pressing_cyrillic_z_with_base_layout_key(self):
        # Cyrillic 'я' = codepoint 1103, Latin 'z' = codepoint 122
        cyrillic_ctrl_z = "\x1b[1103::122;5u"
        result = parse_key(cyrillic_ctrl_z, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+z"

    def test_should_match_ctrl_shift_p_with_base_layout_key(self):
        # Cyrillic 'з' = codepoint 1079, Latin 'p' = codepoint 112
        # ctrl=4, shift=1, +1 = 6
        #
        # RED correction: the upstream source (keys.test.ts:77) is
        # `matchesKey(cyrillicCtrlShiftP, "ctrl+shift+p")`, an order-insensitive
        # pattern match (parseKeyId just checks `parts.includes("ctrl")` etc,
        # keys.ts:788-801) — it does NOT assert what parseKey's canonical
        # string would be. Our key_id() models parseKey's canonical,
        # order-*sensitive* output (formatKeyNameWithModifiers, keys.ts:
        # 776-786, pushes shift before ctrl), and upstream's own parseKey
        # ground truth confirms shift-before-ctrl ordering (keys.test.ts:283
        # `parseKey(...) === "shift+ctrl+e"`, :100 `"shift+ctrl+super+k"`).
        # The original RED translation of the matchesKey call assumed the
        # matchesKey argument order was the canonical order; it isn't.
        cyrillic_ctrl_shift_p = "\x1b[1079::112;6u"
        result = parse_key(cyrillic_ctrl_shift_p, kitty=True)
        assert result is not None
        assert key_id(result) == "shift+ctrl+p"

    def test_should_match_latin_ctrl_c_without_base_layout_key(self):
        # Latin ctrl+c without base layout key (terminal doesn't support flag 4)
        latin_ctrl_c = "\x1b[99;5u"
        result = parse_key(latin_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_match_super_modified_kitty_bindings_with_combined_modifiers(self):
        # Tests for super modifier (modifier bit 8, reported as 9 with base 1)
        result = parse_key("\x1b[107;9u", kitty=True)
        assert result is not None
        assert key_id(result) == "super+k"

        result = parse_key("\x1b[13;9u", kitty=True)
        assert result is not None
        assert key_id(result) == "super+enter"

        result = parse_key("\x1b[107;13u", kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+super+k"

        result = parse_key("\x1b[107;14u", kitty=True)
        assert result is not None
        # Order normalized: shift+ctrl+super+k
        assert key_id(result) == "shift+ctrl+super+k"

    def test_should_match_digit_bindings_via_kitty_csi_u(self):
        result = parse_key("\x1b[49u", kitty=True)
        assert result is not None
        assert key_id(result) == "1"

        result = parse_key("\x1b[49;5u", kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+1"

    def test_should_normalize_kitty_keypad_functional_keys(self):
        # Keypad functional keys normalize to logical digits, symbols, and navigation
        result = parse_key("\x1b[57400u", kitty=True)
        assert result is not None
        assert key_id(result) == "1"

        result = parse_key("\x1b[57410u", kitty=True)
        assert result is not None
        assert key_id(result) == "/"

        result = parse_key("\x1b[57417u", kitty=True)
        assert result is not None
        assert key_id(result) == "left"

        result = parse_key("\x1b[57426u", kitty=True)
        assert result is not None
        assert key_id(result) == "delete"

    def test_keypad_functional_key_parsing(self):
        # Additional keypad keys
        result = parse_key("\x1b[57399u", kitty=True)
        assert result is not None
        assert key_id(result) == "0"

        result = parse_key("\x1b[57409u", kitty=True)
        assert result is not None
        assert key_id(result) == "."

        result = parse_key("\x1b[57413u", kitty=True)
        assert result is not None
        assert key_id(result) == "+"

        result = parse_key("\x1b[57416u", kitty=True)
        assert result is not None
        assert key_id(result) == ","

        result = parse_key("\x1b[57418u", kitty=True)
        assert result is not None
        assert key_id(result) == "right"

        result = parse_key("\x1b[57419u", kitty=True)
        assert result is not None
        assert key_id(result) == "up"

        result = parse_key("\x1b[57420u", kitty=True)
        assert result is not None
        assert key_id(result) == "down"

        result = parse_key("\x1b[57421u", kitty=True)
        assert result is not None
        assert key_id(result) == "pageUp"

        result = parse_key("\x1b[57422u", kitty=True)
        assert result is not None
        assert key_id(result) == "pageDown"

        result = parse_key("\x1b[57423u", kitty=True)
        assert result is not None
        assert key_id(result) == "home"

        result = parse_key("\x1b[57424u", kitty=True)
        assert result is not None
        assert key_id(result) == "end"

        result = parse_key("\x1b[57425u", kitty=True)
        assert result is not None
        assert key_id(result) == "insert"

    def test_should_handle_shifted_key_in_format(self):
        # Format with shifted key: CSI codepoint:shifted:base;modifier u
        # Latin 'c' with shifted 'C' (67) and base 'c' (99)
        shifted_key = "\x1b[99:67:99;2u"  # shift modifier = 1, +1 = 2
        result = parse_key(shifted_key, kitty=True)
        assert result is not None
        assert key_id(result) == "shift+c"

    def test_should_handle_event_type_in_format(self):
        # Format with event type: CSI codepoint::base;modifier:event u
        # Cyrillic ctrl+c release event (event type 3)
        #
        # Acceptance-bug-1 correction: upstream source is
        # `matchesKey(releaseEvent, "ctrl+c")` -> true (keys.test.ts:149-151)
        # because upstream's parseKey/matchesKey never filter by event type
        # at all -- release filtering is a *caller* concern, gated by
        # `isKeyRelease(data) && !focusedComponent.wantsKeyRelease` at
        # `TUI.handleInput` (tui.ts:829). This port's `Component`/`TUI`
        # never gained a `wantsKeyRelease` field (out of scope per tui.py
        # module docstring deviation 10), and no component here opts into
        # release events, so `parse_key` itself is the single choke point
        # that filters them (see its docstring) -- this was the actual
        # real-terminal doubled-keystroke bug (every keypress under Kitty
        # flag 2 arrives as press+release; both used to parse identically
        # and both got dispatched). A release event therefore returns
        # `None` here, not a `KeyEvent` -- the opposite of upstream's
        # literal `matchesKey` return value for the same input.
        release_event = "\x1b[1089::99;5:3u"
        result = parse_key(release_event, kitty=True)
        assert result is None

    def test_should_handle_full_format_with_shifted_base_and_event_type(self):
        # Full format: CSI codepoint:shifted:base;modifier:event u
        # Cyrillic 'С' (shifted) with base 'c', Ctrl+Shift pressed, repeat event
        # Cyrillic 'с' = 1089, Cyrillic 'С' = 1057, Latin 'c' = 99
        # ctrl=4, shift=1, +1 = 6, repeat event = 2
        #
        # RED correction: same order issue as
        # test_should_match_ctrl_shift_p_with_base_layout_key above — upstream
        # source (keys.test.ts:163) is the order-insensitive
        # `matchesKey(fullFormat, "ctrl+shift+c")`, not a parseKey canonical
        # value. Canonical order is shift-before-ctrl (see citations above).
        full_format = "\x1b[1089:1057:99;6:2u"
        result = parse_key(full_format, kitty=True)
        assert result is not None
        assert key_id(result) == "shift+ctrl+c"

    def test_should_prefer_codepoint_for_latin_letters_when_base_differs(self):
        # Dvorak Ctrl+K reports codepoint 'k' (107) and base layout 'v' (118)
        dvorak_ctrl_k = "\x1b[107::118;5u"
        result = parse_key(dvorak_ctrl_k, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+k"

    def test_should_prefer_codepoint_for_symbol_keys_when_base_differs(self):
        # Dvorak Ctrl+/ reports codepoint '/' (47) and base layout '[' (91)
        dvorak_ctrl_slash = "\x1b[47::91;5u"
        result = parse_key(dvorak_ctrl_slash, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+/"

    def test_should_not_match_wrong_key_even_with_base_layout(self):
        # Cyrillic ctrl+с with base 'c' should NOT match ctrl+d
        cyrillic_ctrl_c = "\x1b[1089::99;5u"
        result = parse_key(cyrillic_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) != "ctrl+d"

    def test_should_not_match_wrong_modifiers_even_with_base_layout(self):
        # Cyrillic ctrl+с should NOT match ctrl+shift+c
        cyrillic_ctrl_c = "\x1b[1089::99;5u"
        result = parse_key(cyrillic_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) != "ctrl+shift+c"


class TestModifyOtherKeysMatching:
    """xterm modifyOtherKeys format tests"""

    def test_should_match_xterm_modify_other_keys_ctrl_c(self):
        result = parse_key("\x1b[27;5;99~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_match_xterm_modify_other_keys_ctrl_d(self):
        result = parse_key("\x1b[27;5;100~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+d"

    def test_should_match_xterm_modify_other_keys_ctrl_z(self):
        result = parse_key("\x1b[27;5;122~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+z"

    def test_should_match_xterm_modify_other_keys_enter_variants(self):
        result = parse_key("\x1b[27;5;13~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+enter"

        result = parse_key("\x1b[27;2;13~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+enter"

        result = parse_key("\x1b[27;3;13~", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+enter"

    def test_should_match_xterm_modify_other_keys_tab_variants(self):
        result = parse_key("\x1b[27;2;9~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+tab"

        result = parse_key("\x1b[27;5;9~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+tab"

        result = parse_key("\x1b[27;3;9~", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+tab"

    def test_should_match_xterm_modify_other_keys_backspace_variants(self):
        result = parse_key("\x1b[27;1;127~", kitty=False)
        assert result is not None
        assert key_id(result) == "backspace"

        result = parse_key("\x1b[27;5;127~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+backspace"

        result = parse_key("\x1b[27;3;127~", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+backspace"

    def test_should_match_xterm_modify_other_keys_escape(self):
        result = parse_key("\x1b[27;1;27~", kitty=False)
        assert result is not None
        assert key_id(result) == "escape"

    def test_should_match_xterm_modify_other_keys_space_variants(self):
        result = parse_key("\x1b[27;1;32~", kitty=False)
        assert result is not None
        assert key_id(result) == "space"

        result = parse_key("\x1b[27;5;32~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+space"

    def test_should_match_xterm_modify_other_keys_symbol_combos(self):
        result = parse_key("\x1b[27;5;47~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+/"

    def test_should_match_xterm_modify_other_keys_digit_combos(self):
        result = parse_key("\x1b[27;5;49~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+1"

        result = parse_key("\x1b[27;2;49~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+1"

    def test_should_match_xterm_modify_other_keys_shifted_uppercase_letters(self):
        result = parse_key("\x1b[27;2;69~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+e"

        result = parse_key("\x1b[27;6;69~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+ctrl+e"

    def test_should_match_ctrl_alt_letter_via_csi_u_when_kitty_inactive(self):
        result = parse_key("\x1b[104;7u", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+h"

    def test_should_match_ctrl_alt_letter_via_xterm_modify_other_keys(self):
        result = parse_key("\x1b[27;7;104~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+h"


class TestLegacyKeyMatching:
    """Legacy terminal key matching tests"""

    def test_should_match_legacy_ctrl_c(self):
        # Ctrl+c sends ASCII 3 (ETX)
        result = parse_key("\x03", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_match_legacy_ctrl_d(self):
        # Ctrl+d sends ASCII 4 (EOT)
        result = parse_key("\x04", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+d"

    def test_should_match_escape_key(self):
        result = parse_key("\x1b", kitty=False)
        assert result is not None
        assert key_id(result) == "escape"

    def test_should_match_legacy_linefeed_as_enter(self):
        result = parse_key("\n", kitty=False)
        assert result is not None
        assert key_id(result) == "enter"

    def test_should_treat_linefeed_as_shift_enter_when_kitty_active(self):
        result = parse_key("\n", kitty=True)
        assert result is not None
        assert key_id(result) == "shift+enter"

    def test_should_parse_ctrl_space(self):
        result = parse_key("\x00", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+space"

    def test_should_match_legacy_ctrl_symbol(self):
        # Ctrl+\ sends ASCII 28 (File Separator) in legacy terminals
        result = parse_key("\x1c", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+\\"

        # Ctrl+] sends ASCII 29 (Group Separator) in legacy terminals
        result = parse_key("\x1d", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+]"

        # Ctrl+_ sends ASCII 31 (Unit Separator) in legacy terminals
        # Ctrl+- is on the same physical key on US keyboards
        result = parse_key("\x1f", kitty=False)
        assert result is not None
        assert key_id(result) in ("ctrl+_", "ctrl+-")

    def test_should_match_legacy_ctrl_alt_symbol(self):
        # Ctrl+Alt+[ sends ESC followed by ESC (Ctrl+[ = ESC)
        result = parse_key("\x1b\x1b", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+["

        # Ctrl+Alt+\ sends ESC followed by ASCII 28
        result = parse_key("\x1b\x1c", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+\\"

        # Ctrl+Alt+] sends ESC followed by ASCII 29
        result = parse_key("\x1b\x1d", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+]"

        # Ctrl+_ sends ASCII 31 (Unit Separator) in legacy terminals
        # Ctrl+- is on the same physical key on US keyboards
        result = parse_key("\x1b\x1f", kitty=False)
        assert result is not None
        assert key_id(result) in ("ctrl+alt+_", "ctrl+alt+-")

    def test_should_treat_raw_0x08_as_plain_backspace_outside_windows_terminal(self):
        # Remove Windows Terminal env vars if they exist
        saved_env = {}
        for key in ["WT_SESSION", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"]:
            saved_env[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]

        try:
            result = parse_key("\x7f", kitty=False)
            assert result is not None
            assert key_id(result) == "backspace"

            result = parse_key("\x08", kitty=False)
            assert result is not None
            assert key_id(result) == "backspace"
        finally:
            # Restore env
            for key, value in saved_env.items():
                if value is not None:
                    os.environ[key] = value

    def test_should_treat_raw_0x08_as_ctrl_backspace_in_local_windows_terminal(self):
        saved_env = {}
        for key in ["WT_SESSION", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"]:
            saved_env[key] = os.environ.get(key)

        try:
            # Set Windows Terminal env vars
            os.environ["WT_SESSION"] = "test-session"
            if "SSH_CONNECTION" in os.environ:
                del os.environ["SSH_CONNECTION"]
            if "SSH_CLIENT" in os.environ:
                del os.environ["SSH_CLIENT"]
            if "SSH_TTY" in os.environ:
                del os.environ["SSH_TTY"]

            result = parse_key("\x08", kitty=False)
            assert result is not None
            assert key_id(result) == "ctrl+backspace"
        finally:
            # Restore env
            for key, value in saved_env.items():
                if value is not None:
                    os.environ[key] = value
                elif key in os.environ:
                    del os.environ[key]

    def test_should_treat_raw_0x08_as_plain_backspace_in_windows_terminal_over_ssh(self):
        saved_env = {}
        for key in ["WT_SESSION", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"]:
            saved_env[key] = os.environ.get(key)

        try:
            # Set Windows Terminal + SSH env vars
            os.environ["WT_SESSION"] = "test-session"
            os.environ["SSH_CONNECTION"] = "1 2 3 4"
            os.environ["SSH_CLIENT"] = "1 2 3"
            os.environ["SSH_TTY"] = "/dev/pts/1"

            result = parse_key("\x08", kitty=False)
            assert result is not None
            assert key_id(result) == "backspace"
        finally:
            # Restore env
            for key, value in saved_env.items():
                if value is not None:
                    os.environ[key] = value
                elif key in os.environ:
                    del os.environ[key]

    def test_should_parse_legacy_alt_prefixed_sequences_when_kitty_inactive(self):
        result = parse_key("\x1b ", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+space"

        result = parse_key("\x1b\b", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+backspace"

        result = parse_key("\x1b\x03", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+c"

        result = parse_key("\x1bB", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+left"

        result = parse_key("\x1bF", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+right"

        result = parse_key("\x1ba", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+a"

        result = parse_key("\x1b1", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+1"

        result = parse_key("\x1by", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+y"

        result = parse_key("\x1bz", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+z"

    def test_should_not_parse_legacy_alt_when_kitty_active(self):
        result = parse_key("\x1b ", kitty=True)
        assert result is None

        result = parse_key("\x1b\x03", kitty=True)
        assert result is None

        result = parse_key("\x1bB", kitty=True)
        assert result is None

        result = parse_key("\x1bF", kitty=True)
        assert result is None

        result = parse_key("\x1ba", kitty=True)
        assert result is None

        result = parse_key("\x1b1", kitty=True)
        assert result is None

        result = parse_key("\x1by", kitty=True)
        assert result is None

    def test_should_match_arrow_keys(self):
        result = parse_key("\x1b[A", kitty=False)
        assert result is not None
        assert key_id(result) == "up"

        result = parse_key("\x1b[B", kitty=False)
        assert result is not None
        assert key_id(result) == "down"

        result = parse_key("\x1b[C", kitty=False)
        assert result is not None
        assert key_id(result) == "right"

        result = parse_key("\x1b[D", kitty=False)
        assert result is not None
        assert key_id(result) == "left"

    def test_should_match_ss3_arrows_and_home_end(self):
        result = parse_key("\x1bOA", kitty=False)
        assert result is not None
        assert key_id(result) == "up"

        result = parse_key("\x1bOB", kitty=False)
        assert result is not None
        assert key_id(result) == "down"

        result = parse_key("\x1bOC", kitty=False)
        assert result is not None
        assert key_id(result) == "right"

        result = parse_key("\x1bOD", kitty=False)
        assert result is not None
        assert key_id(result) == "left"

        result = parse_key("\x1bOH", kitty=False)
        assert result is not None
        assert key_id(result) == "home"

        result = parse_key("\x1bOF", kitty=False)
        assert result is not None
        assert key_id(result) == "end"

    def test_should_match_legacy_function_keys_and_clear(self):
        result = parse_key("\x1bOP", kitty=False)
        assert result is not None
        assert key_id(result) == "f1"

        result = parse_key("\x1b[24~", kitty=False)
        assert result is not None
        assert key_id(result) == "f12"

        result = parse_key("\x1b[E", kitty=False)
        assert result is not None
        assert key_id(result) == "clear"

    def test_should_match_alt_arrows(self):
        result = parse_key("\x1bp", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+up"

    def test_should_match_rxvt_modifier_sequences(self):
        result = parse_key("\x1b[a", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+up"

        result = parse_key("\x1bOa", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+up"

        result = parse_key("\x1b[2$", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+insert"

        result = parse_key("\x1b[2^", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+insert"

        result = parse_key("\x1b[7$", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+home"


class TestParseKey:
    """parseKey-specific tests"""

    def test_should_return_latin_key_name_when_base_layout_key_is_present(self):
        # Cyrillic ctrl+с with base layout 'c'
        cyrillic_ctrl_c = "\x1b[1089::99;5u"
        result = parse_key(cyrillic_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_prefer_codepoint_for_latin_letters_when_base_layout_differs(self):
        # Dvorak Ctrl+K reports codepoint 'k' (107) and base layout 'v' (118)
        dvorak_ctrl_k = "\x1b[107::118;5u"
        result = parse_key(dvorak_ctrl_k, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+k"

    def test_should_prefer_codepoint_for_symbol_keys_when_base_layout_differs(self):
        # Dvorak Ctrl+/ reports codepoint '/' (47) and base layout '[' (91)
        dvorak_ctrl_slash = "\x1b[47::91;5u"
        result = parse_key(dvorak_ctrl_slash, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+/"

    def test_should_return_key_name_from_codepoint_when_no_base_layout(self):
        latin_ctrl_c = "\x1b[99;5u"
        result = parse_key(latin_ctrl_c, kitty=True)
        assert result is not None
        assert key_id(result) == "ctrl+c"

    def test_should_parse_shifted_uppercase_csi_u_letters_as_shift_letter(self):
        result = parse_key("\x1b[69;2u", kitty=True)
        assert result is not None
        assert key_id(result) == "shift+e"

    def test_should_ignore_kitty_csi_u_with_unsupported_modifiers(self):
        result = parse_key("\x1b[99;17u", kitty=True)
        assert result is None

    def test_should_parse_legacy_ctrl_letter(self):
        result = parse_key("\x03", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+c"

        result = parse_key("\x04", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+d"

    def test_should_parse_special_keys(self):
        result = parse_key("\x1b", kitty=False)
        assert result is not None
        assert key_id(result) == "escape"

        result = parse_key("\t", kitty=False)
        assert result is not None
        assert key_id(result) == "tab"

        result = parse_key("\r", kitty=False)
        assert result is not None
        assert key_id(result) == "enter"

        result = parse_key("\n", kitty=False)
        assert result is not None
        assert key_id(result) == "enter"

        result = parse_key("\x00", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+space"

        result = parse_key(" ", kitty=False)
        assert result is not None
        assert key_id(result) == "space"

        result = parse_key("1", kitty=False)
        assert result is not None
        assert key_id(result) == "1"

    def test_should_parse_arrow_keys(self):
        result = parse_key("\x1b[A", kitty=False)
        assert result is not None
        assert key_id(result) == "up"

        result = parse_key("\x1b[B", kitty=False)
        assert result is not None
        assert key_id(result) == "down"

        result = parse_key("\x1b[C", kitty=False)
        assert result is not None
        assert key_id(result) == "right"

        result = parse_key("\x1b[D", kitty=False)
        assert result is not None
        assert key_id(result) == "left"

    def test_should_parse_ss3_arrows_and_home_end(self):
        result = parse_key("\x1bOA", kitty=False)
        assert result is not None
        assert key_id(result) == "up"

        result = parse_key("\x1bOB", kitty=False)
        assert result is not None
        assert key_id(result) == "down"

        result = parse_key("\x1bOC", kitty=False)
        assert result is not None
        assert key_id(result) == "right"

        result = parse_key("\x1bOD", kitty=False)
        assert result is not None
        assert key_id(result) == "left"

        result = parse_key("\x1bOH", kitty=False)
        assert result is not None
        assert key_id(result) == "home"

        result = parse_key("\x1bOF", kitty=False)
        assert result is not None
        assert key_id(result) == "end"

    def test_should_parse_legacy_function_and_modifier_sequences(self):
        result = parse_key("\x1bOP", kitty=False)
        assert result is not None
        assert key_id(result) == "f1"

        result = parse_key("\x1b[24~", kitty=False)
        assert result is not None
        assert key_id(result) == "f12"

        result = parse_key("\x1b[E", kitty=False)
        assert result is not None
        assert key_id(result) == "clear"

        result = parse_key("\x1b[2^", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+insert"

        result = parse_key("\x1bp", kitty=False)
        assert result is not None
        assert key_id(result) == "alt+up"

    def test_should_parse_double_bracket_page_up(self):
        result = parse_key("\x1b[[5~", kitty=False)
        assert result is not None
        assert key_id(result) == "pageUp"


class TestPrintableTextDecoding:
    """Un-skipped conversions of upstream's ``decodeKittyPrintable`` /
    ``decodePrintableKey`` internal-helper test suites (keys.test.ts:496-518).

    Those two suites test standalone functions that aren't part of the
    task-4 brief's public surface (KeyEvent/parse_key/key_id). This port
    folds their behavior into ``KeyEvent.text`` (see keys.py module
    docstring, deviation 2), so the *meaningful* assertions from both
    suites are translated here as public-surface tests: same input frames,
    same expected decoded characters, observed through
    ``parse_key(frame, kitty=...).text`` instead of calling the internal
    helper directly. None of the 15 upstream assertions (10 + 5) turned out
    to be unobservable through parse_key, so none remain skipped.
    """

    def test_should_decode_kitty_keypad_functional_keys_to_printable_text(self):
        # Translated from keys.test.ts:496-508 (decodeKittyPrintable).
        cases = [
            ("\x1b[57399u", "0"),
            ("\x1b[57400u", "1"),
            ("\x1b[57409u", "."),
            ("\x1b[57410u", "/"),
            ("\x1b[57411u", "*"),
            ("\x1b[57412u", "-"),
            ("\x1b[57413u", "+"),
            ("\x1b[57415u", "="),
            ("\x1b[57416u", ","),
        ]
        for frame, expected_text in cases:
            result = parse_key(frame, kitty=True)
            assert result is not None
            assert result.text == expected_text

        # keys.test.ts:507 — KP_LEFT normalizes to the (non-printable) arrow
        # codepoint, so it has a recognized *name* ("left", already covered
        # by test_should_normalize_kitty_keypad_functional_keys above) but no
        # printable text.
        result = parse_key("\x1b[57417u", kitty=True)
        assert result is not None
        assert key_id(result) == "left"
        assert result.text is None

    def test_should_decode_xterm_modify_other_keys_printable_text(self):
        # Translated from keys.test.ts:511-518 (decodePrintableKey).
        result = parse_key("\x1b[27;2;69~", kitty=False)
        assert result is not None
        assert result.text == "E"

        # Non-ASCII codepoint (196 = 'Ä'): no recognized KeyId taxonomy entry
        # for it (see keys.py deviation 3), but it must still decode as
        # printable text rather than being dropped.
        result = parse_key("\x1b[27;2;196~", kitty=False)
        assert result is not None
        assert result.text == "Ä"

        result = parse_key("\x1b[27;2;32~", kitty=False)
        assert result is not None
        assert result.text == " "

        # Shift+Enter: codepoint 13 is a control character, never printable.
        result = parse_key("\x1b[27;2;13~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+enter"
        assert result.text is None

        # Shift+Ctrl+E: ctrl held disqualifies text decoding even though the
        # key has a recognized name.
        result = parse_key("\x1b[27;6;69~", kitty=False)
        assert result is not None
        assert key_id(result) == "shift+ctrl+e"
        assert result.text is None

    def test_should_decode_shifted_kitty_csi_u_key_to_uppercase_text(self):
        # Extends test_should_parse_shifted_uppercase_csi_u_letters_as_shift_letter:
        # the *name* normalizes shift+E to lowercase "e" (keybinding
        # convention), but the *text* to insert is the literal reported
        # character "E" (decodeKittyPrintable does not lowercase).
        result = parse_key("\x1b[69;2u", kitty=True)
        assert result is not None
        assert key_id(result) == "shift+e"
        assert result.text == "E"

        # Format with an explicit shifted-key subfield (keys.test.ts:166-172):
        # shift held + a distinct shifted glyph reported -> text prefers the
        # shifted glyph over the base codepoint.
        result = parse_key("\x1b[99:67:99;2u", kitty=True)
        assert result is not None
        assert key_id(result) == "shift+c"
        assert result.text == "C"

    def test_should_not_produce_printable_text_for_ctrl_or_alt_combos(self):
        # ctrl+c (legacy) and ctrl+alt+h (kitty CSI-u) are keybindings, not
        # insertable text.
        result = parse_key("\x03", kitty=False)
        assert result is not None
        assert result.text is None

        result = parse_key("\x1b[104;7u", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+alt+h"
        assert result.text is None

    def test_should_produce_printable_text_for_plain_ascii_frames(self):
        # Raw single-character legacy frames (no escape sequence at all) are
        # already the literal text — covered implicitly by upstream's raw
        # `data.length === 1` fallback (keys.ts:1315-1322); asserted here
        # explicitly against .text since upstream has no dedicated test for
        # this (it only asserts the key-id side, keys.test.ts:582).
        result = parse_key("1", kitty=False)
        assert result is not None
        assert result.text == "1"

        result = parse_key(" ", kitty=False)
        assert result is not None
        assert result.text == " "


class TestKittyKeyReleaseFiltering:
    """Acceptance bug 1 (real-terminal doubled keystrokes): Kitty flag 2
    ("report event types") makes every physical keypress arrive as a
    *press* frame followed by a *release* frame for the same key. Upstream
    dispatches both through ``parseKey``/``matchesKey`` identically and
    instead gates release events at ``TUI.handleInput``
    (``isKeyRelease(data) && !focusedComponent.wantsKeyRelease`` —
    tui.ts:829). This port has no ``wantsKeyRelease``-gated dispatch layer
    (see ``tui.py`` module docstring deviation 10), so ``parse_key`` itself
    filters release events by returning ``None`` — see its docstring.
    Before this fix, the CSI-u event-type subfield was an unused capture
    group and every keystroke typed/acted twice.
    """

    def test_release_of_plain_letter_returns_none(self):
        # 'a', unmodified. Press: event=1 (or omitted). Release: event=3.
        press = parse_key("\x1b[97;1:1u", kitty=True)
        release = parse_key("\x1b[97;1:3u", kitty=True)
        assert press is not None
        assert key_id(press) == "a"
        assert press.text == "a"
        assert release is None

    def test_release_with_omitted_event_subfield_defaults_to_press(self):
        # No `:<event>` subfield at all -> upstream's parseEventType treats
        # the absence as "press" (keys.ts:580 `if (!eventTypeStr) return
        # "press"`), not as a release. Only an explicit `:3` is a release.
        result = parse_key("\x1b[97;1u", kitty=True)
        assert result is not None
        assert key_id(result) == "a"

    def test_release_of_ctrl_c_returns_none(self):
        # The maintainer's reported doubling: Ctrl+C typed once must not
        # dispatch twice (press + release).
        press = parse_key("\x1b[99;5:1u", kitty=True)
        release = parse_key("\x1b[99;5:3u", kitty=True)
        assert press is not None
        assert key_id(press) == "ctrl+c"
        assert release is None

    def test_release_of_arrow_key_returns_none(self):
        press = parse_key("\x1b[1;1:1A", kitty=True)
        release = parse_key("\x1b[1;1:3A", kitty=True)
        assert press is not None
        assert key_id(press) == "up"
        assert release is None

    def test_release_of_functional_key_returns_none(self):
        # Delete key (`~` form, keys.ts _FUNC_CODES 3 -> delete).
        press = parse_key("\x1b[3;1:1~", kitty=True)
        release = parse_key("\x1b[3;1:3~", kitty=True)
        assert press is not None
        assert key_id(press) == "delete"
        assert release is None

    def test_release_of_home_end_key_returns_none(self):
        press = parse_key("\x1b[1;1:1H", kitty=True)
        release = parse_key("\x1b[1;1:3H", kitty=True)
        assert press is not None
        assert key_id(press) == "home"
        assert release is None

    def test_repeat_event_still_parses_like_a_press(self):
        # event=2 (repeat, auto-repeat while a key is held) must NOT be
        # filtered -- it should act exactly like a press.
        repeat = parse_key("\x1b[97;1:2u", kitty=True)
        assert repeat is not None
        assert key_id(repeat) == "a"
        assert repeat.text == "a"

    def test_release_with_cyrillic_base_layout_key_still_returns_none(self):
        # Combines flag-4 (alternate keys) with flag-2 (event type): a
        # release event must be filtered regardless of what else the
        # sequence encodes.
        release = parse_key("\x1b[1089::99;5:3u", kitty=True)
        assert release is None

    def test_release_with_unsupported_modifier_bits_still_returns_none(self):
        # Regression guard: an unsupported-modifier CSI-u sequence already
        # returned None via `_split_modifier` before this fix. Confirm the
        # new release check doesn't change that outcome when combined with
        # an event-type subfield (order of checks must not matter).
        result = parse_key("\x1b[99;9:3u", kitty=True)
        assert result is None

    def test_unrecognized_event_type_digit_falls_back_to_press(self):
        # keys.ts:579-584 `parseEventType`: any digit other than 2 or 3
        # (including e.g. 9, or a value a future kitty revision might add)
        # falls back to "press", not release -- so it must NOT be filtered.
        result = parse_key("\x1b[97;1:9u", kitty=True)
        assert result is not None
        assert key_id(result) == "a"

    def test_modify_other_keys_sequences_have_no_event_type_and_are_unaffected(self):
        # xterm modifyOtherKeys (fallback protocol when Kitty isn't
        # negotiated) has no event-type field at all -- this fix must not
        # touch that path.
        result = parse_key("\x1b[27;5;99~", kitty=False)
        assert result is not None
        assert key_id(result) == "ctrl+c"
