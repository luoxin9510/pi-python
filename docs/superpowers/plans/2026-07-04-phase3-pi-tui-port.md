# pi-python 阶段三：pi-tui 差分渲染引擎移植 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 pi-tui 差分渲染引擎与全套驱动组件架构级移植为 Python，替换阶段二 inline TUI，使 pipython 获得与 pi 一致的终端体验（主缓冲差分渲染、常驻编辑器、补全浮层、滚动历史保留）。

**Architecture:** 模块一一对应上游 `packages/tui/src`（engine/ + components/ 两层），Component 契约 `render(width) -> list[str]`；新引擎旁路开发，旧 TUI 末位任务才删。规范 = `docs/superpowers/specs/2026-07-04-phase3-pi-tui-port-design.md`（rev 3，下称 spec）。

**Tech Stack:** Python 3.11+ 纯 asyncio；markdown-it-py(gfm-like)+linkify-it-py、wcwidth、regex、pathspec；零 UI 框架。

## Global Constraints

（每任务隐含本节；与 spec 冲突以 spec 为准）

- **移植任务约定（本计划的核心工作方式）**：标 `[PORT]` 的实现步骤，其规范源是上游 TS 文件（本地路径 `~/Developer/nukcole-pi/packages/tui/src/<file>`，任务书内给出）。实现者必须**先通读该文件对应区段**，语义级照搬（命名转 snake_case、Node API 换 asyncio/termios 等价物）；任务书提供的是**接口契约（必须逐字遵守）+ 行为要点 + 完整测试**，不是重抄一遍 TS。凡主动偏离上游语义必须在报告"Deviations"节声明理由；纯语言运行时差异（调度顺序、异常类型映射）预授权偏离、无需逐条声明，但改变可观察行为的偏离必须声明。
- **测试翻译约定**：标 `[TEST-PORT]` 的步骤把上游对应 `*.test.ts` 的用例翻译为 pytest（同名、同输入、同断言；上游测试路径任务书给出）。翻译时发现上游用例依赖未移植功能 → 跳过并在报告列明清单，不许静默丢弃。
- 模型分工：`[TEST]`/`[TEST-PORT]` 步骤派 haiku subagent，其余 sonnet；同任务先测试后实现。测试失败的修复回 sonnet。
- 四道门：提交前 `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` 全绿；e2e 变动时加 `uv run pytest tests/e2e/ -v`。
- 依赖：本计划 Task 1 新增 `markdown-it-py + linkify-it-py + wcwidth + regex`（钉 `==`，随 uv 解析回填）；prompt_toolkit/rich/rapidfuzz 的**移除只在 Task 18** 进行。核心 SDK 依赖不变。
- **旧 TUI 存活约束**：Task 18 之前不得删除/修改 `src/pipython/tui/{app,keys,render,commands,completers}.py` 的现有行为（Task 15/16 明确列出的接线改动除外）；`pipython` 入口全程可用，每任务 CI 全绿。
- 新代码全部在 `src/pipython/tui/engine/`、`src/pipython/tui/components/`、`src/pipython/tui/app2.py`（Task 16 建、Task 18 更名为 app.py）。
- TUI 只 import `pipython` 公开 API；POSIX only；tmux e2e 断言一律轮询 capture 直到匹配或超时。
- commit 格式 `{feat,fix,test,docs,chore}(scope): message`，scope ∈ {tui,pkg}；消息尾加：
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
- git add 只加本任务文件。

---

## 文件结构总览

| 任务 | 产出 | 上游规范源（packages/tui/src/） |
|---|---|---|
| 1 | 依赖入库 + `engine/__init__.py` + `engine/utils.py` | utils.ts（宽度/字素/折行子集） |
| 2 | `engine/terminal_colors.py`、`engine/term_caps.py` | terminal-colors.ts、terminal-image.ts（仅 hyperlink/isImageLine/能力子集） |
| 3 | `engine/stdin_buffer.py` | stdin-buffer.ts |
| 4 | `engine/keys.py` | keys.ts（子集见 spec §5） |
| 5 | `engine/keybindings.py`、`engine/word_navigation.py`、`engine/fuzzy.py`、`engine/kill_ring.py`、`engine/undo_stack.py` | 同名五文件 |
| 6 | `engine/terminal.py` | terminal.ts |
| 7 | `engine/tui.py` 之一：Component/Container + 差分渲染 + request_render | tui.ts（差分核心区段） |
| 8 | `engine/tui.py` 之二：overlay 栈/焦点链 + resize/硬件光标 | tui.ts（overlay/焦点/resize 区段） |
| 9 | `components/{text,box,spacer,truncated_text,loader}.py` | 同名五组件 |
| 10 | `components/select_list.py` | select-list.ts |
| 11 | `components/editor.py` 之一：缓冲模型/光标/增删/移动 | editor.ts + editor.test.ts（对应域） |
| 12 | editor 之二：kill-ring/undo/历史/bracketed paste | 同上 |
| 13 | editor 之三：补全钩子 + SelectList 集成 + IME 光标；`engine/editor_protocol.py` | 同上 + editor-component.ts |
| 14 | `components/markdown.py`（含扁平流→树适配 + 严格删除线插件） | markdown.ts |
| 15 | `components/autocomplete.py` + completers.py Provider 包装 | autocomplete.ts |
| 16 | `app2.py`（新引擎主循环）+ commands.py 渲染出口双轨 | （集成，无单一上游文件） |
| 17 | e2e 迁移 + 新场景（浮层/滚动历史/多行） | — |
| 18 | 切换入口、删旧码、依赖移除、README、CI | — |
| 19 | [ACCEPTANCE] 维护者并排手感验收 | — |

