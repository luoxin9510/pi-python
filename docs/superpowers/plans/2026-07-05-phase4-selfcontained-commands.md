# pi-python 阶段四 自足斜杠命令（第一批）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 pipython TUI 加 5 条无 SDK 依赖的斜杠命令：`/hotkeys` `/new` `/copy` `/session` `/changelog`。

**Architecture:** 新增一个剪贴板 util 模块 + 5 个 handler 注册进现有 `commands.py` 的 `build_registry()`；handler 经既有 `CommandContext`(app+sink) 驱动，Sink 内部已触发重绘。规范 = `docs/superpowers/specs/2026-07-05-phase4-selfcontained-commands-design.md`（rev 2，下称 spec）。

**Tech Stack:** Python 3.11+ stdlib（subprocess/base64/os/shutil）；无新依赖。

## Global Constraints

- 新代码：`src/pipython/tui/components/clipboard.py`；handler 加进现有 `src/pipython/tui/commands.py`。
- 四道门：提交前 `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` 全绿；e2e 变动加 `uv run pytest tests/e2e/ -v`。**注意**：本计划贴的代码块按可读性手排，未必符合 ruff 排版；每个任务 Step 4 跑 check 门**之前先** `uv run ruff check --fix . && uv run ruff format .` 自动整形，再跑 `ruff format --check` 才会绿（纯排版差异，无语义变化）。
- **测试例外（已获维护者认可）**：clipboard util 的平台工具路径 monkeypatch subprocess——这是对 CLAUDE.md "不 mock 子进程" 的**明确例外**，因 headless CI 无 pbcopy/xclip/剪贴板设备。OSC 52 路径不涉子进程（纯 stdout 写），真实断言字节。其余一切真实执行。
- 模型分工：`[TEST]` 步骤派 haiku，实现派 sonnet；测试失败修复回 sonnet。
- commit 格式 `{feat,fix,test,docs}(scope): message`，scope=tui；消息尾加：
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
- git add 只加本任务文件。

## 现有接缝（已核实）

- `commands.py`：`Command(name, description, handler)`；`CommandContext`（`@dataclass`）：`app`（有 `app.session`、`app.make_session`）、`sink`。`Sink.emit_text(s, style="")` / `emit_lines(lines: list[str])`（内部已调 `tui.request_render`，handler 无需触发重绘）。`build_registry() -> dict[str, Command]`（现 6 命令）。已 `from pipython import ... current_path, entry_id, MessageEntry, SessionHeader`。
- handler 现有范式（照抄）：`async def _clear(ctx, _): ctx.app.session = await ctx.app.make_session(); ctx.sink.emit_text("new session")`。
- `session.store.entries`、`session.store.leaf_id`；`current_path(entries, leaf_id) -> list[Entry]`（root→leaf 正序，`_tree` 在用）。
- `MessageEntry.message` 是裸 dict；assistant 落盘形如 `{"role":"assistant","content":[{"type":"text","text":".."},{"type":"toolCall",..}],"usage":{"inputTokens":5,"outputTokens":3,"cost":0.001}}`（content 块 `type` 为 `"text"`/`"toolCall"`，usage camelCase）。
- `DEFAULT_EDITOR_BINDINGS`（`engine/keybindings.py`）：`dict[str, str | list[str]]`，**action 名 → key_id 或 key_id 列表**。含 `"app.tools.expand": "ctrl+o"`。
- `pipython.__version__`（`src/pipython/__init__.py`，现 `"0.1.0"`）。

---

### Task 1: clipboard util（平台探测 + OSC 52 兜底）

**Files:**
- Create: `src/pipython/tui/components/clipboard.py`
- Test: `tests/tui/components/test_clipboard.py`

