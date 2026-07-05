# pi-python 阶段四 自足斜杠命令（第一批）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 pipython TUI 加 5 条无 SDK 依赖的斜杠命令：`/hotkeys` `/new` `/copy` `/session` `/changelog`。

**Architecture:** 新增一个剪贴板 util 模块 + 5 个 handler 注册进现有 `commands.py` 的 `build_registry()`；handler 经既有 `CommandContext`(app+sink) 驱动，Sink 内部已触发重绘。规范 = `docs/superpowers/specs/2026-07-05-phase4-selfcontained-commands-design.md`（rev 2，下称 spec）。

**Tech Stack:** Python 3.11+ stdlib（subprocess/base64/os/shutil）；无新依赖。

## Global Constraints

- 新代码：`src/pipython/tui/components/clipboard.py`；handler 加进现有 `src/pipython/tui/commands.py`。
- 四道门：提交前 `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` 全绿；e2e 变动加 `uv run pytest tests/e2e/ -v`。
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
- Produces: `copy_to_clipboard(text: str) -> str`——把 text 送到剪贴板，返回用的方法名（`"pbcopy"`/`"wl-copy"`/`"xclip"`/`"xsel"`/`"osc52"`，供调用方/测试断言）。全部路径失败 raise `ClipboardError`。远程会话（`SSH_CONNECTION`/`SSH_TTY`/`MOSH_CONNECTION` 任一非空）或本地工具全不可用 → OSC 52（`\x1b]52;c;<base64(utf-8)>\x07` 写 `sys.stdout` 并 flush）。

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
    monkeypatch.setattr(clipboard, "_which", lambda name: name == "wl-copy")
    ran = {}
    monkeypatch.setattr(
        clipboard.subprocess, "run",
        lambda cmd, **kw: ran.setdefault("cmd", cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "wl-copy"
    assert ran["cmd"][0] == "wl-copy"


def test_linux_x11_falls_to_xclip_then_xsel(monkeypatch):
    _clear_remote(monkeypatch)
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard, "_which", lambda name: name in ("xclip",))
    monkeypatch.setattr(
        clipboard.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
    )
    assert copy_to_clipboard("x") == "xclip"


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

_OSC52_MAX = 100_000  # upstream caps OSC 52 payload; skip if larger


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

```python
import pytest

from pipython.tui import commands
from pipython.tui.commands import (
    CommandContext,
    _changelog,
    _copy,
    _format_key,
    _hotkeys,
    _new,
    _session,
    build_registry,
)


class _Sink:
    def __init__(self):
        self.lines: list[str] = []

    def emit_text(self, s, style=""):
        self.lines.append(s)

    def emit_lines(self, lines):
        self.lines.extend(lines)


class _Store:
    def __init__(self, entries, leaf_id):
        self.entries = entries
        self.leaf_id = leaf_id


class _Session:
    def __init__(self, entries, leaf_id, model="fake/model"):
        self.store = _Store(entries, leaf_id)
        self.model = model


class _App:
    def __init__(self, session):
        self.session = session
        self._made = None

    async def make_session(self):
        self._made = _Session([], None)
        return self._made


def _ctx(session):
    return CommandContext(app=_App(session), sink=_Sink())


# MessageEntry-like stub: has .type and .message dict; entry_id via .id
class _E:
    def __init__(self, eid, parent, message):
        from pipython import MessageEntry  # real type for isinstance in handlers

        self._m = MessageEntry(id=eid, parent_id=parent, timestamp="t", message=message)
        self.id = eid

    def __getattr__(self, k):
        return getattr(self._m, k)


def _asst(eid, parent, text=None, tool=False, usage=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "toolCall", "id": "c", "name": "ls", "arguments": {}})
    msg = {"role": "assistant", "content": content}
    if usage is not None:
        msg["usage"] = usage
    from pipython import MessageEntry

    return MessageEntry(id=eid, parent_id=parent, timestamp="t", message=msg)


def _user(eid, parent, text):
    from pipython import MessageEntry

    return MessageEntry(id=eid, parent_id=parent, timestamp="t", message={"role": "user", "content": text})


# --- _format_key ---

def test_format_key_capitalizes_and_joins():
    assert _format_key("ctrl+b") == "Ctrl+B"
    assert _format_key(["left", "ctrl+b"]) == "Left / Ctrl+B"
    assert _format_key("enter") == "Enter"


# --- /hotkeys ---

async def test_hotkeys_lists_key_help():
    ctx = _ctx(_Session([], None))
    await _hotkeys(ctx, "")
    joined = "\n".join(ctx.sink.lines)
    assert "Ctrl+B" in joined or "Left" in joined  # cursor movement rendered, formatted
    assert "Ctrl+O" in joined  # app.tools.expand in-table


# --- /new ---

async def test_new_swaps_session():
    ctx = _ctx(_Session([_user("a", None, "hi")], "a"))
    old = ctx.app.session
    await _new(ctx, "")
    assert ctx.app.session is not old


# --- /copy ---

async def test_copy_takes_last_assistant_text_on_current_path(monkeypatch):
    entries = [
        _user("u1", None, "hi"),
        _asst("a1", "u1", text="first answer", usage={"inputTokens": 1, "outputTokens": 1, "cost": 0.0}),
        _user("u2", "a1", "more"),
        _asst("a2", "u2", text="second answer", usage={"inputTokens": 1, "outputTokens": 1, "cost": 0.0}),
    ]
    ctx = _ctx(_Session(entries, "a2"))
    got = {}
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: got.setdefault("text", t) or "pbcopy")
    await _copy(ctx, "")
    assert got["text"] == "second answer"
    assert any("Copied" in x for x in ctx.sink.lines)


async def test_copy_no_assistant_message(monkeypatch):
    ctx = _ctx(_Session([_user("u1", None, "hi")], "u1"))
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert any("No agent messages" in x for x in ctx.sink.lines)


async def test_copy_pure_toolcall_is_no_message(monkeypatch):
    entries = [_user("u", None, "x"), _asst("a", "u", text=None, tool=True)]
    ctx = _ctx(_Session(entries, "a"))
    monkeypatch.setattr(commands, "copy_to_clipboard", lambda t: "pbcopy")
    await _copy(ctx, "")
    assert any("No agent messages" in x for x in ctx.sink.lines)


# --- /session ---

async def test_session_stats():
    entries = [
        _user("u1", None, "hi"),
        _asst("a1", "u1", text="hi", tool=True, usage={"inputTokens": 100, "outputTokens": 20, "cost": 0.01}),
        _user("u2", "a1", "again"),
        _asst("a2", "u2", text="ok", usage={"inputTokens": 50, "outputTokens": 10, "cost": 0.005}),
    ]
    ctx = _ctx(_Session(entries, "a2"))
    await _session(ctx, "")
    joined = "\n".join(ctx.sink.lines)
    assert "2" in joined  # 2 user, 2 assistant
    assert "150" in joined or "↑" in joined  # tokens accumulated
    assert "1" in joined  # 1 tool call


async def test_session_empty():
    ctx = _ctx(_Session([], None))
    await _session(ctx, "")
    assert ctx.sink.lines  # renders without crash


# --- /changelog ---

async def test_changelog_shows_version_and_repo():
    ctx = _ctx(_Session([], None))
    await _changelog(ctx, "")
    joined = "\n".join(ctx.sink.lines)
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

- [ ] **Step 2: 确认失败** → FAIL (ImportError on new symbols)
- [ ] **Step 3: [PORT] 实现** —— 加进 `src/pipython/tui/commands.py`（handler 放在 `_quit` 之后、`build_registry` 之前；顶部 import 加 `from pipython import __version__`、`from pipython.tui.components.clipboard import ClipboardError, copy_to_clipboard`、`from pipython.tui.engine.keybindings import DEFAULT_EDITOR_BINDINGS`）：

```python
def _format_key(key: "str | list[str]") -> str:
    def fmt(k: str) -> str:
        parts = k.split("+")
        out = []
        for p in parts:
            if p == "alt" and __import__("sys").platform == "darwin":
                out.append("Option")
            else:
                out.append(p.capitalize())
        return "+".join(out)

    if isinstance(key, list):
        return " / ".join(fmt(k) for k in key)
    return fmt(key)


# /hotkeys grouping: (section title, [(action, label)]) mirroring upstream
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
    ("Other", [
        ("app.tools.expand", "Expand/collapse tool output"),
    ]),
]


