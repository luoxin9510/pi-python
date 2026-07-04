"""Grapheme/width/ANSI-aware text utilities — Python port of upstream pi's
``packages/tui/src/utils.ts`` (grapheme segmentation, ``visibleWidth``,
``wrapTextWithAnsi``, ``truncateToWidth``, ``applyBackgroundToLine``).

Naming is snake_case per Python convention; behaviour is ported faithfully
except where noted in the module docstring of individual functions (and in
the task-1 report's Deviations section).

Grapheme segmentation uses the ``regex`` module's ``\\X`` (extended grapheme
cluster), matching upstream's ``Intl.Segmenter(granularity: "grapheme")``.

``regex`` does not support Unicode's ``\\p{RGI_Emoji}`` property (used
upstream to detect "recommended for general interchange" emoji sequences),
so ``_is_rgi_emoji`` approximates it with a code-point/unicodedata heuristic:
ZWJ sequences, skin-tone modifier sequences, keycap sequences, regional
indicator (flag) pairs, and single emoji-block code points with Unicode
category ``So``. The golden tests in ``tests/tui/engine/test_utils.py`` are
the arbiter for this approximation, not upstream's regex.
"""

import unicodedata

import regex
import wcwidth

__all__ = [
    "graphemes",
    "visible_width",
    "wrap_text_with_ansi",
    "truncate_to_width",
    "apply_background_to_line",
]

# --------------------------------------------------------------------------
# Classification regexes — ported verbatim from utils.ts:40-42, except
# RGI_Emoji (unsupported by the `regex` module; see _is_rgi_emoji below).
# --------------------------------------------------------------------------

_GRAPHEME_RE = regex.compile(r"\X")

_ZERO_WIDTH_RE = regex.compile(
    r"^(?:\p{Default_Ignorable_Code_Point}|\p{Control}|\p{Mark}|\p{Surrogate})+$",
    regex.V1,
)
_LEADING_NON_PRINTING_RE = regex.compile(
    r"^[\p{Default_Ignorable_Code_Point}\p{Control}\p{Format}\p{Mark}\p{Surrogate}]+",
    regex.V1,
)

_CJK_BREAK_RE = regex.compile(
    r"[\p{Script_Extensions=Han}\p{Script_Extensions=Hiragana}"
    r"\p{Script_Extensions=Katakana}\p{Script_Extensions=Hangul}"
    r"\p{Script_Extensions=Bopomofo}]",
    regex.V1,
)

_SGR_RE = regex.compile(r"\x1b\[([\d;]*)m")

_VS16 = "️"  # emoji presentation selector
_ZWJ = "‍"
_RESET = "\x1b[0m"


# --------------------------------------------------------------------------
# Grapheme segmentation
# --------------------------------------------------------------------------


def graphemes(s: str) -> list[str]:
    """Split ``s`` into extended grapheme clusters (regex ``\\X``)."""
    return _GRAPHEME_RE.findall(s)


# --------------------------------------------------------------------------
# ANSI escape sequence extraction — ported from utils.ts extractAnsiCode
# (CSI ``ESC [ ... m/G/K/H/J``, OSC ``ESC ] ... BEL|ST``, APC ``ESC _ ... BEL|ST``).
# --------------------------------------------------------------------------


def _extract_ansi_code(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text) or text[pos] != "\x1b":
        return None

    nxt = text[pos + 1] if pos + 1 < len(text) else None

    if nxt == "[":
        j = pos + 2
        while j < len(text) and text[j] not in "mGKHJ":
            j += 1
        if j < len(text):
            return text[pos : j + 1], j + 1 - pos
        return None

    if nxt in ("]", "_"):
        j = pos + 2
        while j < len(text):
            if text[j] == "\x07":
                return text[pos : j + 1], j + 1 - pos
            if text[j] == "\x1b" and j + 1 < len(text) and text[j + 1] == "\\":
                return text[pos : j + 2], j + 2 - pos
            j += 1
        return None

    return None


def _strip_ansi(text: str) -> str:
    result = []
    i = 0
    n = len(text)
    while i < n:
        ansi = _extract_ansi_code(text, i)
        if ansi is not None:
            i += ansi[1]
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


# --------------------------------------------------------------------------
# RGI-emoji approximation (spec §2 known constraint)
# --------------------------------------------------------------------------

# Broad "could be emoji" pre-filter, ported from couldBeEmoji (utils.ts:27-37).
_EMOJI_PREFILTER_RANGES = (
    (0x1F000, 0x1FBFF),  # Emoji and Pictograph
    (0x2300, 0x23FF),  # Misc technical
    (0x2600, 0x27BF),  # Misc symbols, dingbats
    (0x2B50, 0x2B55),  # Specific stars/circles
)

