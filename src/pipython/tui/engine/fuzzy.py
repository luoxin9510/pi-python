"""Fuzzy matching — Python port of upstream pi's ``packages/tui/src/fuzzy.ts``
(137 lines).

Matches if all query characters appear in ``candidate``, case-insensitively,
in order (not necessarily consecutive). **Lower score = better match**
(matches upstream's convention exactly — this is not an inverted/normalized
"higher is better" score).

Interface (binding, per task-5 brief):

- ``fuzzy_match(query, candidate) -> int | None`` — upstream's ``fuzzyMatch``
  returns ``{ matches: boolean, score: number }``; this port collapses that
  to ``None`` for ``matches: false`` and ``round(score)`` for
  ``matches: true`` (upstream's ``score`` arithmetic includes a ``i * 0.1``
  fractional term — brief's ``int`` return type rounds it, which does not
  change any of upstream's relative orderings since that term is always
  dominated by the integer bonuses/penalties).
- ``fuzzy_filter(query, items, get_text=None) -> list`` — upstream's
  ``fuzzyFilter<T>(items, query, getText)`` reordered to ``(query, items,
  get_text=...)`` per brief's Produces signature; ``get_text`` defaults to
  the identity function for plain string lists (all upstream string-list
  test cases), matching the RED suite's calls without a ``get_text=``
  argument.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import TypeVar

__all__ = ["fuzzy_match", "fuzzy_filter"]

T = TypeVar("T")

# fuzzy.ts:32 `/[\s\-_./:]/` — characters after which a match counts as
# landing "at a word boundary" (in addition to i === 0).
_BOUNDARY_RE = re.compile(r"[\s\-_./:]")

# fuzzy.ts:75-76 alpha<->digit swap patterns.
_ALPHA_THEN_DIGITS_RE = re.compile(r"^(?P<letters>[a-z]+)(?P<digits>[0-9]+)$")
_DIGITS_THEN_ALPHA_RE = re.compile(r"^(?P<digits>[0-9]+)(?P<letters>[a-z]+)$")

# fuzzyFilter's query tokenizer (fuzzy.ts:104-107): split on runs of
# whitespace or "/".
_TOKEN_SPLIT_RE = re.compile(r"[\s/]+")


def _match_query(normalized_query: str, text_lower: str) -> tuple[bool, float]:
    """fuzzy.ts:16-68 ``matchQuery`` (the closure inside ``fuzzyMatch``)."""
    if len(normalized_query) == 0:
        return True, 0.0

    if len(normalized_query) > len(text_lower):
        return False, 0.0

    query_index = 0
    score = 0.0
    last_match_index = -1
    consecutive_matches = 0

    for i, ch in enumerate(text_lower):
        if query_index >= len(normalized_query):
            break
        if ch != normalized_query[query_index]:
            continue

        is_word_boundary = i == 0 or bool(_BOUNDARY_RE.match(text_lower[i - 1]))

        if last_match_index == i - 1:
            consecutive_matches += 1
            score -= consecutive_matches * 5
        else:
            consecutive_matches = 0
            if last_match_index >= 0:
                score += (i - last_match_index - 1) * 2

        if is_word_boundary:
            score -= 10

        score += i * 0.1

        last_match_index = i
        query_index += 1

    if query_index < len(normalized_query):
        return False, 0.0

    if normalized_query == text_lower:
        score -= 100

    return True, score


def fuzzy_match(query: str, candidate: str) -> int | None:
    """Score ``query`` fuzzily against ``candidate``. ``None`` means no
    match; otherwise lower is better (fuzzy.ts:12-93 ``fuzzyMatch``)."""
    query_lower = query.lower()
    text_lower = candidate.lower()

    matched, score = _match_query(query_lower, text_lower)
    if matched:
        return round(score)

    alpha_then_digits = _ALPHA_THEN_DIGITS_RE.match(query_lower)
    digits_then_alpha = _DIGITS_THEN_ALPHA_RE.match(query_lower)
    if alpha_then_digits:
        swapped_query = alpha_then_digits.group("digits") + alpha_then_digits.group("letters")
    elif digits_then_alpha:
        swapped_query = digits_then_alpha.group("letters") + digits_then_alpha.group("digits")
    else:
        swapped_query = ""

    if not swapped_query:
        return None

    swapped_matched, swapped_score = _match_query(swapped_query, text_lower)
    if not swapped_matched:
        return None

    return round(swapped_score + 5)


def fuzzy_filter(
    query: str,
    items: Iterable[T],
    get_text: Callable[[T], str] | None = None,
) -> list[T]:
    """Filter and sort ``items`` by fuzzy match quality (best first).

    Supports whitespace- and slash-separated query tokens: every token must
    match (fuzzy.ts:95-137 ``fuzzyFilter``).
    """
    items_list = list(items)
    if not query.strip():
        return items_list

    tokens = [t for t in _TOKEN_SPLIT_RE.split(query.strip()) if t]
    if not tokens:
        return items_list

    text_of: Callable[[T], str] = get_text if get_text is not None else (lambda x: x)  # type: ignore[assignment]

    scored: list[tuple[T, int]] = []
    for item in items_list:
        text = text_of(item)
        total_score = 0
        all_match = True
        for token in tokens:
            match_score = fuzzy_match(token, text)
            if match_score is None:
                all_match = False
                break
            total_score += match_score
        if all_match:
            scored.append((item, total_score))

    scored.sort(key=lambda pair: pair[1])
    return [item for item, _ in scored]