async def _hotkeys(ctx: CommandContext, _: str) -> None:
    lines: list[str] = []
    for title, rows in _HOTKEY_SECTIONS:
        lines.append(f"\x1b[1m{title}\x1b[22m")
        for action, label in rows:
            key = DEFAULT_EDITOR_BINDINGS.get(action)
            if key is None:
                continue
            lines.append(f"  {_format_key(key):<24} {label}")
        lines.append("")
    # app-level bytes not in the bindings table:
    lines.append("\x1b[1mSession\x1b[22m")
    lines.append(f"  {'Ctrl+C':<24} Interrupt turn / clear input")
    lines.append(f"  {'Ctrl+D':<24} Exit (empty prompt)")
    ctx.sink.emit_lines(lines)


async def _new(ctx: CommandContext, _: str) -> None:
    ctx.app.session = await ctx.app.make_session()
    ctx.sink.emit_text("new session")


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
        "\x1b[1mSession Info\x1b[22m",
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

- [ ] §3.1 /hotkeys：action→key 方向 + _format_key（Ctrl+B）+ Ctrl+O 在表 + Ctrl+C/D 硬编码 → Task 2
- [ ] §3.2 /new == /clear 语义 → Task 2
- [ ] §3.3 /copy：current_path 分支感知 + 单条目语义（空→无消息）+ 剪贴板 util → Task 1 + Task 2
- [ ] §3.4 /session：current_path 统计 + 空会话不崩 → Task 2
- [ ] §3.5 /changelog：版本 + 仓库链接、不伪造 → Task 2
- [ ] §4 测试五类（handler 单测/clipboard mock+OSC52/注册 11 条/e2e） → Task 1/2
- [ ] §5 剪贴板 OSC 52 兜底、mock 子进程例外标注 → Task 1