**Interfaces:**
- Consumes: 无
- Produces: `copy_to_clipboard(text: str) -> str`——把 text 送到剪贴板，返回用的方法名（`"pbcopy"`/`"wl-copy"`/`"xclip"`/`"xsel"`/`"osc52"`，供调用方/测试断言）。**声明偏离**：spec rev-1 曾写 `-> None`，改为返回方法名纯为可测性（`/copy` 忽略返回值只捕异常，用法不变）；spec §3.3 已同步更正为 `-> str`。全部路径失败 raise `ClipboardError`。远程会话（`SSH_CONNECTION`/`SSH_TTY`/`MOSH_CONNECTION` 任一非空）或本地工具全不可用 → OSC 52（`\x1b]52;c;<base64(utf-8)>\x07` 写 `sys.stdout` 并 flush）。

- [ ] **Step 1: [TEST]** `tests/tui/components/test_clipboard.py`

```python
import base64
import subprocess
import sys

import pytest

from pipython.tui.components import clipboard
from pipython.tui.components.clipboard import ClipboardError, copy_to_clipboard


def _clear_remote(monkeypatch):
    for v in ("SSH_CONNECTION", "SSH_TTY", "MOSH_CONNECTION"):
        monkeypatch.delenv(v, raising=False)


def test_macos_uses_pbcopy(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["input"] = kw.get("input")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(clipboard, "_which", lambda name: name == "pbcopy")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    assert copy_to_clipboard("hello") == "pbcopy"
    assert calls["cmd"][0] == "pbcopy"
    assert calls["input"] == b"hello"


def test_linux_wayland_uses_wl_copy(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")  # _local_tools gates wl-copy on this
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "wl-copy")
    ran = {}
    monkeypatch.setattr(
        clipboard.subprocess, "run",
        lambda cmd, **kw: ran.setdefault("cmd", cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "wl-copy"
    assert ran["cmd"][0] == "wl-copy"


def test_linux_x11_uses_xclip_first(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)  # force X11 branch (no wl-copy)
    monkeypatch.setattr(clipboard, "_which", lambda name: name in ("xclip", "xsel"))
    monkeypatch.setattr(
        clipboard.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "xclip"


def test_linux_x11_falls_to_xsel_when_xclip_fails(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(clipboard, "_which", lambda name: name in ("xclip", "xsel"))

    def fake_run(cmd, **kw):
        if cmd[0] == "xclip":
            raise subprocess.CalledProcessError(1, cmd)  # xclip present but errors
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    assert copy_to_clipboard("x") == "xsel"


def test_remote_session_uses_osc52(monkeypatch, capsys):
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    # even if pbcopy exists, remote → OSC 52
    monkeypatch.setattr(clipboard, "_which", lambda name: True)
    assert copy_to_clipboard("hi") == "osc52"
    out = capsys.readouterr().out
    expected = "\x1b]52;c;" + base64.b64encode(b"hi").decode("ascii") + "\x07"
    assert out == expected


def test_no_tools_no_remote_falls_to_osc52(monkeypatch, capsys):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_which", lambda name: False)
    assert copy_to_clipboard("z") == "osc52"
    assert "\x1b]52;c;" in capsys.readouterr().out


def test_subprocess_failure_falls_to_osc52(monkeypatch, capsys):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "pbcopy")

    def boom(cmd, **kw):
        raise OSError("no")

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    assert copy_to_clipboard("z") == "osc52"
    assert "\x1b]52;c;" in capsys.readouterr().out


def test_all_paths_fail_raises_clipboard_error(monkeypatch):
    # No local tools + OSC 52 also unavailable (payload cap forced to 0) → raise.
    # Covers spec §3.3 "全部路径失败才 raise"; also makes the pytest/ClipboardError imports used.
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_which", lambda name: False)
    monkeypatch.setattr(clipboard, "_OSC52_MAX", 0)  # any non-empty payload exceeds → ClipboardError
    with pytest.raises(ClipboardError):
        copy_to_clipboard("x")
```

- [ ] **Step 2: 确认失败** — `uv run pytest tests/tui/components/test_clipboard.py -q` → FAIL (ImportError)
- [ ] **Step 3: [PORT] 实现** `src/pipython/tui/components/clipboard.py`（规范源 `utils/clipboard.ts`）

