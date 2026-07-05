# pi-python 阶段四 footer 状态栏 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 pipython TUI 加上 pi 同款底部状态栏（可用子集）：cwd(~缩写)+git分支、token↑↓、cost、model，缺 SDK 数据的字段留白。

**Architecture:** 两个新组件（`GitBranchProvider` 轮询探测 git 分支、`Footer` 渲染两条独立行），挂进 `app.py` root Container 编辑器下方；Footer 持 `app_state` 每次 render 现取 session（应对 `/clear` 换 session）。规范 = `docs/superpowers/specs/2026-07-05-phase4-footer-design.md`（rev 2，下称 spec）。

**Tech Stack:** Python 3.11+ asyncio；引擎 Component 契约；engine.utils（truncate_to_width/visible_width）；subprocess（git 回退路径）。

## Global Constraints

- 新代码在 `src/pipython/tui/components/{footer,git_branch}.py`；只 import `pipython` 内部引擎/组件与 SDK 公开面，POSIX only。
- 样式常量集中模块顶：dim = dimGray `#666666` → `\x1b[38;2;102;102;102m` + `\x1b[39m`，加 `PHASE-4 REVISIT` 注释留 256 色回退位（对齐 select_list.py 手法，引用 dark.json `dimGray`）。
- 四道门：提交前 `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` 全绿；e2e 变动加 `uv run pytest tests/e2e/ -v`。
- 测试真实执行：真 git 仓库（`git init`）、真文件系统；轮询用注入的短间隔 + 有界等待，禁裸 sleep。
- 模型分工：`[TEST]` 步骤派 haiku，实现派 sonnet；测试失败修复回 sonnet。
- commit 格式 `{feat,fix,test,docs}(scope): message`，scope=tui；消息尾加：
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
- git add 只加本任务文件。

## 现有接缝（已核实，实现者可依赖）

- `AppState`（app.py）：`@dataclass`，`app_state.session: AgentSession`、`app_state.make_session`。**AgentSession 无 `.cwd`**——cwd 在 `session.agent.cwd`（`Path`）；`session.model`（str property）；`session.store.entries`、`session.store.path`。
- `MessageEntry`（session/store.py，`CamelModel`）：`.message` 是裸 `dict`（永不解析成 AssistantMessage）；`.type == "message"`。`Usage`（ai/types.py）字段 `input_tokens/output_tokens/cost`，CamelModel alias 为 `inputTokens/outputTokens/cost`——磁盘 entry dict 用 camelCase。
- app.py：`root = Container()` 后 `root.add_child(transcript/loader_slot/editor)`（312-315）；`_run_turn` 内 `isinstance(event, MessageEnd)`（449）/`isinstance(event, AgentEnd)`（480）分支；`_DIM` 样式常量已存在（381 行在用）；`run_app` 的 setup 在 293 行起，末尾 finally（569+）只护 stdin reader。
- `engine.utils`：`truncate_to_width(s, width, ellipsis) -> str`、`visible_width(s) -> int`。
- 组件契约：`render(width: int) -> list[str]`、`invalidate() -> None`。

---

### Task 1: GitBranchProvider（探测 + 轮询）

**Files:**
- Create: `src/pipython/tui/components/git_branch.py`
- Test: `tests/tui/components/test_git_branch.py`

**Interfaces:**
- Consumes: 无（纯 stdlib）
- Produces:
  - `find_git_head(cwd: Path) -> Path | None`：从 cwd 上行找 `.git`（目录→`<dir>/HEAD`；文件→读 `gitdir: <path>` 解析 worktree 的 `HEAD`）；无则 None。
  - `read_branch(cwd: Path) -> str | None`：主路径直读 HEAD 文件——`ref: refs/heads/X` → `X`；非该前缀（detached）→ `"detached"`；HEAD 内容为 `.invalid` 哨兵 → 回退 `git --no-optional-locks symbolic-ref --quiet --short HEAD`（subprocess，`timeout=2`，失败/空→`"detached"`）；找不到 repo → None。
  - `GitBranchProvider(cwd: Path, poll_interval: float = 2.0)`：`current_branch: str | None`（初始即 `read_branch(cwd)`）；`async start(on_change: Callable[[], None]) -> None`（起 asyncio 轮询任务：每 `poll_interval` 秒对 HEAD 文件 `stat().st_mtime`，变化则重读 branch，值真变才 `on_change()`）；`async stop() -> None`（cancel 任务，suppress CancelledError）。

