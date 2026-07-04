import re

import pytest
from pipython.tui.engine.utils import (
    apply_background_to_line,
    graphemes,
    truncate_to_width,
    visible_width,
    wrap_text_with_ansi,
)

CASES_WIDTH = [
    ("abc", 3),
    ("中文", 4),
    ("a中b", 4),
    ("", 0),
    ("\x1b[31m红\x1b[0m", 2),  # ANSI 零宽
    ("👩‍👩‍👧‍👦", 2),  # ZWJ 家庭 = 单字素宽 2
    ("é", 1),  # 组合重音
    ("ｆｕｌｌ", 8),  # 全角拉丁
]


@pytest.mark.parametrize("s,w", CASES_WIDTH)
def test_visible_width(s, w):
    assert visible_width(s) == w


def test_graphemes_zwj_single_cluster():
    assert len(graphemes("👩‍👩‍👧‍👦x")) == 2


def test_wrap_cjk_never_splits_grapheme():
    lines = wrap_text_with_ansi("中文字符串测试", 5)
    assert all(visible_width(x) <= 5 for x in lines)
    assert "".join(lines) == "中文字符串测试"


def test_wrap_preserves_ansi_state_across_lines():
    lines = wrap_text_with_ansi("\x1b[31m" + "红" * 6 + "\x1b[0m", 4)
    assert len(lines) == 3 and all("\x1b[31m" in x for x in lines[1:])


def test_wrap_osc8_reopens_on_continuation():
    link = "\x1b]8;;http://x\x1b\\" + "a" * 8 + "\x1b]8;;\x1b\\"
    lines = wrap_text_with_ansi(link, 4)
    assert all(line.startswith("\x1b]8;;http://x") or i == 0 for i, line in enumerate(lines))


def test_truncate_to_width_cjk():
    assert truncate_to_width("中文测试", 5) == "中文…"


def test_apply_background_pads_to_width():
    out = apply_background_to_line("ab", "\x1b[44m", 5)
    assert visible_width(out) == 5 and out.startswith("\x1b[44m")


# [TEST-PORT] Translated from upstream packages/tui/test/wrap-ansi.test.ts
# (describe("wrapTextWithAnsi") + describe("wrapTextWithAnsi with OSC 8
# hyperlinks")). Same names/inputs/assertions as upstream `it(...)` blocks,
# renamed to snake_case test_ functions. All 17 upstream cases apply to this
# port unchanged — none skipped.


def test_wrap_underline_not_applied_before_styled_text():
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    url = "https://example.com/very/long/path/that/will/wrap"
    text = f"read this thread {underline_on}{url}{underline_off}"

    wrapped = wrap_text_with_ansi(text, 40)

    assert wrapped[0] == "read this thread"
    assert wrapped[1].startswith(underline_on)
    assert "https://" in wrapped[1]


def test_wrap_no_whitespace_before_underline_reset():
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    text = f"{underline_on}underlined text here {underline_off}more"

    wrapped = wrap_text_with_ansi(text, 18)

    assert f" {underline_off}" not in wrapped[0]


def test_wrap_underline_reset_does_not_bleed_into_padding():
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    url = "https://example.com/very/long/path/that/will/definitely/wrap"
    text = f"prefix {underline_on}{url}{underline_off} suffix"

    wrapped = wrap_text_with_ansi(text, 30)

    for line in wrapped[1:-1]:
        if underline_on in line:
            assert line.endswith(underline_off)
            assert not line.endswith("\x1b[0m")


def test_wrap_preserves_background_across_lines_without_full_reset():
    bg_blue = "\x1b[44m"
    reset = "\x1b[0m"
    text = f"{bg_blue}hello world this is blue background text{reset}"

    wrapped = wrap_text_with_ansi(text, 15)

    assert all(bg_blue in line for line in wrapped)
    assert all(not line.endswith("\x1b[0m") for line in wrapped[:-1])


def test_wrap_resets_underline_but_preserves_background():
    underline_on = "\x1b[4m"
    underline_off = "\x1b[24m"
    reset = "\x1b[0m"
    text = (
        f"\x1b[41mprefix {underline_on}UNDERLINED_CONTENT_THAT_WRAPS{underline_off} suffix{reset}"
    )

    wrapped = wrap_text_with_ansi(text, 20)

    for line in wrapped:
        assert "[41m" in line or ";41m" in line or "[41;" in line

    for line in wrapped[:-1]:
        has_underline_on = "[4m" in line or "[4;" in line or ";4m" in line
        if has_underline_on and underline_off not in line:
            assert line.endswith(underline_off)
            assert not line.endswith("\x1b[0m")


