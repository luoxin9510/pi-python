"""Word-boundary cursor navigation — Python port of upstream pi's
``packages/tui/src/word-navigation.ts`` (117 lines), Western semantics only.

Upstream uses ``Intl.Segmenter(undefined, { granularity: "word" })`` (UAX#29)
to split text into word-like / non-word-like segments, then walks one
segment at a time, additionally trimming *inside* a word-like segment down
to the position just past its last embedded ASCII-punctuation character
(``PUNCTUATION_REGEX``, utils.ts:800) — this handles cases where UAX#29
glues punctuation into a "word" (e.g. contractions).

Python has no ``Intl.Segmenter``. Per the phase-3 port convention, Western
text is approximated as maximal alphanumeric/underscore runs (this is
exactly what upstream's own segment-internal trimming degrades to once
ASCII punctuation is excluded from "word-like" — no upstream test exercises
embedded punctuation inside a word-like segment, e.g. no apostrophe/
contraction case in word-navigation.test.ts), so the extra trim step upstream
needs is not required here: a punctuation character is never inside a
"word" run in this port's classification, it always starts its own run.

**CJK ruling (spec §9, binding):** unlike upstream — which, lacking spaces
between CJK characters, has ``Intl.Segmenter`` emit *one word-like segment
per CJK character* (see word-navigation.test.ts "CJK mixed": each of the 4
characters in "你好世界" is its own segment, so ``findWordBackward`` walks it
one character at a time) — this port treats one *continuous run* of CJK
characters as a single word for navigation purposes. This is an explicit
simplification ruling, not a translation bug: verified by re-reading
word-navigation.test.ts's CJK case before implementing.

Interface (binding, per task-5 brief): ``word_left(text, pos) -> int``,
``word_right(text, pos) -> int`` — pure functions, no state.
"""

from __future__ import annotations

__all__ = ["word_left", "word_right"]

# Mirrors utils.ts:800 PUNCTUATION_REGEX exactly:
# /[(){}[\]<>.,;:'"!?+\-=*/\\|&%^$#@~`]/
_PUNCTUATION_CHARS = frozenset("(){}[]<>.,;:'\"!?+-=*/\\|&%^$#@~`")

# CJK ideograph / kana / hangul ranges treated as "one continuous run = one
# word" per spec §9. Deliberately broad (Han + extensions + Hiragana +
# Katakana + Hangul + CJK compatibility ideographs) since the ruling is about
# *simplifying* CJK handling, not about being a precise script classifier.
_CJK_RANGES = (
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x20000, 0x2A6DF),  # CJK Unified Ideographs Extension B
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _char_class(ch: str) -> str:
    """Classify one character into a run type: "space", "cjk", "punct", or
    "word" (letters, digits, underscore, and anything else not covered
    above)."""
    if ch.isspace():
        return "space"
    if _is_cjk(ch):
        return "cjk"
    if ch in _PUNCTUATION_CHARS:
        return "punct"
    return "word"


def word_left(text: str, pos: int) -> int:
    """Cursor position after moving one word backward from ``pos``.

    Skips trailing whitespace, then skips one contiguous same-class run
    (word/CJK-run/punctuation-run). Pure function — no mutation.
    """
    if pos <= 0:
        return 0

    i = pos
    while i > 0 and text[i - 1].isspace():
        i -= 1
    if i == 0:
        return 0

    run_class = _char_class(text[i - 1])
    while i > 0 and _char_class(text[i - 1]) == run_class:
        i -= 1
    return i


def word_right(text: str, pos: int) -> int:
    """Cursor position after moving one word forward from ``pos``.

    Skips leading whitespace, then skips one contiguous same-class run
    (word/CJK-run/punctuation-run). Pure function — no mutation.
    """
    n = len(text)
    if pos >= n:
        return n

    i = pos
    while i < n and text[i].isspace():
        i += 1
    if i >= n:
        return i

    run_class = _char_class(text[i])
    while i < n and _char_class(text[i]) == run_class:
        i += 1
    return i