- [ ] **Step 1: [TEST] 写测试** `tests/tui/components/test_git_branch.py`

```python
import asyncio
import subprocess
from pathlib import Path

import pytest

from pipython.tui.components.git_branch import (
    GitBranchProvider,
    find_git_head,
    read_branch,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("x")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def test_read_branch_returns_current(repo: Path):
    assert read_branch(repo) == "main"


def test_read_branch_after_switch(repo: Path):
    _git(repo, "checkout", "-b", "feature")
    assert read_branch(repo) == "feature"


def test_read_branch_detached_returns_detached(repo: Path):
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git(repo, "checkout", sha)
    assert read_branch(repo) == "detached"


def test_read_branch_non_git_returns_none(tmp_path: Path):
    assert read_branch(tmp_path) is None


def test_find_git_head_regular(repo: Path):
    head = find_git_head(repo)
    assert head is not None and head.name == "HEAD" and head.parent.name == ".git"


def test_find_git_head_worktree(repo: Path, tmp_path: Path):
    wt = tmp_path.parent / "wt"
    _git(repo, "worktree", "add", str(wt))
    head = find_git_head(wt)
    assert head is not None and head.name == "HEAD" and head.read_text().strip()
    # worktree read_branch works through the .git-file gitdir indirection
    assert read_branch(wt) is not None


def test_find_git_head_walks_up(repo: Path):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert find_git_head(sub) is not None


async def test_provider_initial_branch(repo: Path):
    p = GitBranchProvider(repo)
    assert p.current_branch == "main"


async def test_provider_polls_and_calls_on_change(repo: Path):
    p = GitBranchProvider(repo, poll_interval=0.02)
    changed = asyncio.Event()
    await p.start(on_change=changed.set)
    try:
        _git(repo, "checkout", "-b", "feature")
        await asyncio.wait_for(changed.wait(), timeout=3.0)
        assert p.current_branch == "feature"
    finally:
        await p.stop()


async def test_provider_stop_cancels_cleanly(repo: Path):
    p = GitBranchProvider(repo, poll_interval=0.02)
    await p.start(on_change=lambda: None)
    await p.stop()
    await p.stop()  # idempotent, no raise
```

- [ ] **Step 2: 跑测试确认失败** — Run: `uv run pytest tests/tui/components/test_git_branch.py -q` → FAIL (ModuleNotFoundError)
- [ ] **Step 3: [PORT] 实现** `src/pipython/tui/components/git_branch.py`（规范源 footer-data-provider.ts:16-48 findGitPaths、239-267 read_branch）

```python
"""Git branch detection + polling, ported from pi's footer-data-provider.ts.

Deviation: upstream uses fs watch (Node watchFile); this port polls HEAD's
mtime on an asyncio task (POSIX-portable, low churn). reftable-backend ref
switches that don't touch HEAD mtime are not observed (phase-4 follow-up).
"""

import asyncio
import contextlib
import subprocess
from collections.abc import Callable
from pathlib import Path


def find_git_head(cwd: Path) -> Path | None:
    d = cwd.resolve()
    while True:
        git = d / ".git"
        if git.is_dir():
            return git / "HEAD"
        if git.is_file():
            content = git.read_text(errors="replace").strip()
            if content.startswith("gitdir: "):
                git_dir = (d / content[len("gitdir: ") :].strip()).resolve()
                return git_dir / "HEAD"
            return None
        if d.parent == d:
            return None
        d = d.parent


def read_branch(cwd: Path) -> str | None:
    head = find_git_head(cwd)
    if head is None or not head.is_file():
        return None
    content = head.read_text(errors="replace").strip()
    if content.startswith("ref: refs/heads/"):
        return content[len("ref: refs/heads/") :]
    if content == ".invalid":
        try:
            r = subprocess.run(
                ["git", "--no-optional-locks", "symbolic-ref", "--quiet", "--short", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = r.stdout.strip()
            return out or "detached"
        except (subprocess.SubprocessError, OSError):
            return "detached"
    # detached HEAD: content is a raw commit sha, not a ref
    return "detached"


class GitBranchProvider:
    def __init__(self, cwd: Path, poll_interval: float = 2.0):
        self._cwd = Path(cwd)
        self._interval = poll_interval
        self._head = find_git_head(self._cwd)
        self.current_branch: str | None = read_branch(self._cwd)
        self._task: asyncio.Task[None] | None = None

    async def start(self, on_change: Callable[[], None]) -> None:
        self._task = asyncio.ensure_future(self._poll(on_change))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _poll(self, on_change: Callable[[], None]) -> None:
        last_mtime = self._mtime()
        while True:
            await asyncio.sleep(self._interval)
            m = self._mtime()
            if m == last_mtime:
                continue
            last_mtime = m
            new_branch = read_branch(self._cwd)
            if new_branch != self.current_branch:
                self.current_branch = new_branch
                on_change()

    def _mtime(self) -> float | None:
        if self._head is None:
            return None
        try:
            return self._head.stat().st_mtime
        except OSError:
            return None
```