```python
"""Clipboard copy with platform tools + OSC 52 remote fallback (ported from pi's clipboard.ts).

Local tools: pbcopy (macOS), wl-copy (Wayland), xclip/xsel (X11). On a remote
session (SSH/mosh) or when no local tool works, falls back to the OSC 52 escape
sequence written to stdout, which the outer terminal forwards to the real
clipboard. Only raises if every path fails.
"""

import base64
import os
import shutil
import subprocess
import sys

_OSC52_MAX = 100_000  # cap payload: very large clipboards can hang some terminals over OSC 52


class ClipboardError(Exception):
    pass


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _is_remote() -> bool:
    return any(os.environ.get(v) for v in ("SSH_CONNECTION", "SSH_TTY", "MOSH_CONNECTION"))


def _osc52(text: str) -> str:
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(b64) > _OSC52_MAX:
        raise ClipboardError("Text too large for OSC 52 clipboard")
    sys.stdout.write(f"\x1b]52;c;{b64}\x07")
    sys.stdout.flush()
    return "osc52"


def _local_tools() -> list[tuple[str, list[str]]]:
    if sys.platform == "darwin":
        return [("pbcopy", ["pbcopy"])]
    if sys.platform.startswith("win"):
        return [("clip", ["clip"])]
    tools: list[tuple[str, list[str]]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        tools.append(("wl-copy", ["wl-copy"]))
    tools.append(("xclip", ["xclip", "-selection", "clipboard"]))
    tools.append(("xsel", ["xsel", "--clipboard", "--input"]))
    return tools


def copy_to_clipboard(text: str) -> str:
    if _is_remote():
        return _osc52(text)
    for name, cmd in _local_tools():
        if not _which(name):
            continue
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return name
        except (OSError, subprocess.SubprocessError):
            continue
    return _osc52(text)
```

- [ ] **Step 4: 跑测试 + 四道门** → 全 PASS
- [ ] **Step 5: Commit** `feat(tui): clipboard util — platform tools + OSC 52 remote fallback`

---

### Task 2: 5 命令 handler + key 格式化 + 注册 + e2e

**Files:**
- Modify: `src/pipython/tui/commands.py`（新增 handler + 注册；`_format_key` helper）
- Test: `tests/tui/test_commands_selfcontained.py`
- Modify: `tests/e2e/test_tui_tmux.py`（+1 e2e）
- Modify: `README.md`（斜杠命令表补 5 条）

**Interfaces:**
- Consumes: Task 1 `copy_to_clipboard`/`ClipboardError`；`current_path`/`entry_id`/`MessageEntry`（commands.py 已导入 current_path/MessageEntry）；`DEFAULT_EDITOR_BINDINGS`；`pipython.__version__`。
- Produces: 5 个 handler（`_hotkeys`/`_new`/`_copy`/`_session`/`_changelog`）注册进 `build_registry`；`_format_key(key_id: str) -> str`。

- [ ] **Step 1: [TEST]** `tests/tui/test_commands_selfcontained.py`

> 关键：**不造 duck-typed 假 app/session**（`CommandContext.app` 标注为具体类 `AppState`，喂 duck-typed 对象会 pyright 报 `reportArgumentType` 挂四道门）。照 `tests/tui/test_commands.py` 的既有约定，用**真实 `AppState` + `create_agent_session` + `FakeClient`** 构造 session，真实 `store.append` 手工铺 entry（真写 tmp JSONL，非 mock）。分支感知测试构造「物理最后一条 assistant 离开当前路径」的场景——若实现误用 `store.entries` 物理序而非 `current_path`，这些测试会失败。

