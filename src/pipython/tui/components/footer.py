"""Bottom status bar (usable subset), ported from pi's footer.ts.

Two independent lines (pwd, stats), each dim-styled and truncated on its own —
matching upstream footer.ts structure. Fields needing SDK data pi-python does
not yet expose (cache tokens, context %, OAuth sub, session name, auto-compact)
are omitted per spec §1/§6.
"""

import math
import os
from pathlib import Path

from pipython.tui.engine.utils import truncate_to_width

# PHASE-4 REVISIT (theme port): hardcoded truecolor. Upstream theme.ts fgAnsi()
# has a 256-color fallback via getCapabilities(); source from the theme layer
# when terminal-capability detection is ported. dark.json dim -> dimGray #666666.
_DIM = "\x1b[38;2;102;102;102m"
_FG_RESET = "\x1b[39m"


def _dim(text: str) -> str:
    return f"{_DIM}{text}{_FG_RESET}"


def _round_half_up(x: float) -> int:
    # JS Math.round rounds .5 UP; Python round() is banker's rounding. Match JS.
    return math.floor(x + 0.5)


def format_tokens(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 10000:
        return f"{count / 1000:.1f}k"
    if count < 1_000_000:
        return f"{_round_half_up(count / 1000)}k"
    if count < 10_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{_round_half_up(count / 1_000_000)}M"


def format_cwd(cwd: str, home: str | None) -> str:
    if not home:
        return cwd
    # R1: normpath+abspath, NOT resolve() — do not follow symlinks (upstream
    # path.resolve() doesn't either; on macOS /tmp→/private/tmp would otherwise
    # flip an in-HOME path to out-of-HOME). POSIX only, so str(rel) is posix.
    resolved_cwd = Path(os.path.normpath(os.path.abspath(cwd)))
    resolved_home = Path(os.path.normpath(os.path.abspath(home)))
    try:
        rel = resolved_cwd.relative_to(resolved_home)
    except ValueError:
        return cwd
    return "~" if str(rel) == "." else f"~/{rel}"


class Footer:
    def __init__(self, app_state, git):
        self._app = app_state
        self._git = git

    def invalidate(self) -> None:
        pass

    def render(self, width: int) -> list[str]:
        session = self._app.session  # re-fetch: /clear swaps the session object

        # line 1: pwd (~ abbreviation) + git branch
        pwd = format_cwd(str(session.agent.cwd), os.environ.get("HOME"))
        branch = self._git.current_branch
        if branch:
            pwd = f"{pwd} ({branch})"
        line1 = truncate_to_width(_dim(pwd), width, _dim("..."))

        # line 2: token stats + cost + model, accumulated over all assistant usage
        total_in = total_out = 0
        total_cost = 0.0
        for e in session.store.entries:
            if getattr(e, "type", None) != "message":
                continue
            msg = e.message
            if msg.get("role") != "assistant":
                continue
            usage = msg.get("usage") or {}
            total_in += usage.get("inputTokens") or 0
            total_out += usage.get("outputTokens") or 0
            c = usage.get("cost")
            if c:
                total_cost += c

        parts: list[str] = []
        if total_in:
            parts.append(f"↑{format_tokens(total_in)}")
        if total_out:
            parts.append(f"↓{format_tokens(total_out)}")
        if total_cost > 0:
            parts.append(f"${total_cost:.3f}")
        parts.append(session.model)
        line2 = truncate_to_width(_dim(" ".join(parts)), width, _dim("..."))

        return [line1, line2]