- [ ] **Step 4: 跑测试 + 四道门** → 全 PASS
- [ ] **Step 5: Commit** `feat(tui): git branch provider — HEAD probe + mtime polling`

---

### Task 2: Footer 组件

**Files:**
- Create: `src/pipython/tui/components/footer.py`
- Test: `tests/tui/components/test_footer.py`

**Interfaces:**
- Consumes: Task 1 `GitBranchProvider`；`engine.utils.truncate_to_width`；`engine.tui.Component`
- Produces:
  - `format_tokens(count: int) -> str`（照 footer.ts:23-29）
  - `format_cwd(cwd: str, home: str | None) -> str`（照 footer.ts:31-49：在 HOME 内→`~`/`~/rel`，否则原样）
  - `Footer(app_state, git: GitBranchProvider)`：`render(width) -> list[str]`（两条独立行：行1 pwd、行2 stats，各自 dim + truncate）；`invalidate() -> None`（no-op，无缓存）。
- 备注：`app_state` 是 duck-typed（任何有 `.session`（含 `.agent.cwd`/`.model`/`.store.entries`）的对象），测试用轻量 stub 或真 AppState。

- [ ] **Step 1: [TEST] 写测试** `tests/tui/components/test_footer.py`

```python
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
    # mimic MessageEntry: has .type and .message dict; usage in camelCase
    from pipython.tui.components.footer import _is_message_entry  # noqa

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
```

- [ ] **Step 2: 确认失败** — Run: `uv run pytest tests/tui/components/test_footer.py -q` → FAIL
- [ ] **Step 3: [PORT] 实现** `src/pipython/tui/components/footer.py`（规范源 footer.ts:23-49 helpers、83-245 render 的 pwd/stats 两行结构）

```python
"""Bottom status bar (usable subset), ported from pi's footer.ts.

Two independent lines (pwd, stats), each dim-styled and truncated on its own —
matching upstream footer.ts structure. Fields needing SDK data pi-python does
not yet expose (cache tokens, context %, OAuth sub, session name, auto-compact)
are omitted per spec §1/§6.
"""

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


def format_tokens(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 10000:
        return f"{count / 1000:.1f}k"
    if count < 1_000_000:
        return f"{round(count / 1000)}k"
    if count < 10_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{round(count / 1_000_000)}M"


def format_cwd(cwd: str, home: str | None) -> str:
    if not home:
        return cwd
    resolved_cwd = Path(cwd).resolve()
    resolved_home = Path(home).resolve()
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
```

（注意：测试里的 `_is_message_entry` import 只是占位——实现不需要它；若 haiku RED 写了该 import，GREEN 删掉那行 noqa import，改为 duck-typed `getattr(e, "type", None)`，如上。RED 修正记报告。）

- [ ] **Step 4: 跑测试 + 四道门** → 全 PASS
- [ ] **Step 5: Commit** `feat(tui): footer component — pwd/branch line + token/cost/model line`

---

### Task 3: app 接线 + /clear 回归 + e2e

**Files:**
- Modify: `src/pipython/tui/app.py`
- Modify: `tests/tui/test_app.py`（追加接线/`/clear` 回归测试）
- Modify: `tests/e2e/test_tui_tmux.py`（追加 footer e2e）
- Modify: `README.md`（footer 一节）