# Code-point table for the single-code-point RGI-emoji fallback below.
_EMOJI_BLOCK_RANGES = (
    (0x1F000, 0x1FFFF),
    (0x2300, 0x23FF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
)


def _could_be_emoji(cluster: str) -> bool:
    if not cluster:
        return False
    cp = ord(cluster[0])
    return (
        any(lo <= cp <= hi for lo, hi in _EMOJI_PREFILTER_RANGES)
        or _VS16 in cluster
        or len(cluster) > 2
    )


def _is_rgi_emoji(cluster: str) -> bool:
    """Approximate Unicode's RGI_Emoji property for a grapheme cluster.

    Not a faithful reproduction of emoji-sequences.txt/emoji-test.txt (not
    available offline); a code-point/unicodedata heuristic arbitrated by the
    golden tests, per spec §2's documented constraint.
    """
    if not cluster:
        return False
    if _VS16 in cluster:
        return True
    if _ZWJ in cluster:
        return True
    # Skin-tone (Fitzpatrick) modifier sequence: base + U+1F3FB..U+1F3FF.
    if len(cluster) > 1 and any(0x1F3FB <= ord(ch) <= 0x1F3FF for ch in cluster[1:]):
        return True
    # Regional indicator flag pair (e.g. "🇨🇳").
    if len(cluster) == 2 and all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in cluster):
        return True
    # Keycap sequence: e.g. "1️⃣".
    if cluster.endswith("⃣"):
        return True
    if len(cluster) == 1:
        cp = ord(cluster)
        if any(lo <= cp <= hi for lo, hi in _EMOJI_BLOCK_RANGES):
            return unicodedata.category(cluster) == "So"
    return False


# --------------------------------------------------------------------------
# visible_width
# --------------------------------------------------------------------------


def _grapheme_width(cluster: str) -> int:
    if cluster == "\t":
        return 3

    if _ZERO_WIDTH_RE.match(cluster):
        return 0

    if _could_be_emoji(cluster) and _is_rgi_emoji(cluster):
        return 2

    base = _LEADING_NON_PRINTING_RE.sub("", cluster)
    if not base:
        return 0

    cp = ord(base[0])
    # Regional indicator symbols are often rendered full-width even in
    # isolation (e.g. mid-stream); keep width conservative (ported from
    # utils.ts:189-194).
    if 0x1F1E6 <= cp <= 0x1F1FF:
        return 2

    width = wcwidth.wcswidth(base)
    return width if width > 0 else 0


def visible_width(s: str) -> int:
    """Visible terminal-column width of ``s``.

    ANSI/OSC/APC escape sequences are zero-width; tabs count as 3 columns;
    other characters use ``wcwidth`` per grapheme cluster, with RGI-emoji
    clusters forced to width 2 (ported from utils.ts visibleWidth/
    graphemeWidth).
    """
    if not s:
        return 0

    if s.isascii() and s.isprintable():
        return len(s)

    clean = s.replace("\t", "   ") if "\t" in s else s
    if "\x1b" in clean:
        clean = _strip_ansi(clean)

    return sum(_grapheme_width(cluster) for cluster in _GRAPHEME_RE.findall(clean))


# --------------------------------------------------------------------------
# OSC 8 hyperlink tracking + ANSI SGR state tracker — ported from
# utils.ts AnsiCodeTracker (lines 330-589) so styling/hyperlinks survive
# wrap line breaks.
# --------------------------------------------------------------------------


class _ActiveHyperlink:
    __slots__ = ("params", "url", "terminator")

    def __init__(self, params: str, url: str, terminator: str) -> None:
        self.params = params
        self.url = url
        self.terminator = terminator  # "\x07" or "\x1b\\"


def _parse_osc8_hyperlink(ansi_code: str) -> tuple[bool, "_ActiveHyperlink | None"]:
    """Return ``(is_osc8, hyperlink)``.

    ``(False, None)``: not an OSC 8 code at all.
    ``(True, None)``: OSC 8 *close* (empty url).
    ``(True, hyperlink)``: OSC 8 *open*.
    """
    if not ansi_code.startswith("\x1b]8;"):
        return False, None

    terminator = "\x07" if ansi_code.endswith("\x07") else "\x1b\\"
    body = ansi_code[4 : -1 if terminator == "\x07" else -2]
    sep = body.find(";")
    if sep == -1:
        return False, None

    params = body[:sep]
    url = body[sep + 1 :]
    if not url:
        return True, None
    return True, _ActiveHyperlink(params, url, terminator)