```python
from pipython import (
    AgentSessionConfig,
    MessageEntry,
    create_agent_session,
)
from pipython.session import ids
from pipython.testing import FakeClient
from pipython.tui import commands
from pipython.tui.commands import (
    AppState,
    CommandContext,
    _changelog,
    _copy,
    _format_key,
    _hotkeys,
    _new,
    _session,
    build_registry,
)


class RecordingSink:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []
        self.lines: list[list[str]] = []

    def emit_text(self, s: str, style: str = "") -> None:
        self.texts.append((s, style))

    def emit_lines(self, lines: list[str]) -> None:
        self.lines.append(list(lines))

    def flat_text(self) -> str:
        parts = [s for s, _ in self.texts]
        for group in self.lines:
            parts.extend(group)
        return "\n".join(parts)


async def make_ctx(tmp_path, *, sink=None, script=None) -> CommandContext:
    async def factory():
        return await create_agent_session(
            AgentSessionConfig(
                model="fake",
                cwd=tmp_path,
                session_dir=tmp_path / "s",
                client=FakeClient(script=script or []),
            )
        )

    session = await factory()
    return CommandContext(app=AppState(session=session, make_session=factory), sink=sink or RecordingSink())


def _append(store, eid, parent, message) -> None:
    """Append a hand-built entry to the REAL store (writes real JSONL; sets leaf_id=eid)."""
    store.append(MessageEntry(id=eid, parent_id=parent, timestamp=ids.iso_now(), message=message))


def _asst_msg(text=None, *, tool=False, usage=None) -> dict:
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "toolCall", "id": "c", "name": "ls", "arguments": {}})
    msg = {"role": "assistant", "content": content}
    if usage is not None:
        msg["usage"] = usage
    return msg


# --- _format_key (pure) ---

def test_format_key_capitalizes_and_joins():
    assert _format_key("ctrl+b") == "Ctrl+B"
    assert _format_key(["left", "ctrl+b"]) == "Left / Ctrl+B"
    assert _format_key("enter") == "Enter"


def test_format_key_camelcase_preserved():
    # .capitalize() would wrongly yield "Pageup"; must keep interior caps
    assert _format_key("pageUp") == "PageUp"


def test_format_key_macos_option(monkeypatch):
    monkeypatch.setattr(commands.sys, "platform", "darwin")
    assert _format_key("alt+b") == "Option+B"


def test_format_key_non_macos_alt(monkeypatch):
    monkeypatch.setattr(commands.sys, "platform", "linux")
    assert _format_key("alt+b") == "Alt+B"


# --- /hotkeys ---
# NOTE: assert via a LOCAL `sink = RecordingSink()` (concrete type), never
# `ctx.sink.flat_text()` — CommandContext.sink is typed as the Sink Protocol,
# which has no flat_text, so pyright errors on ctx.sink.flat_text(). This
# mirrors test_commands.py's convention.

async def test_hotkeys_lists_key_help(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _hotkeys(ctx, "")
    joined = sink.flat_text()
    assert "Navigation" in joined
    assert "History" in joined  # history nav is implemented (editor cursorUp/Down)
    assert "Completion" in joined  # autocomplete is implemented (tui.select.*)
    assert "Ctrl+B" in joined or "Left" in joined  # formatted cursor keys
    assert "Ctrl+O" in joined  # app.tools.expand in-table
    assert "Ctrl+C" in joined and "Ctrl+D" in joined  # hardcoded app-level bytes


# --- /new ---

async def test_new_swaps_session(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    old = ctx.app.session
    await _new(ctx, "")
    assert ctx.app.session is not old
    assert "new session" in sink.flat_text()


# --- /copy ---

async def test_copy_takes_last_assistant_text_on_path(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first answer"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second answer"))
    got = {}
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: got.setdefault("text", t) or "pbcopy")
    await _copy(ctx, "")
    assert got["text"] == "second answer"
    assert "Copied" in sink.flat_text()


async def test_copy_is_branch_aware(tmp_path, monkeypatch):
    # a2 ("second") is physically last but OFF the current path; leaf → a1 ("first").
    ctx = await make_ctx(tmp_path)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first answer"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second answer"))
    store.leaf_id = "a1"  # branch back — current path is now [u1, a1]
    got = {}
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: got.setdefault("text", t) or "pbcopy")
    await _copy(ctx, "")
    assert got["text"] == "first answer"  # on-path, NOT physical-last "second answer"


async def test_copy_no_assistant_message(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    _append(ctx.app.session.store, "u1", None, {"role": "user", "content": "hi"})
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert "No agent messages" in sink.flat_text()


async def test_copy_pure_toolcall_is_no_message(tmp_path, monkeypatch):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "x"})
    _append(store, "a1", "u1", _asst_msg(text=None, tool=True))  # toolCall only, no text
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert "No agent messages" in sink.flat_text()


# --- /session ---

async def test_session_stats(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("hi", tool=True, usage={"inputTokens": 100, "outputTokens": 20, "cost": 0.01}))
    _append(store, "u2", "a1", {"role": "user", "content": "again"})
    _append(store, "a2", "u2", _asst_msg("ok", usage={"inputTokens": 50, "outputTokens": 10, "cost": 0.005}))
    await _session(ctx, "")
    joined = sink.flat_text()
    assert "2 user, 2 assistant" in joined
    assert "Tool calls: 1" in joined
    assert "↑150 ↓30" in joined
    assert "$0.0150" in joined
    assert "fake" in joined  # model line


async def test_session_counts_toolresult(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("run", tool=True))
    _append(store, "t1", "a1", {"role": "toolResult", "content": "output"})
    await _session(ctx, "")
    assert "1 tool result" in sink.flat_text()


async def test_session_is_branch_aware(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    store = ctx.app.session.store
    _append(store, "u1", None, {"role": "user", "content": "hi"})
    _append(store, "a1", "u1", _asst_msg("first"))
    _append(store, "u2", "a1", {"role": "user", "content": "more"})
    _append(store, "a2", "u2", _asst_msg("second"))
    store.leaf_id = "a1"  # off-path: u2/a2 excluded; current path [u1, a1]
    await _session(ctx, "")
    assert "1 user, 1 assistant" in sink.flat_text()


async def test_session_empty(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _session(ctx, "")
    assert "0 user, 0 assistant, 0 tool result" in sink.flat_text()  # empty → all zero


# --- /changelog ---

async def test_changelog_shows_version_and_repo(tmp_path):
    sink = RecordingSink()
    ctx = await make_ctx(tmp_path, sink=sink)
    await _changelog(ctx, "")
    joined = sink.flat_text()
    from pipython import __version__

    assert __version__ in joined
    assert "github.com/luoxin9510/pi-python" in joined


# --- registry ---

def test_registry_has_11_commands():
    reg = build_registry()
    for name in ("help", "model", "clear", "tree", "branch", "quit",
                 "hotkeys", "new", "copy", "session", "changelog"):
        assert name in reg
    assert len(reg) == 11
```