---

### Task 1: 依赖入库与 engine/utils.py（宽度/字素/ANSI 折行）

**Files:**
- Create: `src/pipython/tui/engine/__init__.py`（空）、`src/pipython/tui/engine/utils.py`
- Modify: `pyproject.toml`（tui extra **追加** markdown-it-py/linkify-it-py/wcwidth/regex，钉版；不移除旧四件）
- Test: `tests/tui/engine/__init__.py`（空）、`tests/tui/engine/test_utils.py`

**Interfaces:**
- Consumes: 无
- Produces（后续所有组件依赖，签名逐字）：
  - `graphemes(s: str) -> list[str]`（regex `\X`）
  - `visible_width(s: str) -> int`（ANSI 序列零宽；宽度 = wcwidth + RGI emoji=2；分类正则照抄 utils.ts:40-42，RGI_Emoji 用码位表替代——从 `regex` 不支持 `\p{RGI_Emoji}` 的现实出发，用 `unicodedata`+Emoji 码段近似构造 `_is_rgi_emoji(cluster)`）
  - `wrap_text_with_ansi(text: str, width: int) -> list[str]`（ANSI 感知折行，含 OSC-8 跨行重开——对齐上游 wrapTextWithAnsi 及其 OSC-8 测试）
  - `truncate_to_width(s: str, width: int, ellipsis: str = "…") -> str`
  - `apply_background_to_line(line: str, bg: str, width: int) -> str`

**上游规范源**：`utils.ts`（重点 1-120 行分类正则与 visibleWidth、wrapTextWithAnsi 全函数）；上游测试 `test/wrap-ansi.test.ts`（折行 + OSC-8 续行用例）。

- [ ] **Step 1: 依赖入库** `uv add --optional tui markdown-it-py linkify-it-py wcwidth regex`，把解析出的版本改成 `==` 钉版，`uv sync --extra tui`。
- [ ] **Step 2: [TEST] 写金标准测试**（含 CJK/emoji 专项，spec §7.3）：

```python
import pytest
from pipython.tui.engine.utils import (
    apply_background_to_line, graphemes, truncate_to_width,
    visible_width, wrap_text_with_ansi,
)

CASES_WIDTH = [
    ("abc", 3), ("中文", 4), ("a中b", 4), ("", 0),
    ("\x1b[31m红\x1b[0m", 2),          # ANSI 零宽
    ("👩‍👩‍👧‍👦", 2),                      # ZWJ 家庭 = 单字素宽 2
    ("é", 1),                     # 组合重音
    ("ｆｕｌｌ", 8),                     # 全角拉丁
]

@pytest.mark.parametrize("s,w", CASES_WIDTH)
def test_visible_width(s, w):
    assert visible_width(s) == w

def test_graphemes_zwj_single_cluster():
    assert len(graphemes("👩‍👩‍👧‍👦x")) == 2

def test_wrap_cjk_never_splits_grapheme():
    lines = wrap_text_with_ansi("中文字符串测试", 5)
    assert all(visible_width(x) <= 5 for x in lines)
    assert "".join(lines) == "中文字符串测试"

def test_wrap_preserves_ansi_state_across_lines():
    lines = wrap_text_with_ansi("\x1b[31m" + "红" * 6 + "\x1b[0m", 4)
    assert len(lines) == 3 and all("\x1b[31m" in x for x in lines[1:])

def test_wrap_osc8_reopens_on_continuation():
    link = "\x1b]8;;http://x\x1b\\" + "a" * 8 + "\x1b]8;;\x1b\\"
    lines = wrap_text_with_ansi(link, 4)
    assert all(l.startswith("\x1b]8;;http://x") or i == 0 for i, l in enumerate(lines))

def test_truncate_to_width_cjk():
    assert truncate_to_width("中文测试", 5) == "中文…"

def test_apply_background_pads_to_width():
    out = apply_background_to_line("ab", "\x1b[44m", 5)
    assert visible_width(out) == 5 and out.startswith("\x1b[44m")
```

- [ ] **Step 3: 跑测试确认失败**（ModuleNotFoundError）。
- [ ] **Step 4: [PORT] 实现 utils.py**——先读 `utils.ts` 对应区段再写；OSC-8 跨行行为对照上游 `wrapTextWithAnsi` 的 OSC-8 测试语义。
- [ ] **Step 5: [TEST-PORT] 翻译上游 utils 相关测试**（`test/` 下 wrap/width 用例）补进 test_utils.py。
- [ ] **Step 6: 四道门全绿。**
- [ ] **Step 7: Commit** `feat(tui): engine utils — grapheme/width/ansi-aware wrapping (+ tui extra deps)`

---

### Task 2: terminal_colors.py 与 term_caps.py

**Files:**
- Create: `src/pipython/tui/engine/terminal_colors.py`、`src/pipython/tui/engine/term_caps.py`
- Test: `tests/tui/engine/test_terminal_colors.py`、`tests/tui/engine/test_term_caps.py`

**Interfaces:**
- Produces:
  - terminal_colors: `parse_osc11_response(data: bytes) -> tuple[int,int,int] | None`、`is_dark(rgb: tuple[int,int,int]) -> bool`、`QUERY_BG = "\x1b]11;?\x1b\\"`
  - term_caps: `TermCaps(true_color: bool, hyperlinks: bool)`、`detect_caps(env: dict[str,str]) -> TermCaps`（纯函数，读 env 判定，对齐上游 getCapabilities 判定表）、`hyperlink(url: str, text: str, caps: TermCaps) -> str`（不支持时返回纯文本）、`is_image_line(line: str) -> bool`