**Interfaces:**
- Consumes: Task 1 `GitBranchProvider`、Task 2 `Footer`
- Produces: footer 在 root Container 末尾常驻；git 轮询挂 `tui.request_render`，生命周期 try/finally；每回合末刷新。

- [ ] **Step 1: [TEST] 写接线测试**（`tests/tui/test_app.py` 追加；沿用该文件既有的 FakeClient + RecordingTerm + 脚本 stdin 帧驱动 run_app 的 harness 模式——实现者读该文件现有测试照搬 fixture）：

```python
# 追加到 tests/tui/test_app.py（伪代码骨架，实现者对齐文件既有 harness）
async def test_footer_shows_cwd_and_tokens_and_updates_on_clear(...):
    # FakeClient 脚本：一回合返回带 usage 的 assistant 消息
    # 驱动 run_app（RecordingTerm，注入 client），提交一次 prompt
    # 断言：RecordingTerm.screen() 底部两行含 cwd 段 与 ↑/↓ token、model
    # 然后经 stdin 帧提交 "/clear"，断言 footer token 段归零（新 session store 空）、cwd 仍在
    ...
```

（实现者按 test_app.py 现有 `_run_app_in_task` / 帧注入 / `wait_for_screen` 等工具写全断言；关键断言：底部 footer 两行存在、token 累加正确、`/clear` 后 token 归零 cwd 不变。）

- [ ] **Step 2: 确认失败** → FAIL（footer 未接线，screen 无 footer 行）
- [ ] **Step 3: 实现接线** `src/pipython/tui/app.py`：
  - import：`from pipython.tui.components.footer import Footer` 和 `from pipython.tui.components.git_branch import GitBranchProvider`。
  - `run_app` setup（root Container 处，约 312-315 行后）：
    ```python
    git = GitBranchProvider(cwd)
    footer = Footer(app_state, git)
    root.add_child(footer)  # after editor — bottom of the tree
    ```
  - git 生命周期：把 `git.start(...)` 放进护住 setup 全程的 try/finally（扩大或新包一层 try，finally 里 `await git.stop()`）：
    ```python
    await git.start(on_change=tui.request_render)
    ```
  - 每回合刷新：`_run_turn` 的 `MessageEnd`（449）与 `AgentEnd`（480）分支各加 `footer.invalidate(); tui.request_render()`（token/cost 更新后重绘）。
- [ ] **Step 4: 跑测试 + 四道门** → PASS
- [ ] **Step 5: [TEST] 写 e2e**（`tests/e2e/test_tui_tmux.py` 追加，沿用 tmux_util 轮询）：真实 pty 下启动 pipython（cwd 指向一个 `git init` 的 tmp 仓库），poll capture 断言底部出现 cwd 段与 `(<branch>)`；另断言窄终端下编辑器光标仍正确（footer 多占 2 行不挤出视口——发一次输入回显可见）。
- [ ] **Step 6: e2e 两连跑 + 全套四道门** → 全绿
- [ ] **Step 7: README** 追加 footer 一节：底部状态栏显示 cwd(~)/git 分支/token↑↓/cost/model；说明留白字段（cache/context/sub/session name）待后续阶段。
- [ ] **Step 8: Commit** `feat(tui): wire footer into app; refresh on turn end; e2e + README`

---

## 验收核对清单（对照 spec rev 2）

- [ ] §1 做的字段：cwd/branch/token/cost/model → Task 2/3
- [ ] §2.1 两独立行 + dim + truncate + format_tokens 五档 + format_cwd → Task 2
- [ ] §2.1 Footer 持 app_state 应对 /clear → Task 2 + Task 3 回归测试
- [ ] §2.2 read_branch 直读 HEAD + detached "detached" + worktree + .invalid 回退 → Task 1
- [ ] §2.2 轮询监听（间隔注入、值真变才回调）→ Task 1
- [ ] §3 root Container 末尾 + git 生命周期 try/finally + 每回合刷新 → Task 3
- [ ] §4 测试五类（组件金行/纯函数/git真仓库/接线+/clear/e2e+窄终端光标）→ Task 1/2/3
- [ ] §5 偏离：轮询/detached 保真/两行布局/256 回退标记 → 各任务
