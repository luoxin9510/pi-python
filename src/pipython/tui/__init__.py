"""pipython interactive CLI. Only main() is public API."""

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def _tui_deps_available() -> bool:
    return all(
        importlib.util.find_spec(m) is not None
        for m in ("prompt_toolkit", "rich", "rapidfuzz", "pathspec")
    )


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(prog="pipython", description="pi-python interactive CLI")
    parser.add_argument(
        "--model",
        default=os.environ.get("PI_PYTHON_MODEL", "anthropic/claude-sonnet-5"),
        help="litellm model id",
    )
    parser.add_argument("--cwd", type=Path, default=Path("."), help="agent working directory")
    parser.add_argument(
        "--engine",
        choices=["legacy", "pi"],
        default="legacy",
        help="TUI engine: 'legacy' (prompt_toolkit/rich, default) or 'pi' (new diff-render engine)",
    )
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

    try:
        if args.engine == "pi":
            from .app import make_client
            from .app2 import run_app2

            # make_client() is app.py's existing PI_PYTHON_FAKE_SCRIPT ->
            # FakeClient wiring (test-only escape hatch, spec §7); reused
            # verbatim so the pi engine honors the same env var as legacy
            # instead of only ever taking run_app2's real-client default.
            asyncio.run(
                run_app2(
                    model=args.model,
                    cwd=args.cwd.resolve(),
                    client=make_client(args.model),
                )
            )
        else:
            from .app import run_app

            asyncio.run(run_app(model=args.model, cwd=args.cwd.resolve()))
    except KeyboardInterrupt:
        # SIGINT handler 只覆盖运行中的 turn，prompt_toolkit 只覆盖输入编辑；
        # 两者之间的窗口（比如 pre-prompt 的 file-list 刷新）冒出的
        # KeyboardInterrupt 会一路顶到这里——干净退出而不是甩 traceback（issue #6）。
        return 130
    return 0