**上游规范源**：`terminal-colors.ts`（73 行全量）；`terminal-image.ts` 仅 `getCapabilities`/`hyperlink`/`isImageLine` 三件（spec §3）。

- [ ] **Step 1: [TEST]**：OSC 11 样本解析（`\x1b]11;rgb:1e1e/1e1e/1e1eBEL` 与 ST 两种终止符）、深浅判定边界、caps 判定表（TERM/COLORTERM 组合）、hyperlink 开关两态、is_image_line 真假样本。测试代码写全（每个函数 ≥3 用例）。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: [PORT] 实现两模块。**
- [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): terminal color scheme detection and capability subset`

---

### Task 3: stdin_buffer.py（字节流切帧）

**Files:**
- Create: `src/pipython/tui/engine/stdin_buffer.py`
- Test: `tests/tui/engine/test_stdin_buffer.py`

**Interfaces:**
- Produces: `StdinBuffer(on_frame: Callable[[str], None], esc_timeout: float = 0.01, timer: Callable = asyncio 计时注入位)`（0.01=上游 10ms；此前 0.05 系 brief 单位笔误，已由维护者确认更正）；`feed(data: bytes) -> None`；帧类型语义：完整转义序列成帧、半截序列等待后续字节、孤立 ESC 超时成帧、**bracketed paste（`ESC[200~`…`ESC[201~`）整块单帧且经同一 on_frame 通道、marker 保留在帧内**（下游 Editor.handle_input 靠 marker 判断粘贴——单通道是硬契约，禁止第二回调）。计时器可注入（测试用手动时钟，不 sleep）。

**上游规范源**：`stdin-buffer.ts`（434 行全量）；测试翻译源 `test/stdin-buffer.test.ts`（458 行）。

- [ ] **Step 1: [TEST-PORT] 翻译上游 stdin-buffer.test.ts 全部适用用例**（预计 20+ 条：分段到达的 CSI、粘贴块跨 feed 调用、ESC 超时、混合流）。翻译不动断言语义；依赖 Node 定时器的用例改手动时钟注入。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: [PORT] 实现。**
- [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): stdin byte-stream framing with bracketed paste`

---

### Task 4: keys.py（KeyEvent 解析）

**Files:**
- Create: `src/pipython/tui/engine/keys.py`
- Test: `tests/tui/engine/test_keys.py`

**Interfaces:**
- Produces:
  - `KeyEvent(name: str, ctrl: bool, alt: bool, shift: bool, text: str | None)`（frozen dataclass；`name` 取值对齐上游：`"enter" "tab" "backspace" "up" ... "a"`）
  - `parse_key(frame: str, kitty: bool) -> KeyEvent | None`（一帧一键；粘贴帧不进此函数）
  - `key_id(e: KeyEvent) -> str`（`"ctrl+shift+enter"` 风格规范名，供 keybindings 查表）
- 子集边界照 spec §5：全部 legacy 序列 + kitty CSI-u 基础/修饰/flag-4 alternate keys；**不含 native-modifiers**。

**上游规范源**：`keys.ts`（重点 CSI-u 解析区段 550-700 行与 legacy 表）；测试翻译源 `test/keys.test.ts`（614 行）。

- [ ] **Step 1: [TEST-PORT] 翻译 keys.test.ts 适用用例**（legacy 方向键/功能键/Ctrl 组合、CSI-u 带修饰、flag-4 alternate、UTF-8 文本键；该文件无 native-modifiers 用例，无需跳过清单）。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: [PORT] 实现 parse_key/key_id。**
- [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): key event parsing — legacy + kitty CSI-u subset`

---

### Task 5: 编辑器支撑五件（keybindings/word_navigation/fuzzy/kill_ring/undo_stack）

**Files:**
- Create: `src/pipython/tui/engine/{keybindings,word_navigation,fuzzy,kill_ring,undo_stack}.py`
- Test: `tests/tui/engine/test_editor_support.py`

**Interfaces:**
- Produces:
  - keybindings: `KeyBindings(table: dict[str, str])`（key_id → action 名）；`DEFAULT_EDITOR_BINDINGS: dict`——照抄 keybindings.ts 默认表，**外加声明偏离**：`"alt+enter": "newline"`（spec §5，上游无此绑定）
  - word_navigation: `word_left(text: str, pos: int) -> int`、`word_right(text: str, pos: int) -> int`——西文按 UAX#29 词界近似（字母数字连续段），**CJK 按"连续 CJK 段=一个词"**（spec §9 裁决）
  - fuzzy: `fuzzy_match(query: str, candidate: str) -> int | None`（评分语义照 fuzzy.ts）、`fuzzy_filter(query: str, items: list[str]) -> list[str]`
  - kill_ring: `KillRing()`：`kill(text, prepend: bool)`、`yank() -> str`、`yank_pop() -> str`
  - undo_stack: `UndoStack()`：`push(state: tuple[str,int])`、`undo() -> tuple[str,int] | None`、`clear()`——**无 redo、无合并策略**（上游 undo-stack.ts 就是裸栈；此前"合并策略照上游/redo"系 brief 幻觉，审核证伪后删除；Task 12 编辑器仅绑 undo，与上游一致）
- Consumes: Task 4 `key_id`

**上游规范源**：同名五个 ts 文件；fuzzy/undo/kill-ring 若上游有测试则 [TEST-PORT]，无则按接口写新测试。

- [ ] **Step 1: [TEST] + [TEST-PORT]**：每模块 ≥4 用例；word_navigation 必测 `"hello 世界你好 world"` 的中西混排跳词（CJK 段一跳到底）；fuzzy 测评分排序稳定性；undo 测合并窗口；kill_ring 测 yank_pop 轮转。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: [PORT] 实现五模块。**
- [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): editor support — bindings, word nav, fuzzy, kill ring, undo`

---

### Task 6: terminal.py（raw mode / 能力协商 / ANSI 出口）

**Files:**
- Create: `src/pipython/tui/engine/terminal.py`
- Test: `tests/tui/engine/test_terminal.py`

**Interfaces:**
- Produces:
  - `TerminalIO(Protocol)`: `write(data: str)`、`columns: int`、`rows: int`——**引擎全部输出走它**；测试注入 `RecordingTerm`（见 Task 7 conftest）
  - `RealTerminal(TerminalIO)`：`start()`（termios raw + 探测 kitty：发 `CSI ? u` 收应答/超时 200ms，照 terminal.ts 探测次序；启用 bracketed paste/kitty flags）、`stop()`（**finally 级还原**：termios、kitty 标志弹栈、显示光标——异常路径必须还原，注册 atexit 兜底）、`kitty_enabled: bool`、`on_resize(cb)`（SIGWINCH）
  - 光标寻址原语：`move_to_row(delta: int)`、`erase_line()`、`hide_cursor()/show_cursor()`（ANSI 串常量随类导出，供 tui.py 用）
- 真实终端行为进 e2e（Task 17）；本任务单测覆盖：raw 进出的 termios 调用序列（mock termios 模块——**这是全项目唯一允许 mock 的系统边界**，因 CI 无 pty 可控回读）、kitty 应答/超时解析纯函数化拆出直测。本任务测试不需要任何渲染桩。

**上游规范源**：`terminal.ts`（531 行全量；native-modifiers 调用点按 spec §5 裁决跳过）。

- [ ] **Step 1: [TEST]**：kitty 应答解析函数（`parse_kitty_reply`）真假样本；raw 进出调用序列；stop 幂等（重复调用不炸）。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): real terminal — raw mode, kitty negotiation, restore guarantees`

---

### Task 7: tui.py 之一 —— Component/Container + 差分渲染核心

**Files:**
- Create: `src/pipython/tui/engine/tui.py`
- Test: `tests/tui/engine/conftest.py`（`RecordingTerm`：实现 TerminalIO，记录 write 的 ANSI 操作序列并可回放成虚拟屏幕）、`tests/tui/engine/test_diff_render.py`

**Interfaces:**
- Produces（**契约照上游真实形状**，tui.ts:64-79 与 ~104-107）:
  - `Component(Protocol)`: `render(width: int) -> list[str]`、`invalidate() -> None`（必需）、可选 `handle_input(data: str) -> None`（吃**原始帧字符串**——把帧解析成 KeyEvent 是组件自己的事，见 Task 11）
  - `Focusable(Protocol)`: **仅一个可写属性 `focused: bool`**（上游没有 focus()/unfocus() 方法；TUI 直接读写 `.focused`，组件在自己的 render 里检查它决定是否内嵌 CURSOR_MARKER，见 Task 8）
  - `CURSOR_MARKER = "\x1b_pi:c\x07"`（零宽 APC 序列常量，本任务定义、Task 8 消费）
  - `Container(Component)`: `add_child/remove_child/clear`，render 拼接子行
  - `TUI(term: TerminalIO)`: `set_root(c: Component)`、`request_render(force: bool = False)`（`loop.call_soon` 归并，多次调用一帧执行）、`do_render()`（测试可直调同步跑）、`set_focus(c: Component | None)`（翻转新旧组件的 `.focused` 并转发输入帧给焦点组件的 handle_input）、`start()/stop()`
  - 差分语义（照 tui.ts）：新旧行数组比对 → 光标寻址首个差异行 → 只重写差异行（含尾部缩短时擦除）；**增长向下扩展、绝不清屏重画**（滚动历史保留——注意：该逻辑**内联在 doRender 里**的 `maxLinesRendered`/`bufferLength`/`previousViewportTop` 簿记中，没有独立函数；上游 `expandForLines` 是 kitty 图片专用 helper，与此无关，勿被名字误导）；`clear_on_shrink` 选项。
- Consumes: Task 6 `TerminalIO`

**上游规范源**：`tui.ts` 的 `doRender` 实际在 **1254-1620 行**（367 行大函数）。**筛读警告**：其中大量交织 kitty 图片合成分支（`getKittyImageReservedRows`/`deleteKittyImages`/`collectKittyImageIds` 等）——图片是 spec 非目标，**只抄纯差分/viewport 逻辑，图片分支整段跳过**。

- [ ] **Step 1: [TEST] 差分行为测试**（RecordingTerm 断言操作序列）：

```python
def test_first_render_writes_all_lines(term, tui): ...
def test_unchanged_rerender_writes_nothing(term, tui): ...
def test_single_middle_line_change_rewrites_only_that_line(term, tui): ...
def test_growth_appends_without_clearing(term, tui):
    # 关键：先渲 3 行再渲 5 行，断言旧 3 行未被擦除重写、只新增 2 行
def test_shrink_erases_tail_lines(term, tui): ...
def test_request_render_coalesces(term, tui, event_loop):
    # 连续 5 次 request_render 只触发一次 do_render
```
（每条写全断言，RecordingTerm 提供 `ops` 列表与 `screen()` 回放。）
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现（含 Container）。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): differential renderer core — Component contract, coalesced render`

---

### Task 8: tui.py 之二 —— overlay 栈/焦点链 + resize/硬件光标

**Files:**
- Modify: `src/pipython/tui/engine/tui.py`
- Test: `tests/tui/engine/test_overlay_focus.py`、`tests/tui/engine/test_resize_cursor.py`

**Interfaces:**
- Produces（追加到 TUI）：
  - `show_overlay(c: Component, *, anchor_row: int | None = None) -> OverlayHandle`、`OverlayHandle.close()`；overlay 渲染叠加在主行数组之上（照 tui.ts `compositeOverlays`）
  - 焦点链：overlay 打开自动夺焦、关闭还焦给此前焦点者（读写 `.focused`，Task 7 契约）；嵌套 overlay 栈式还原（照 tui.ts focus-restore 状态机）
  - `on_resize()`：SIGWINCH → previous_viewport_top 修正 + 全量重绘（**回调注册在 terminal.ts 侧**，Python 对应挂在 Task 6 RealTerminal.on_resize，TUI 订阅）
  - **硬件光标 = CURSOR_MARKER 提取机制（照上游，非组件自报坐标）**：聚焦组件在自己 render 输出里内嵌 `CURSOR_MARKER`（Task 7 常量）；`do_render` 在 **overlay 合成与 viewport 计算完成后**的最终行数组里 `extract_cursor_position()` 找 marker → 算行列 → 从行里剥掉 marker → 把真实终端光标定位到该点（IME 候选窗跟随）。浮层/滚动场景因"先合成后找"而天然正确——这是上游架构，禁止改成组件自算屏幕坐标。
- Consumes: Task 7 全部、Task 6 `on_resize`

**上游规范源**：`tui.ts` overlay/焦点状态机 366-620 行；`compositeOverlays` 1050-1160 行；resize 感知逻辑在 `doRender` 内 1258-1352 行；CURSOR_MARKER 注释 118-120 行与 `extractCursorPosition`；SIGWINCH 注册见 `terminal.ts` 134-155 行。

- [ ] **Step 1: [TEST]**：overlay 显示/关闭的行合成；夺焦/还焦（含嵌套两层 overlay 先开后关、后开先关两序）；resize 后全量重绘；hardware cursor 的落点 ANSI 断言。每条写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): overlay stack with focus restore, resize handling, hardware cursor`

---

### Task 9: 基础组件五件（text/box/spacer/truncated_text/loader）

**Files:**
- Create: `src/pipython/tui/components/__init__.py`、`src/pipython/tui/components/{text,box,spacer,truncated_text,loader}.py`
- Test: `tests/tui/components/__init__.py`、`tests/tui/components/test_basic_components.py`

**Interfaces:**
- Produces:
  - `Text(content: str, style: str = "")`：`set_content(s)`；render 按宽折行（用 utils.wrap_text_with_ansi）
  - `Box(child: Component, *, padding: int = 0, border: bool = False)`
  - `Spacer(lines: int = 1)`
  - `TruncatedText(content: str)`（单行截断加省略号）
  - `Loader(tui_request_render: Callable, frames: list[str] | None = None, interval: float = 0.08)`：`start()/stop()`；spinner 帧推进靠注入的 request_render（测试手动步进，不真 sleep）
- Consumes: Task 1 utils、Task 7 Component

**上游规范源**：同名五组件文件。

- [ ] **Step 1: [TEST]**：每组件 render 金行断言（含 Text 的 CJK 折行、Box 边框宽度、Loader 手动步进换帧）。写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): basic components — text, box, spacer, truncated text, loader`

