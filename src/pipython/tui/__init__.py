"""pipython interactive CLI. Only main() is public API."""

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def _tui_deps_available() -> bool:
    # Task 18: prompt_toolkit/rich/rapidfuzz dropped from pyproject entirely
    # (the legacy engine that needed them is deleted) — the remaining tui
    # extra's runtime deps are pathspec (completers.py), markdown-it-py
    # (components/markdown.py, imported as markdown_it), linkify-it-py
    # (markdown_it's linkify option, imported as linkify_it), wcwidth and
    # regex (engine/utils.py, components/editor.py).
    return all(
        importlib.util.find_spec(m) is not None
        for m in ("pathspec", "markdown_it", "linkify_it", "wcwidth", "regex")
    )


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(prog="pipython", description="pi-python interactive CLI")
    parser.add_argument(
        "--model",
        default=os.environ.get("PI_PYTHON_MODEL", "anthropic/claude-sonnet-5"),
        help="litellm model id",
    )
    parser.add_argument("--cwd", type=Path, default=Path("."), help="agent working directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        # loop.add_signal_handler（app.py 的 SIGINT 处理）在 Windows 上
        # NotImplementedError；给一行干净提示而不是一路跑到那里才崩（issue #5）。
        print(
            "pipython's TUI is POSIX-only (macOS/Linux); Windows is not supported", file=sys.stderr
        )
        return 1
    args = _parse_args(argv)
    if not _tui_deps_available():
        print(
            'TUI dependencies missing — install with: pip install "pi-python[tui]"',
            file=sys.stderr,
        )
        return 1
    import asyncio

    # Task 18: the pi-tui engine (formerly app2.py, ``--engine=pi``) is now
    # the only TUI — the legacy prompt_toolkit/rich engine and the
    # ``--engine`` flag selecting between them are both gone.
    from .app import make_client, run_app

    try:
        asyncio.run(
            run_app(
                model=args.model,
                cwd=args.cwd.resolve(),
                # make_client() is app.py's PI_PYTHON_FAKE_SCRIPT -> FakeClient
                # wiring (test-only escape hatch, spec §7).
                client=make_client(args.model),
            )
        )
    except KeyboardInterrupt:
        # SIGINT handler 只覆盖运行中的 turn；两者之间的窗口（比如 pre-prompt 的
        # file-list 刷新）冒出的 KeyboardInterrupt 会一路顶到这里——干净退出而不
        # 是甩 traceback（issue #6）。
        return 130
    return 0
