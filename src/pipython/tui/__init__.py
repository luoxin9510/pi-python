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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _tui_deps_available():
        print(
            'TUI dependencies missing — install with: pip install "pi-python[tui]"',
            file=sys.stderr,
        )
        return 1
    import asyncio

    from .app import run_app

    asyncio.run(run_app(model=args.model, cwd=args.cwd.resolve()))
    return 0