---

### Task 10: select_list.py

**Files:**
- Create: `src/pipython/tui/components/select_list.py`
- Test: `tests/tui/components/test_select_list.py`

**Interfaces:**
- Produces: `SelectItem(value: str, label: str, description: str | None = None)`（dataclass，照上游 item 形状）；`SelectList(items: list[SelectItem], max_visible: int)`：`move_up()/move_down()`（越界环绕照上游）、`selected: SelectItem | None`、`set_items(items)`；render 高亮当前项、超出 max_visible 滚动窗口。（Task 13 的 `AutocompleteItem` 即此 `SelectItem` 的别名——补全选中直接拿回结构化条目，无需 index 映射。）
- Consumes: Task 7 Component、Task 1 utils

**上游规范源**：`select-list.ts`（229 行全量；theme 参数简化为固定 pi 默认样式，样式常量集中模块顶）。

- [ ] **Step 1: [TEST]**：窗口滚动（8 项 max 5，光标到 6 时窗口移动）、环绕、高亮行 ANSI、空列表 render 空。写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): select list component`

---

### Task 11: editor.py 之一 —— 缓冲模型/光标/增删/移动

**Files:**
- Create: `src/pipython/tui/components/editor.py`
- Test: `tests/tui/components/test_editor_core.py`

**Interfaces:**
- Produces:
  - `Editor(bindings: KeyBindings = DEFAULT..., on_submit: Callable[[str], None] | None = None)`——实现 Task 7 的 Component 契约：`render/invalidate/handle_input(data: str)` + `focused: bool` 属性
  - **输入分层（Task 7 契约的桥接点，明确写死）**：`handle_input(data: str)` 是对外入口（TUI 转发原始帧）——内部先判 bracketed paste 帧→`handle_paste`，否则 `parse_key`（Task 4）→ `handle_key(e: KeyEvent)`；`handle_key` 是**内部方法但保持公开**（测试直接驱动它，绕过帧编码）
  - 状态面：`text: str`、`cursor: tuple[int, int]`（行,字素列）、`set_text(s)`
  - `handle_key(e: KeyEvent) -> None`（本任务动作子集：字符插入、backspace/delete、左右上下、home/end、行首尾、`newline` 动作、`submit` 动作→on_submit）
  - `handle_paste(text: str) -> None`（整段插入）
  - render：多行 + 按宽软折行（视觉行 ≠ 逻辑行，照 editor.ts 布局逻辑）；**`focused` 为真时在光标字素处内嵌 `CURSOR_MARKER`**（Task 7 常量；Task 8 的 TUI 负责提取定位——editor 不算屏幕坐标）
- Consumes: Task 4 KeyEvent/parse_key、Task 5 bindings、Task 1 utils、Task 7 Component/Focusable/CURSOR_MARKER

**上游规范源**：`editor.ts`（缓冲/光标/渲染区段）；测试翻译源 `editor.test.ts` **编辑与光标移动域**的用例。

- [ ] **Step 1: [TEST-PORT] 翻译 editor.test.ts 指定域用例**——本任务认领的 describe 域（行号为该文件实际位置）：`public state accessors`(287)、`Backslash+Enter newline workaround`(315)、`Kitty CSI-u handling`(373)、`Unicode text editing behavior`(399)、`Grapheme-aware text wrapping`(702)、`Word wrapping`(835)、`Character jump`(2824)、`Sticky column`(3045)。（`Prompt history navigation`/`Kill ring`/`Undo`/`Paste marker` 归 Task 12，`Autocomplete` 归 Task 13——三方清单互斥完备，不许重复不许漏。）另补 CJK 光标列宽用例（"中文" 上 backspace/左移的字素级行为）≥5 条，写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现本域。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): editor core — buffer, cursor, editing, soft wrap`