def _format_osc8_hyperlink(h: _ActiveHyperlink) -> str:
    return f"\x1b]8;{h.params};{h.url}{h.terminator}"


def _format_osc8_close(terminator: str) -> str:
    return f"\x1b]8;;{terminator}"


class _AnsiCodeTracker:
    """Tracks active SGR attributes + OSC 8 hyperlink state across wraps."""

    def __init__(self) -> None:
        self.bold = False
        self.dim = False
        self.italic = False
        self.underline = False
        self.blink = False
        self.inverse = False
        self.hidden = False
        self.strikethrough = False
        self.fg_color: str | None = None
        self.bg_color: str | None = None
        self.active_hyperlink: _ActiveHyperlink | None = None

    def _reset(self) -> None:
        self.bold = False
        self.dim = False
        self.italic = False
        self.underline = False
        self.blink = False
        self.inverse = False
        self.hidden = False
        self.strikethrough = False
        self.fg_color = None
        self.bg_color = None
        # SGR reset does not affect OSC 8 hyperlink state.

    def process(self, ansi_code: str) -> None:
        is_osc8, hyperlink = _parse_osc8_hyperlink(ansi_code)
        if is_osc8:
            self.active_hyperlink = hyperlink
            return

        if not ansi_code.endswith("m"):
            return

        match = _SGR_RE.match(ansi_code)
        if not match:
            return

        params = match.group(1)
        if params in ("", "0"):
            self._reset()
            return

        parts = params.split(";")
        i = 0
        while i < len(parts):
            try:
                code = int(parts[i])
            except ValueError:
                i += 1
                continue

            if code in (38, 48):
                if i + 2 < len(parts) and parts[i + 1] == "5" and parts[i + 2] != "":
                    color_code = f"{parts[i]};{parts[i + 1]};{parts[i + 2]}"
                    if code == 38:
                        self.fg_color = color_code
                    else:
                        self.bg_color = color_code
                    i += 3
                    continue
                if i + 4 < len(parts) and parts[i + 1] == "2" and parts[i + 4] != "":
                    color_code = ";".join(parts[i : i + 5])
                    if code == 38:
                        self.fg_color = color_code
                    else:
                        self.bg_color = color_code
                    i += 5
                    continue

            if code == 0:
                self._reset()
            elif code == 1:
                self.bold = True
            elif code == 2:
                self.dim = True
            elif code == 3:
                self.italic = True
            elif code == 4:
                self.underline = True
            elif code == 5:
                self.blink = True
            elif code == 7:
                self.inverse = True
            elif code == 8:
                self.hidden = True
            elif code == 9:
                self.strikethrough = True
            elif code == 21:
                self.bold = False
            elif code == 22:
                self.bold = False
                self.dim = False
            elif code == 23:
                self.italic = False
            elif code == 24:
                self.underline = False
            elif code == 25:
                self.blink = False
            elif code == 27:
                self.inverse = False
            elif code == 28:
                self.hidden = False
            elif code == 29:
                self.strikethrough = False
            elif code == 39:
                self.fg_color = None
            elif code == 49:
                self.bg_color = None
            elif (30 <= code <= 37) or (90 <= code <= 97):
                self.fg_color = str(code)
            elif (40 <= code <= 47) or (100 <= code <= 107):
                self.bg_color = str(code)
            i += 1

    def get_active_codes(self) -> str:
        codes: list[str] = []
        if self.bold:
            codes.append("1")
        if self.dim:
            codes.append("2")
        if self.italic:
            codes.append("3")
        if self.underline:
            codes.append("4")
        if self.blink:
            codes.append("5")
        if self.inverse:
            codes.append("7")
        if self.hidden:
            codes.append("8")
        if self.strikethrough:
            codes.append("9")
        if self.fg_color:
            codes.append(self.fg_color)
        if self.bg_color:
            codes.append(self.bg_color)

        result = f"\x1b[{';'.join(codes)}m" if codes else ""
        if self.active_hyperlink:
            result += _format_osc8_hyperlink(self.active_hyperlink)
        return result

    def get_line_end_reset(self) -> str:
        """Codes to close at a line break: underline only (preserves
        background across the padding), plus re-closing an open hyperlink
        (re-opened at the next line's start via get_active_codes())."""
        result = ""
        if self.underline:
            result += "\x1b[24m"
        if self.active_hyperlink:
            result += _format_osc8_close(self.active_hyperlink.terminator)
        return result