> `pyproject.toml` 已 `asyncio_mode = "auto"`（已核实，line 36；既有 async 测试同款），无需 `@pytest.mark.asyncio`。导入位置（已实证）：`AgentSessionConfig`/`create_agent_session`/`MessageEntry` 从 `pipython` 顶层；**`AppState`/`CommandContext` 从 `pipython.tui.commands`**（`AppState` 未在 `pipython.__init__` 导出，同 `test_commands.py` 的导入方式）；`ids` 从 `pipython.session`（`ids.iso_now()`/`ids.new_entry_id()`）；`FakeClient` 从 `pipython.testing`（被 `make_ctx` 的 factory 闭包引用，非未使用）。entry 全部手工构造，不走 FakeClient 脚本，故不导入 `AssistantMessage/TextContent/Usage`（避免 ruff F401）。已跑通验证：full path=2u/2a、branch 回 a1 后 path=1u/1a、`session.model=='fake'`。

- [ ] **Step 2: 确认失败** → FAIL (ImportError on new symbols)
- [ ] **Step 3: [PORT] 实现** —— 加进 `src/pipython/tui/commands.py`（handler 放在 `_quit` 之后、`build_registry` 之前；顶部 import 加：stdlib `import sys`（供 `_format_key` 的 macOS 判定）；`from pipython import __version__`；`from pipython.tui.components.clipboard import ClipboardError, copy_to_clipboard`；`from pipython.tui.engine.keybindings import DEFAULT_EDITOR_BINDINGS`。若 `commands.py` 顶部已有 `import sys` 则勿重复）：

