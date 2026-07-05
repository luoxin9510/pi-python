from dataclasses import dataclass
from pathlib import Path

from pipython.tui.components.footer import Footer, format_cwd, format_tokens
from pipython.tui.engine.utils import visible_width

_DIM = "\x1b[38;2;102;102;102m"


# --- pure helpers ---


def test_format_tokens_bands():
    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1000) == "1.0k"
    assert format_tokens(9999) == "10.0k"
    assert format_tokens(10000) == "10k"
    assert format_tokens(999999) == "1000k"
    assert format_tokens(1_000_000) == "1.0M"
    assert format_tokens(9_999_999) == "10.0M"
    assert format_tokens(10_000_000) == "10M"
    # round-half-up (JS Math.round parity, not banker's rounding):
    assert format_tokens(10500) == "11k"  # 10.5 → 11, not 10
    assert format_tokens(10_500_000) == "11M"  # 10.5 → 11


def test_format_cwd_home(tmp_path: Path):
    home = str(tmp_path)
    assert format_cwd(home, home) == "~"
    assert format_cwd(str(tmp_path / "a" / "b"), home) == "~/a/b"


def test_format_cwd_outside_home(tmp_path: Path):
    assert format_cwd("/opt/x", str(tmp_path)) == "/opt/x"


def test_format_cwd_no_home():
    assert format_cwd("/opt/x", None) == "/opt/x"


# --- Footer render, driven by stubs ---


class _Store:
    def __init__(self, entries):
        self.entries = entries
        self.path = Path("/tmp/s.jsonl")


class _Agent:
    def __init__(self, cwd):
        self.cwd = Path(cwd)


class _Session:
    def __init__(self, cwd, model, entries):
        self.agent = _Agent(cwd)
        self.model = model
        self.store = _Store(entries)


@dataclass
class _AppState:
    session: _Session


class _Git:
    def __init__(self, branch):
        self.current_branch = branch


def _msg_entry(role, usage=None):
    # mimic MessageEntry: has .type == "message" and .message dict; camelCase usage
    class E:
        type = "message"

        def __init__(self):
            self.message = {"role": role}
            if usage is not None:
                self.message["usage"] = usage

    return E()


def _render(app, git, width=80):
    return Footer(app, git).render(width)


def test_footer_two_lines_pwd_and_stats(tmp_path: Path):
    home = str(tmp_path)
    import os

    os.environ["HOME"] = home
    sess = _Session(
        cwd=str(tmp_path / "proj"),
        model="deepseek/deepseek-chat",
        entries=[
            _msg_entry("assistant", {"inputTokens": 1200, "outputTokens": 340, "cost": 0.012}),
            _msg_entry("assistant", {"inputTokens": 800, "outputTokens": 60, "cost": 0.004}),
            _msg_entry("user"),
        ],
    )
    lines = _render(_AppState(sess), _Git("main"))
    assert len(lines) == 2
    # line 1: pwd with ~ and branch
    assert "~/proj (main)" in lines[0]
    assert lines[0].startswith(_DIM)
    # line 2: accumulated tokens ↑2.0k ↓400, cost $0.016, model
    assert "↑2.0k" in lines[1] and "↓400" in lines[1]
    assert "$0.016" in lines[1]
    assert "deepseek/deepseek-chat" in lines[1]


def test_footer_detached_shows_detached(tmp_path: Path):
    import os

    os.environ["HOME"] = str(tmp_path)
    sess = _Session(str(tmp_path), "m", [])
    lines = _render(_AppState(sess), _Git("detached"))
    assert "(detached)" in lines[0]


def test_footer_no_branch_omits_parens(tmp_path: Path):
    import os

    os.environ["HOME"] = str(tmp_path)
    sess = _Session(str(tmp_path / "p"), "m", [])
    lines = _render(_AppState(sess), _Git(None))
    assert "(" not in lines[0]


def test_footer_skips_none_cost(tmp_path: Path):
    import os

    os.environ["HOME"] = str(tmp_path)
    sess = _Session(
        str(tmp_path),
        "m",
        [_msg_entry("assistant", {"inputTokens": 10, "outputTokens": 5, "cost": None})],
    )
    lines = _render(_AppState(sess), _Git(None))
    assert "$" not in lines[1]


def test_footer_truncates_to_width(tmp_path: Path):
    import os

    os.environ["HOME"] = str(tmp_path)
    sess = _Session(str(tmp_path / ("deep/" * 40)), "m", [])
    lines = _render(_AppState(sess), _Git(None), width=20)
    assert all(visible_width(x) <= 20 for x in lines)