def _update_tracker_from_text(text: str, tracker: _AnsiCodeTracker) -> None:
    i = 0
    n = len(text)
    while i < n:
        ansi = _extract_ansi_code(text, i)
        if ansi is not None:
            tracker.process(ansi[0])
            i += ansi[1]
        else:
            i += 1


# --------------------------------------------------------------------------
# wrap_text_with_ansi
# --------------------------------------------------------------------------


def _split_into_tokens_with_ansi(text: str) -> list[str]:
    """Split text into words/spaces/CJK-single-grapheme tokens, keeping
    ANSI codes attached to the following visible content."""
    tokens: list[str] = []
    current = ""
    pending_ansi = ""
    current_kind: str | None = None  # "space" | "word" | None
    i = 0
    n = len(text)

    def flush_current() -> None:
        nonlocal current, current_kind
        if current:
            tokens.append(current)
            current = ""
            current_kind = None

    while i < n:
        ansi = _extract_ansi_code(text, i)
        if ansi is not None:
            pending_ansi += ansi[0]
            i += ansi[1]
            continue

        end = i
        while end < n and _extract_ansi_code(text, end) is None:
            end += 1

        for cluster in _GRAPHEME_RE.findall(text[i:end]):
            segment_is_space = cluster == " "
            if not segment_is_space and _CJK_BREAK_RE.search(cluster):
                flush_current()
                tokens.append(pending_ansi + cluster)
                pending_ansi = ""
                continue

            segment_kind = "space" if segment_is_space else "word"
            if current and current_kind != segment_kind:
                flush_current()

            if pending_ansi:
                current += pending_ansi
                pending_ansi = ""

            current_kind = segment_kind
            current += cluster

        i = end

    if pending_ansi:
        if current:
            current += pending_ansi
        elif tokens:
            tokens[-1] += pending_ansi
        else:
            current = pending_ansi

    if current:
        tokens.append(current)

    return tokens


def _break_long_word(word: str, width: int, tracker: _AnsiCodeTracker) -> list[str]:
    lines: list[str] = []
    current_line = tracker.get_active_codes()
    current_width = 0

    segments: list[tuple[str, str]] = []
    i = 0
    n = len(word)
    while i < n:
        ansi = _extract_ansi_code(word, i)
        if ansi is not None:
            segments.append(("ansi", ansi[0]))
            i += ansi[1]
            continue
        end = i
        while end < n and _extract_ansi_code(word, end) is None:
            end += 1
        for cluster in _GRAPHEME_RE.findall(word[i:end]):
            segments.append(("grapheme", cluster))
        i = end

    for kind, value in segments:
        if kind == "ansi":
            current_line += value
            tracker.process(value)
            continue

        if not value:
            continue

        g_width = visible_width(value)
        if current_width + g_width > width:
            line_end_reset = tracker.get_line_end_reset()
            if line_end_reset:
                current_line += line_end_reset
            lines.append(current_line)
            current_line = tracker.get_active_codes()
            current_width = 0

        current_line += value
        current_width += g_width

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


def _wrap_single_line(line: str, width: int) -> list[str]:
    if not line:
        return [""]

    if visible_width(line) <= width:
        return [line]

    wrapped: list[str] = []
    tracker = _AnsiCodeTracker()
    tokens = _split_into_tokens_with_ansi(line)

    current_line = ""
    current_visible_length = 0

    for token in tokens:
        token_visible_length = visible_width(token)
        is_whitespace = token.strip() == ""

        if token_visible_length > width and not is_whitespace:
            if current_line:
                line_end_reset = tracker.get_line_end_reset()
                if line_end_reset:
                    current_line += line_end_reset
                wrapped.append(current_line)
                current_line = ""
                current_visible_length = 0

            broken = _break_long_word(token, width, tracker)
            wrapped.extend(broken[:-1])
            current_line = broken[-1]
            current_visible_length = visible_width(current_line)
            continue

        total_needed = current_visible_length + token_visible_length

        if total_needed > width and current_visible_length > 0:
            line_to_wrap = current_line.rstrip()
            line_end_reset = tracker.get_line_end_reset()
            if line_end_reset:
                line_to_wrap += line_end_reset
            wrapped.append(line_to_wrap)
            if is_whitespace:
                current_line = tracker.get_active_codes()
                current_visible_length = 0
            else:
                current_line = tracker.get_active_codes() + token
                current_visible_length = token_visible_length
        else:
            current_line += token
            current_visible_length += token_visible_length

        _update_tracker_from_text(token, tracker)

    if current_line:
        wrapped.append(current_line)

    return [ln.rstrip() for ln in wrapped] if wrapped else [""]