```python
def _format_key(key: "str | list[str]") -> str:
    def cap(p: str) -> str:
        # NOT str.capitalize() — that lowercases the tail ("pageUp" → "Pageup").
        return p[:1].upper() + p[1:] if p else p

    def fmt(k: str) -> str:
        out = []
        for p in k.split("+"):
            if p == "alt" and sys.platform == "darwin":
                out.append("Option")
            else:
                out.append(cap(p))
        return "+".join(out)

    if isinstance(key, list):
        return " / ".join(fmt(k) for k in key)
    return fmt(key)


# /hotkeys grouping: (section title, [(action, label)]) — hand-grouped per
# upstream handleHotkeysCommand (Navigation/Editing/History/Completion/Other).
# Every action referenced here is verified present in DEFAULT_EDITOR_BINDINGS.
_HOTKEY_SECTIONS = [
    ("Navigation", [
        ("tui.editor.cursorLeft", "Move left"),
        ("tui.editor.cursorRight", "Move right"),
        ("tui.editor.cursorWordLeft", "Word left"),
        ("tui.editor.cursorWordRight", "Word right"),
        ("tui.editor.cursorLineStart", "Line start"),
        ("tui.editor.cursorLineEnd", "Line end"),
        ("tui.editor.jumpForward", "Jump to char forward"),
        ("tui.editor.jumpBackward", "Jump to char backward"),
    ]),
    ("Editing", [
        ("tui.input.submit", "Submit"),
        ("tui.input.newLine", "New line"),
        ("tui.editor.deleteWordBackward", "Delete word back"),
        ("tui.editor.deleteWordForward", "Delete word forward"),
        ("tui.editor.deleteToLineStart", "Kill to line start"),
        ("tui.editor.deleteToLineEnd", "Kill to line end"),
        ("tui.editor.yank", "Yank"),
        ("tui.editor.yankPop", "Yank pop"),
        ("tui.editor.undo", "Undo"),
    ]),
    # Up/Down navigate prompt history when the editor is empty / at the first
    # or last visual line (editor.py _navigate_history reuses cursorUp/Down).
    ("History", [
        ("tui.editor.cursorUp", "Previous prompt (at first line)"),
        ("tui.editor.cursorDown", "Next prompt (in history)"),
    ]),
    # Autocomplete overlay keys (editor.py consumes these via kb.matches).
    ("Completion", [
        ("tui.input.tab", "Trigger / apply completion"),
        ("tui.select.up", "Select previous"),
        ("tui.select.down", "Select next"),
        ("tui.select.confirm", "Confirm selection"),
        ("tui.select.cancel", "Cancel completion"),
    ]),
    ("Other", [
        ("app.tools.expand", "Expand/collapse tool output"),
    ]),
]


async def _hotkeys(ctx: CommandContext, _: str) -> None:
    # `\x1b[1m…\x1b[0m` (full reset) matches this module's _tree ANSI convention.
    lines: list[str] = []
    for title, rows in _HOTKEY_SECTIONS:
        lines.append(f"\x1b[1m{title}\x1b[0m")
        for action, label in rows:
            key = DEFAULT_EDITOR_BINDINGS.get(action)
            if key is None:
                continue
            lines.append(f"  {_format_key(key):<24} {label}")
        lines.append("")
    # app-level bytes not in the bindings table (app.py _on_stdin_frame):
    lines.append("\x1b[1mSession\x1b[0m")
    lines.append(f"  {'Ctrl+C':<24} Interrupt turn / clear input")
    lines.append(f"  {'Ctrl+D':<24} Exit (empty prompt)")
    ctx.sink.emit_lines(lines)


async def _new(ctx: CommandContext, _: str) -> None:
    # Upstream /new calls handleClearCommand — delegate to keep them identical.
    await _clear(ctx, _)


def _last_assistant_text(session) -> str | None:
    path = current_path(session.store.entries, session.store.leaf_id)
    for e in reversed(path):
        if isinstance(e, MessageEntry) and e.message.get("role") == "assistant":
            text = "".join(
                c.get("text", "")
                for c in e.message.get("content", [])
                if isinstance(c, dict) and c.get("type") == "text"
            )
            return text or None  # empty (pure toolCall) → treated as no message
    return None


async def _copy(ctx: CommandContext, _: str) -> None:
    text = _last_assistant_text(ctx.app.session)
    if not text:
        ctx.sink.emit_text("No agent messages to copy yet.", style="red")
        return
    try:
        copy_to_clipboard(text)
        ctx.sink.emit_text("Copied last agent message to clipboard", style="dim")
    except ClipboardError as e:
        ctx.sink.emit_text(str(e), style="red")


async def _session(ctx: CommandContext, _: str) -> None:
    session = ctx.app.session
    path = current_path(session.store.entries, session.store.leaf_id)
    users = assts = tools_res = tool_calls = 0
    tin = tout = 0
    cost = 0.0
    for e in path:
        if not isinstance(e, MessageEntry):
            continue
        role = e.message.get("role")
        if role == "user":
            users += 1
        elif role == "toolResult":
            tools_res += 1
        elif role == "assistant":
            assts += 1
            for c in e.message.get("content", []):
                if isinstance(c, dict) and c.get("type") == "toolCall":
                    tool_calls += 1
            usage = e.message.get("usage") or {}
            tin += usage.get("inputTokens") or 0
            tout += usage.get("outputTokens") or 0
            cst = usage.get("cost")
            if cst:
                cost += cst
    ctx.sink.emit_lines([
        "\x1b[1mSession Info\x1b[0m",
        f"  Messages:   {users} user, {assts} assistant, {tools_res} tool result",
        f"  Tool calls: {tool_calls}",
        f"  Tokens:     ↑{tin} ↓{tout}",
        f"  Cost:       ${cost:.4f}",
        f"  Model:      {session.model}",
    ])


async def _changelog(ctx: CommandContext, _: str) -> None:
    ctx.sink.emit_lines([
        f"pi-python {__version__}",
        "https://github.com/luoxin9510/pi-python",
        "Full history in git log / GitHub releases.",
    ])
```

并在 `build_registry` 的 `cmds` 列表追加：

```python
        Command("hotkeys", "查看键位帮助", _hotkeys),
        Command("new", "开新会话（同 /clear）", _new),
        Command("copy", "复制最后一条助手消息到剪贴板", _copy),
        Command("session", "查看会话统计", _session),
        Command("changelog", "查看版本信息", _changelog),
```

- [ ] **Step 4: 跑测试 + 四道门** → 全 PASS
- [ ] **Step 5: [TEST] e2e** `tests/e2e/test_tui_tmux.py` 追加一条（复用 TmuxPane + poll，无裸 sleep）：启动 pipython，发 `/hotkeys\r`，poll capture 断言含 `Navigation` 与某个格式化键（如 `Ctrl+B`）；发 `/session\r`，断言含 `Session Info`。
- [ ] **Step 6: e2e 两连跑 + 全套四道门** → 全绿
- [ ] **Step 7: README** 斜杠命令表补 5 行（/hotkeys /new /copy /session /changelog 各一句）。
- [ ] **Step 8: Commit** `feat(tui): /hotkeys /new /copy /session /changelog commands + e2e + README`

---

## 验收核对清单（对照 spec rev 2）

- [ ] §3.1 /hotkeys：action→key 方向 + _format_key（Ctrl+B，camelCase 保留 PageUp）+ 导航/编辑/**历史/补全**四组 + Ctrl+O 在表 + Ctrl+C/D 硬编码 → Task 2
- [ ] §3.2 /new == /clear 语义（`_new` 委托 `_clear`） → Task 2
- [ ] §3.3 /copy：current_path **分支感知**（物理最后一条离开路径的测试）+ 单条目语义（空→无消息）+ 剪贴板 util → Task 1 + Task 2
- [ ] §3.4 /session：current_path 统计（含 **toolResult 计数** + **分支感知** + token/cost 精确断言）+ 空会话不崩 → Task 2
- [ ] §3.5 /changelog：版本 + 仓库链接、不伪造 → Task 2
- [ ] §4 测试（handler 单测用**真实 AppState/session/store**非 duck-typed / clipboard mock+OSC52 + xsel 兜底 + wayland 环境 / 注册 11 条 / e2e） → Task 1/2
- [ ] §5 剪贴板 OSC 52 兜底、mock 子进程例外标注、`copy_to_clipboard -> str` 偏离声明 → Task 1