---

### Task 12: editor 之二 —— kill-ring/undo/历史/粘贴键位

**Files:**
- Modify: `src/pipython/tui/components/editor.py`
- Test: `tests/tui/components/test_editor_killring_undo_history.py`

**Interfaces:**
- Produces（追加动作）：`kill_line`(Ctrl+K)/`kill_word_back`(Ctrl+W)/`yank`(Ctrl+Y)/`yank_pop`(Alt+Y)、`undo`(Ctrl+_)、历史 `history_prev/next`（`Editor.history: list[str]` + `add_history(s)`；编辑中草稿保存语义照 editor.ts）、bracketed paste 经 `handle_paste` 且计入单次 undo 单元；**大段粘贴折叠为 `[paste #N +M lines]` marker**（阈值与文案照 editor.ts）+ `get_expanded_text() -> str`（把 marker 展开回真实粘贴内容——app 提交必须走它，否则模型收到 marker 字符串）。
- Consumes: Task 5 KillRing/UndoStack、Task 11 全部

**上游规范源**：`editor.ts` 对应区段；`editor.test.ts` kill-ring/undo/history 域。

- [ ] **Step 1: [TEST-PORT] 翻译本任务认领域**：`Prompt history navigation`(42)、`Kill ring`(1158)、`Undo`(1555)、`Paste marker atomic behavior`(3547)（预计 25+ 条），写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): editor kill ring, undo, history, paste as single undo unit`

---

### Task 13: editor 之三 —— 补全钩子 + SelectList 集成 + IME；editor_protocol.py

**Files:**
- Modify: `src/pipython/tui/components/editor.py`
- Create: `src/pipython/tui/engine/editor_protocol.py`
- Test: `tests/tui/components/test_editor_autocomplete.py`

**Interfaces:**
- Produces（**契约照上游真实形状** autocomplete.ts:241-270 与 editor-component.ts）:
  - `AutocompleteItem(value: str, label: str)`（dataclass）
  - `AutocompleteProvider(Protocol)`——**异步可取消**（上游是 Promise+AbortSignal+防抖，不许简化成同步）：
    `async def get_suggestions(self, lines: list[str], cursor_line: int, cursor_col: int, *, force: bool = False, is_cancelled: Callable[[], bool] = ...) -> tuple[list[AutocompleteItem], str]`（返回候选与 prefix）；
    `def apply_completion(self, lines, cursor_line, cursor_col, item: AutocompleteItem, prefix: str) -> tuple[list[str], int, int]`；
    可选 `trigger_characters: str`
  - Editor 追加：`set_autocomplete_provider(provider, tui: TUI)`——**防抖 + 取消 token 照 editor.ts**（`autocompleteDebounceTimer`/`autocompleteStartToken` 语义：新键入使旧请求作废）；触发时 `tui.show_overlay(SelectList(...))`（editor 直接持有 SelectList，照 createAutocompleteList）；Tab/上下/Enter/Esc 浮层开启时改道；选中经 `apply_completion` 回写
  - `EditorComponent(Protocol)`（editor_protocol.py）——**忠实对照 editor-component.ts 的可插拔面**（该文件存在的唯一目的是允许自定义编辑器实现，三原则同款）：`get_text()/set_text(s)/handle_input(data)/render/invalidate/focused` + 可选 hook `on_submit/on_change/add_to_history(s)/insert_text_at_cursor(s)/set_autocomplete_provider(...)/get_expanded_text()`（粘贴 marker 展开，Task 12；app 提交路径必须优先调它）；app 层依赖此 Protocol 而非具体 Editor
- Consumes: Task 10 SelectList、Task 8 overlay、Task 11/12

**上游规范源**：`editor.ts` 补全区段（约 2050-2150 行）+ `editor-component.ts`；`editor.test.ts` 补全域。

- [ ] **Step 1: [TEST-PORT] + [TEST]**：翻译 `Autocomplete` 域用例（editor.test.ts:2092 起，含防抖/取消语义）；另写浮层键改道、apply_completion 回写光标、Esc 关闭还焦、新键入作废旧请求（is_cancelled 早退）≥8 条。写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): editor autocomplete via overlay select list; editor protocol`