def wrap_text_with_ansi(text: str, width: int) -> list[str]:
    """Word-wrap ``text`` to ``width`` visible columns, ANSI-aware.

    Only wraps — no padding, no background fill. Active SGR styling and
    OSC 8 hyperlinks are preserved/re-opened across wrapped lines and
    literal newlines (ported from utils.ts wrapTextWithAnsi).
    """
    if not text:
        return [""]

    input_lines = text.split("\n")
    result: list[str] = []
    tracker = _AnsiCodeTracker()

    for input_line in input_lines:
        prefix = tracker.get_active_codes() if result else ""
        result.extend(_wrap_single_line(prefix + input_line, width))
        _update_tracker_from_text(input_line, tracker)

    return result if result else [""]


# --------------------------------------------------------------------------
# truncate_to_width
# --------------------------------------------------------------------------


def _truncate_fragment_to_width(text: str, max_width: int) -> tuple[str, int]:
    """ANSI/tab-aware prefix of ``text`` that fits in ``max_width`` columns.

    Returns ``(text, width)``. Ported from utils.ts truncateFragmentToWidth.
    """
    if max_width <= 0 or not text:
        return "", 0

    if text.isascii() and text.isprintable():
        clipped = text[:max_width]
        return clipped, len(clipped)

    has_ansi = "\x1b" in text
    has_tabs = "\t" in text

    if not has_ansi and not has_tabs:
        result = ""
        width = 0
        for cluster in _GRAPHEME_RE.findall(text):
            w = _grapheme_width(cluster)
            if width + w > max_width:
                break
            result += cluster
            width += w
        return result, width

    result = ""
    width = 0
    i = 0
    n = len(text)
    pending_ansi = ""

    while i < n:
        ansi = _extract_ansi_code(text, i)
        if ansi is not None:
            pending_ansi += ansi[0]
            i += ansi[1]
            continue

        if text[i] == "\t":
            if width + 3 > max_width:
                break
            if pending_ansi:
                result += pending_ansi
                pending_ansi = ""
            result += "\t"
            width += 3
            i += 1
            continue

        end = i
        while end < n and text[end] != "\t":
            if _extract_ansi_code(text, end) is not None:
                break
            end += 1

        overflowed = False
        for cluster in _GRAPHEME_RE.findall(text[i:end]):
            w = _grapheme_width(cluster)
            if width + w > max_width:
                overflowed = True
                break
            if pending_ansi:
                result += pending_ansi
                pending_ansi = ""
            result += cluster
            width += w
        if overflowed:
            break
        i = end

    return result, width


def truncate_to_width(s: str, width: int, ellipsis: str = "…") -> str:
    """Truncate ``s`` to ``width`` visible columns, adding ``ellipsis`` if
    truncated. ANSI escape codes don't count toward width.

    Deviation from upstream truncateToWidth: upstream unconditionally wraps
    the ellipsis in ``\\x1b[0m`` resets (even for plain, unstyled text) to
    avoid style bleed. This port only adds that reset when the input
    actually contains ANSI codes, so plain-text truncation (the golden
    tests' only case) stays clean — see task-1 report Deviations.
    """
    if width <= 0 or not s:
        return ""

    if visible_width(s) <= width:
        return s

    has_ansi = "\x1b" in s
    ellipsis_width = visible_width(ellipsis)

    if ellipsis_width >= width:
        clipped_text, clipped_width = _truncate_fragment_to_width(ellipsis, width)
        if clipped_width == 0:
            return ""
        return f"{clipped_text}{_RESET}" if has_ansi else clipped_text

    target_width = width - ellipsis_width
    kept, _kept_width = _truncate_fragment_to_width(s, target_width)
    if has_ansi:
        return f"{kept}{_RESET}{ellipsis}{_RESET}"
    return f"{kept}{ellipsis}"


# --------------------------------------------------------------------------
# apply_background_to_line
# --------------------------------------------------------------------------


def apply_background_to_line(line: str, bg: str, width: int) -> str:
    """Pad ``line`` with spaces to ``width`` visible columns and wrap the
    whole thing (content + padding) in the ``bg`` ANSI background code,
    resetting at the end (ported from utils.ts applyBackgroundToLine; here
    ``bg`` is a literal ANSI SGR code string rather than a callback)."""
    visible_len = visible_width(line)
    padding = " " * max(0, width - visible_len)
    return f"{bg}{line}{padding}{_RESET}"
