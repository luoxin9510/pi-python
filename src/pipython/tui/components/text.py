"""Text component — Python port of upstream pi's
``packages/tui/src/components/text.ts`` (106 lines), narrowed to task-9
brief's simplified interface: ``Text(content, style="")`` — no
paddingX/paddingY/customBgFn constructor params. ``set_content()`` is
upstream's ``setText()``. Wrapping itself is not reimplemented here — it is
delegated entirely to Task 1's ``wrap_text_with_ansi`` (utils.ts's own
``wrapTextWithAnsi``, ported verbatim in ``engine/utils.py``).

Deviations from upstream text.ts:

1. No ``paddingX``/``paddingY``/``customBgFn`` constructor params (upstream
   defaults: ``paddingX=1, paddingY=1``). Task-9 brief's Produces list
   (``Text(content: str, style: str = "")``) is the authority for this
   port's constructor shape, not upstream's — that whole axis exists
   upstream to let ``Text`` fill a rectangular, possibly-backgrounded region
   inside a ``Box``; this port's ``Box`` (task-9's own, see ``box.py``)
   handles padding/border itself instead.
2. No per-line fill-to-width padding. Upstream unconditionally pads every
   wrapped line with trailing spaces out to the full render width
   (text.ts:82-86), even with no ``customBgFn`` set, because ``Text``'s
   real job upstream is filling a rectangular region. Without any
   background concept in this port, that trailing whitespace serves no
   purpose and would break exact-output assertions the RED tests make
   (``Text("hello").render(20) == ["hello"]`` — no trailing padding).
3. No caching (``cachedText``/``cachedWidth``/``cachedLines`` memoization,
   text.ts:14-16, 46-49). A pure perf optimization orthogonal to render
   *semantics*; not in the task-9 brief's Produces list and no RED test
   exercises cache-hit behavior.
4. ``style`` (a raw SGR/ANSI escape prefix string) is this port's own
   addition per the task-9 brief — upstream has no such parameter, only the
   ``customBgFn`` callback. It is applied by embedding it directly in the
   text fed to ``wrap_text_with_ansi`` plus a trailing reset, so the
   existing ``_AnsiCodeTracker`` machinery inside that function (already
   exercised by Task 1's own tests) re-opens/closes it across wrap
   boundaries — no bespoke styling logic duplicated here.
"""

from __future__ import annotations

from ..engine.utils import wrap_text_with_ansi

__all__ = ["Text"]

_RESET = "\x1b[0m"


class Text:
    """tui.ts ``Component``-compatible: multi-line word-wrapped text, no
    padding/background (see module docstring deviations 1-2)."""

    def __init__(self, content: str = "", style: str = "") -> None:
        self.content = content
        self.style = style

    def set_content(self, content: str) -> None:
        """Upstream ``setText()`` (text.ts:25-30, minus cache invalidation —
        this port doesn't cache, see module docstring deviation 3)."""
        self.content = content

    def invalidate(self) -> None:
        """No cached render state to invalidate (module docstring deviation 3)."""

    def render(self, width: int) -> list[str]:
        """text.ts:45-105's core, minus the no-op branches this port drops
        (see module docstring). Empty/whitespace-only content renders no
        lines at all (text.ts:52-58's early return)."""
        if not self.content or self.content.strip() == "":
            return []

        normalized = self.content.replace("\t", "   ")
        if self.style:
            normalized = f"{self.style}{normalized}{_RESET}"

        return wrap_text_with_ansi(normalized, max(1, width))