def test_wrap_plain_text():
    text = "hello world this is a test"
    wrapped = wrap_text_with_ansi(text, 10)

    assert len(wrapped) > 1
    assert all(visible_width(line) <= 10 for line in wrapped)


def test_wrap_breaks_cjk_runs_at_grapheme_boundaries_after_latin_text():
    text = "This is an example 中文汉字测试段落内容中文汉字测试段落内容."
    wrapped = wrap_text_with_ansi(text, 40)

    assert wrapped == ["This is an example 中文汉字测试段落内容", "中文汉字测试段落内容."]
    assert all(visible_width(line) <= 40 for line in wrapped)


def test_wrap_preserves_color_codes_when_wrapping_cjk_runs():
    red = "\x1b[31m"
    reset = "\x1b[0m"
    text = f"{red}This is an example 中文汉字测试段落内容中文汉字测试段落内容.{reset}"
    wrapped = wrap_text_with_ansi(text, 40)

    assert len(wrapped) == 2
    assert wrapped[0] == f"{red}This is an example 中文汉字测试段落内容"
    assert wrapped[1] == f"{red}中文汉字测试段落内容.{reset}"
    assert all(visible_width(line) <= 40 for line in wrapped)


def test_wrap_ignores_osc133_semantic_markers_bel_in_visible_width():
    text = "\x1b]133;A\x07hello\x1b]133;B\x07"
    assert visible_width(text) == 5


def test_wrap_ignores_osc_sequences_terminated_with_st_in_visible_width():
    text = "\x1b]133;A\x1b\\hello\x1b]133;B\x1b\\"
    assert visible_width(text) == 5


def test_wrap_treats_isolated_regional_indicators_as_width_2():
    assert visible_width("🇨") == 2
    assert visible_width("🇨🇳") == 2


def test_wrap_truncates_trailing_whitespace_that_exceeds_width():
    two_spaces_wrapped_to_width_1 = wrap_text_with_ansi("  ", 1)
    assert visible_width(two_spaces_wrapped_to_width_1[0]) <= 1


def test_wrap_preserves_color_codes_across_wraps():
    red = "\x1b[31m"
    reset = "\x1b[0m"
    text = f"{red}hello world this is red{reset}"

    wrapped = wrap_text_with_ansi(text, 10)

    for line in wrapped[1:]:
        assert line.startswith(red)
    for line in wrapped[:-1]:
        assert not line.endswith("\x1b[0m")


def test_wrap_osc8_reemits_open_at_start_of_continuation_lines():
    url = "https://example.com"
    input_ = f"\x1b]8;;{url}\x1b\\0123456789\x1b]8;;\x1b\\"
    lines = wrap_text_with_ansi(input_, 6)

    for line in lines:
        stripped = re.sub(r"\x1b\]8;;[^\x1b\x07]*\x1b\\", "", line)
        stripped = re.sub(r"\x1b\[[0-9;]*m", "", stripped)
        if stripped.strip():
            assert line.startswith(f"\x1b]8;;{url}\x1b\\") or f"\x1b]8;;{url}\x1b\\" in line


def test_wrap_osc8_closes_before_each_line_break():
    url = "https://example.com"
    input_ = f"\x1b]8;;{url}\x1b\\0123456789\x1b]8;;\x1b\\"
    lines = wrap_text_with_ansi(input_, 6)

    for line in lines[:-1]:
        if f"\x1b]8;;{url}\x1b\\" in line:
            assert line.endswith("\x1b]8;;\x1b\\")


def test_wrap_osc8_preserves_bel_terminators_for_oauth_style_hyperlinks():
    url = "https://example.com/oauth/" + "a" * 32
    input_ = f"\x1b]8;;{url}\x07{url}\x1b]8;;\x07"
    lines = wrap_text_with_ansi(input_, 20)

    assert len(lines) > 1
    for line in lines:
        assert f"\x1b]8;;{url}\x07" in line
        assert f"\x1b]8;;{url}\x1b\\" not in line
    for line in lines[:-1]:
        assert line.endswith("\x1b]8;;\x07")


def test_wrap_osc8_no_sequences_on_lines_outside_the_hyperlink():
    url = "https://example.com"
    input_ = f"before \x1b]8;;{url}\x1b\\link\x1b]8;;\x1b\\ after"
    lines = wrap_text_with_ansi(input_, 80)

    assert len(lines) == 1
    open_count = len(re.findall(r"\x1b\]8;;https:[^\x1b]+\x1b\\", lines[0]))
    close_count = len(re.findall(r"\x1b\]8;;\x1b\\", lines[0]))
    assert open_count == 1
    assert close_count == 1