---

### Task 14: markdown.py（gfm-like + 扁平流→树适配 + 严格删除线）

**Files:**
- Create: `src/pipython/tui/components/markdown.py`
- Test: `tests/tui/components/test_markdown.py`、`tests/tui/components/fixtures/*.md`（≥6 个：标题层级/嵌套列表/围栏代码/引用/表格/混排中文加删除线加链接）

**Interfaces:**
- Produces: `Markdown(source: str, caps: TermCaps)`：render 输出 pi 风格 ANSI 行（样式常量表集中模块顶=pi 默认主题，注入位）；内部三段：`_parse(source) -> 扁平 token 流`（MarkdownIt("gfm-like") + 严格删除线 ruler 插件，语义对齐上游 StrictStrikethroughTokenizer——`~~` 紧贴不吃空格）→ `_build_tree(tokens) -> 嵌套节点`（**适配层**，表格重建成 header/rows 结构喂渲染）→ `_render_node`（逐节点对齐 markdown.ts 渲染规则）。
- Consumes: Task 1 utils、Task 2 term_caps、Task 7 Component

**上游规范源**：`markdown.ts`（858 行全量，重点 renderTable 686 行起与 StrictStrikethroughTokenizer 8-21 行）。

- [ ] **Step 1: [TEST] 金行测试**：每 fixture 渲 80 列断言关键行（标题反显、代码块底色行宽、表格对齐含 CJK 单元格、OSC-8 链接、严格删除线正反例 `~~x~~` vs `~~ x ~~`）。写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现三段。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): markdown component — gfm-like parse, tree adapter, pi-style ANSI`

---

### Task 15: autocomplete.py Provider 组 + completers 包装

**Files:**
- Create: `src/pipython/tui/components/autocomplete.py`
- Modify: `src/pipython/tui/completers.py`（**只追加**两个 Provider 包装类，不动现有 pt Completer——旧 TUI 存活约束）
- Test: `tests/tui/components/test_autocomplete_providers.py`

**Interfaces:**
- Produces: `PathProvider(file_list: Callable[[], Awaitable[list[str]]])`（`@` 触发；**异步桥接现有 `async def build_file_list`**——get_suggestions 本身就是 async，直接 await，配 is_cancelled 早退；engine.fuzzy 过滤）与 `CommandProvider(commands: dict[str,str])`（行首 `/` 触发，同步数据放进 async 契约即可）——均实现 Task 13 异步 `AutocompleteProvider`；`CombinedProvider([...])` 按触发优先取一。
- Consumes: Task 13 Protocol/AutocompleteItem、Task 5 fuzzy、现有 `build_file_list`（async）

**上游规范源**：`autocomplete.ts`（786 行，取 Provider 语义；pt 相关皮不移）。

- [ ] **Step 1: [TEST]**：`@` 中缀触发/路径含空格引用、`/` 仅行首、fuzzy 排序、apply 回写（光标落插入尾）≥10 条。写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: [PORT] 实现。** — [ ] **Step 4: 四道门。**
- [ ] **Step 5: Commit** `feat(tui): autocomplete providers over engine fuzzy`

---

### Task 16: app2.py 主循环 + commands 渲染双轨

**Files:**
- Create: `src/pipython/tui/app2.py`
- Modify: `src/pipython/tui/commands.py`——**工作量提示：不是纯包装**。现有五个 handler 直接内联 `ctx.console.print/rule`，其中 `_tree` 构造 rich Tree（dim/bold-green/← 叶标）。改法：`CommandContext` 增加可选 `sink: Sink | None = None`（`Sink(Protocol)`: `emit_text(s: str, style: str = "")`、`emit_lines(lines: list[str])`）；每个 handler 开头 `out = ctx.sink or RichSink(ctx.console)`，全部输出走 out；**`_tree` 需要新写一套纯 ANSI 树渲染**（├──/└── 前缀 + ANSI dim/bold-green + ← 叶标，输出 list[str] 走 emit_lines，rich Tree 路径保留在 RichSink 分支之外照旧）——sink 为 None 时行为与现状逐字节一致（旧 TUI 测试不许变红）
- Test: `tests/tui/test_app2.py`（FakeClient 驱动，RecordingTerm 断言）

**Interfaces:**
- Produces: `async run_app2(*, model: str, cwd: Path, client: ModelClient | None = None, term: TerminalIO | None = None) -> None`——组件树照 spec §6：会话区 Container（user 回显 Text/流式 Text 增量 invalidate→message_end 原地替换 Markdown/工具行 Text/错误红 Text）+ Loader + Editor 常驻底部；SIGINT 挂/收与 `[interrupted]`、Ctrl+C 清缓冲、Ctrl+D 空缓冲退出+session 横幅——语义与阶段二相同；**提交取文本走 `get_expanded_text()`**（粘贴 marker 展开，Task 12/13）；斜杠命令经 `Sink` 出组件。`term` 可注入（测试传 RecordingTerm 全程无真终端）。
- Consumes: Task 7/8 TUI、Task 9-15 组件、pipython 公开 API

- [ ] **Step 1: [TEST]**：FakeClient 两轮脚本驱动 run_app2（注入 RecordingTerm + 脚本化 stdin 帧）：断言流式期 Text 逐步增长、message_end 后屏上出现 markdown 渲染行、工具行出现、Ctrl+D 退出后 ops 含 session 横幅；deny/error 红行。≥8 条，写全。
- [ ] **Step 2: 确认失败。** — [ ] **Step 3: 实现（集成任务，无单一 PORT 源；spec §6 为规范）。** — [ ] **Step 4: 四道门（含旧 TUI 测试仍全绿）。**
- [ ] **Step 5: Commit** `feat(tui): new-engine app loop alongside legacy TUI`

---

### Task 17: e2e 迁移与新场景

**Files:**
- Modify: `src/pipython/tui/__init__.py`（加 `--engine {legacy,pi}` argparse 旗标，默认 legacy，pi 路由 app2）
- Test: 新增 `tests/e2e/test_tui_tmux_engine.py`。**`tests/e2e/test_tui_tmux.py` 全程一行不改**（默认引擎的 e2e 覆盖必须存活到 Task 18）。

**Interfaces:**
- Produces: 新 e2e 文件（旧文件零改动）：既有 5 场景对 `--engine=pi` **重写副本**进新文件 + 三条新场景（spec §7.4）：补全浮层出现并选中回写；**滚动历史保留**（三轮对话后 `capture -S -` 断言第一轮 user 回显仍在）；编辑器多行提交（Ctrl+J 组多行）。全部轮询式断言。

- [ ] **Step 1: 加 `--engine=pi` 旗标**（argparse choice，默认 legacy）。
- [ ] **Step 2: [TEST] 写新 e2e**（tmux_util 复用；每场景写全断言）。
- [ ] **Step 3: 跑 `uv run pytest tests/e2e/ -v` 两连全绿 + 四道门。**
- [ ] **Step 4: Commit** `test(tui): e2e for pi engine — overlay, scrollback preservation, multiline`

---

### Task 18: 切换默认、删旧码、依赖清理、README、CI

**Files:**
- Modify: `src/pipython/tui/__init__.py`（app2 成唯一路径，删旗标）、`pyproject.toml`（移除 prompt_toolkit/rich/rapidfuzz）、`README.md`、`.github/workflows/ci.yml`（无需新步骤，确认 `--extra tui` 覆盖新依赖）
- Delete: `src/pipython/tui/{app.py,keys.py,render.py}` 旧实现、`tests/tui/{test_app_helpers,test_render}.py` 等旧 UI 测试、e2e 旧集（新集更名顶替）；`app2.py` → `app.py`
- Test: 全量

**关键门槛：**
- 删除前核对：旧测试中的历史回归断言（issue #4 dim 样式等价物、/branch 头防护、deny 落盘等）已在新组件/新 e2e 有等价覆盖——逐条列对照表进报告（spec §3 要求）。
- README：TUI 章节重写（新键位表含 alt+enter 声明偏离与 Terminal.app 已知限制两条——Shift+Enter 不可区分、Alt+Enter 需开 "Use Option as Meta"；CJK 词移简化说明）。
- completers.py 删除 pt Completer 类，只留 Provider 与 build_file_list。

- [ ] **Step 1: 切默认+更名。** — [ ] **Step 2: 等价覆盖对照表（进报告）→ 删旧文件。** — [ ] **Step 3: 依赖移除+钉版核对+`uv sync --extra tui`。** — [ ] **Step 4: README/CI。** — [ ] **Step 5: 全量四道门 + e2e 两连。**
- [ ] **Step 6: Commit** `feat(tui)!: pi-tui engine becomes the only TUI; drop prompt_toolkit/rich/rapidfuzz`

---

### Task 19: [ACCEPTANCE] 维护者并排手感验收

- [ ] pi 与 pipython 同任务并排（维护者实际终端）；逐项过 spec §1 清单（编辑手感/流式/浮层/IME 候选窗/滚动历史），已声明差异不计入（spec §1 三条款）。
- [ ] 通过 → 台账收官；未通过 → 逐差异立 issue 回修。

---

## 验收核对清单（对照 spec rev 3）

- [ ] §1 验收 1-3（e2e 全绿 / CJK金标准 / 手感验收）→ Task 17、1、19
- [ ] §2 依赖表与钉版 → Task 1、18
- [ ] §3 布局全文件落位（含 select_list/terminal_colors/term_caps/editor_protocol/spacer）→ Task 2/5/9/10/13
- [ ] §4 引擎五要点 → Task 7/8
- [ ] §5 输入栈与键位裁决（含 alt+enter 声明偏离） → Task 3/4/5/6
- [ ] §6 组件与接线 → Task 9-16
- [ ] §7 测试策略四层 → Task 各 [TEST]/[TEST-PORT] + Task 17
- [ ] §8 旁路开发/末位删除 → Global Constraints + Task 16-18
- [ ] §9 风险防线逐条 → Task 1（宽度金标准）、5（CJK 词移）、7/8（tui.ts 差分核心独立拆分）、3（粘贴洪泛）、14（markdown 适配）、6+19（终端兼容矩阵：能力协商+维护者终端实测）、11-13（editor 体量与 editor.test.ts 4051 行按域分批）、19（IME 手动验收）
