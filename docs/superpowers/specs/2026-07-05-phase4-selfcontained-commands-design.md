# pi-python 阶段四设计：自足斜杠命令（第一批）

- 日期：2026-07-05
- 状态：范围经维护者选定；独立审核后修订（rev 2：**彩蛋整体移出本批**——它们是位图
  渲染器非 ASCII 字串、/dementedelves 需图片组件基建且含上游公司真实公告不宜搬入；
  /copy 与 /session 改分支感知；/hotkeys 方向纠正+格式化函数；剪贴板加 OSC 52 兜底）。
  **本批 5 条真命令**：/hotkeys /new /copy /session /changelog
- 上游：`packages/coding-agent/src/modes/interactive/interactive-mode.ts`（各 handler）+
  基线同前
- 前置：footer 已合入 main（PR #12）；issue #10 的第一档
- 追踪：issue #10

## 1. 背景与目标

移植 pi 剩余 24 命令里**无 SDK 依赖**的第一批，接进 pipython 现有命令注册机制。
本批 5 条命令，全部数据源已在 pipython SDK/引擎里。

| 命令 | 行为 | 数据源 |
|---|---|---|
| `/hotkeys` | 渲染键位帮助表 | `engine.keybindings.DEFAULT_EDITOR_BINDINGS`（含 Ctrl+O `app.tools.expand`）+ 硬编码 Ctrl+C/D |
| `/new` | 开新会话（**= `/clear`**：上游 `/new` 直接调 `handleClearCommand`；pipython 保留当前模型） | `app.make_session()`（复用 `/clear` 逻辑） |
| `/copy` | 复制最后一条助手文本到剪贴板 | 当前分支最后一条 assistant message + 剪贴板 util |
| `/session` | 会话统计（消息数/工具调用/token↑↓/cost） | 当前分支路径累加 |
| `/changelog` | 显示版本 + 仓库链接（**pipython 无 CHANGELOG 文件，不伪造**） | `pipython.__version__` |

**非目标**：需 SDK 补数据的命令（`/name` 需会话命名、`/compact` 需 summary 生成、
`/fork` 需 forkFrom、`/export` 大导出、`/resume`/`/session-selector` 需历史回放、
`/settings`/`/login`/`/logout`/`/trust`/`/reload`/`/scoped-models` 需各子系统）——
后续子项目。

## 2. 现有机制（已核实）

`src/pipython/tui/commands.py`：
- `Command(name: str, description: str, handler: Callable[[CommandContext, str], Awaitable[None]])`
- `CommandContext`（`@dataclass`）：`app`（AppState，`app.session`/`app.make_session`）、
  `sink: Sink`。
- `Sink` Protocol：`emit_text(s: str, style: str = "")`、`emit_lines(lines: list[str])`。
- `build_registry() -> dict[str, Command]`：现注册 6 命令（help/model/clear/tree/branch/quit）。
- `dispatch(registry, ctx, line)`：解析 `/name args`、查表、未知→红字+`/help` 提示。

本批只**新增 handler + 注册项**，不改 dispatch/Sink/CommandContext 骨架。

## 3. 各命令实现

### 3.1 `/hotkeys` — `_hotkeys(ctx, _)`
渲染键位帮助。**注意 `DEFAULT_EDITOR_BINDINGS` 的方向是 `action 名 → key_id(s)`**
（`engine/keybindings.py:67`，如 `"tui.editor.cursorLeft": ["left","ctrl+b"]`），不是
反的。做法**照上游 handleHotkeysCommand（interactive-mode.ts:5478 起）**：对一份写死
的 action 名清单**逐个查表**、手工分组进板块（导航/编辑/历史/补全），不是遍历整表自
动分类。需新写一个 **key 显示格式化函数**（pipython 现无）：`ctrl+b`→`Ctrl+B`、多 key
用 `/` 拼、macOS 上 `alt`→`Option`（对齐上游 `formatKeyText`/`keyDisplayText`）。
`Ctrl+O`（工具展开）**在表里**（`app.tools.expand`，Task 19 已从裸字节改为走表）；
`Ctrl+C`/`Ctrl+D` 不在表里，是 `app.py` `_on_stdin_frame` 里的裸字节判断——这两条单独
硬编码进帮助文案即可。收窄理由：上游 "Other"
分区约 13 条 app 绑定（interrupt/suspend/thinking 切换/模型循环/externalEditor 等）对
应的 pipython 功能多未实现，本批只列已实现的键。渲染成 `list[str]`（dim 标题 + `key —
action` 行），经 `ctx.sink.emit_lines`。

### 3.2 `/new` — `_new(ctx, _)`
**与 `/clear` 同实现**（上游 `/new`===`/clear`）。直接复用 `_clear` 的 body（`ctx.app.session
= await ctx.app.make_session()` + 分隔提示），或让 `/new` handler 调 `_clear`。保留当前
模型（承接 pipython `/clear` 语义）。

### 3.3 `/copy` — `_copy(ctx, _)`
- 取最后一条 assistant 文本（**分支感知 + 单条目语义**）：用
  `current_path(session.store.entries, session.store.leaf_id)`（`engine`/`session.tree`
  的既有函数，`_tree`/`_branch` 在用）取当前分支路径，**反向找第一条**
  `type=="message"` 且 `message["role"]=="assistant"` 的 entry，拼接其
  `message["content"]` 里 `type=="text"` 块的 `text`。**只看这一条**——拼出为空
  （纯 toolCall/无 text）即视为"无消息"，**不继续向前找**（对齐上游
  `getLastAssistantText` 的单条语义；pipython 无 `stop_reason`/`aborted` 字段，不做
  aborted 判断）。无 assistant 或拼出空 → `emit_text("No agent messages to copy
  yet.", 红)`。
- 剪贴板 util（`src/pipython/tui/components/clipboard.py`，零新依赖）：`copy_to_clipboard(text)
  -> None`，按平台探测——macOS `pbcopy`、Wayland `wl-copy`、X11 `xclip -selection clipboard`
  /`xsel`；`subprocess` 管道写入。**OSC 52 远程兜底（对齐上游 clipboard.ts）**：检测到
  远程会话（`SSH_CONNECTION`/`SSH_TTY`/`MOSH_CONNECTION` 环境变量）或本地工具全不可用
  时，退到写 OSC 52 序列（`\x1b]52;c;<base64(text)>\x07` 到 stdout，纯 stdlib base64）
  而非直接报错——SSH 场景常见。全部路径失败才 raise。成功 `emit_text("Copied last
  agent message to clipboard", dim)`，异常 `emit_text(<msg>, 红)`。

### 3.4 `/session` — `_session(ctx, _)`
统计**当前分支路径**（`current_path(session.store.entries, session.store.leaf_id)`，
分支感知，非裸 `store.entries`——对齐上游基于 `this.messages` 物化数组的分支语义）：
user/assistant/toolResult 消息数；assistant 里 `content` 的 `type=="toolCall"` 计 tool
calls；`usage` 累加 `inputTokens`/`outputTokens`/`cost`（camelCase dict，同 footer）。
空会话（只有 header）时各计数自然为 0。渲染成信息块（`Session Info` 粗体标题 + 各行），
经 `emit_lines`。字段对齐上游 `getSessionStats`（cache 分项 pipython 无，略）。

### 3.5 `/changelog` — `_changelog(ctx, _)`
pipython 无 CHANGELOG 文件——**不伪造**。渲染 `pi-python <__version__>` +
`https://github.com/luoxin9510/pi-python` + 一句"full history in git log / releases"。
（若日后加 CHANGELOG.md 再改读文件；记 §5。）

### 3.6 彩蛋 — 移出本批（见 §6）

上游 `/arminsayshi`（`armin.ts`）与 `/dementedelves`（实为 `earendil-announcement.ts`，
非 `daxnuts.ts`）都不是 ASCII 字串，而是程序化位图/图片渲染器；`/dementedelves` 还依赖
pipython 没有的终端图片渲染组件，且其内容是上游作者公司的具体真实公告（不宜原样搬入无关
下游）。本批不做，留待后续（详见 §6）。

## 4. 测试

1. **各 handler 单测**（`tests/tui/test_commands_selfcontained.py`）：用一个记录型 sink
   stub（收集 emit_text/emit_lines）+ 轻量 app_state/session stub 驱动每个 handler，断言
   输出内容——`/hotkeys` 含关键键位行且格式化正确（`Ctrl+B` 非 `ctrl+b`）；`/new` 换了
   session（app.session 变新对象）；`/copy` 取对当前分支最后一条 assistant 文本、纯
   toolCall/无消息时红字、`/branch` 回旧节点后取的是路径上的而非物理最后一条；`/session`
   统计数正确（含 tool calls 与 token 累加、空会话全 0）；`/changelog` 含版本号与仓库链
   接。
2. **clipboard util 单测**：monkeypatch subprocess + OSC 52 路径，断言按平台选对命令、写
   入正确 stdin、SSH 环境走 OSC 52、全不可用时 raise；成功/失败路径。**真实剪贴板不测**
   （CI 无显示环境）。**⚠️ CLAUDE.md "实际测试优先" 明写"不 mock 子进程"——此处 mock
   subprocess 是对该硬规则的例外，理由是 headless CI 无 pbcopy/xclip/剪贴板设备，须经维护
   者认可。** OSC 52 那条不涉及子进程（纯 stdout 写），可真实断言输出字节。
3. **注册测试**：`build_registry()` 含全部 5 新命令 + 原 6（共 11），`/help` 列全。
4. **e2e（可选，1 条）**：tmux 下发 `/hotkeys`，poll capture 断言键位帮助出现；发
   `/session` 断言统计出现。（彩蛋/copy 不进 e2e——copy 需剪贴板环境。）

## 5. 风险/偏离

| 项 | 处理 |
|---|---|
| `/new` == `/clear` 冗余 | 上游即如此（`/new` 调 `handleClearCommand`），保真移植；`/help` 里两条描述可区分措辞 |
| `/changelog` 无源 | 显示版本+链接，不伪造 changelog；有 CHANGELOG.md 后再改（follow-up） |
| 剪贴板跨平台 | 探测 pbcopy/wl-copy/xclip/xsel → OSC 52 远程/兜底 → 全失败才报错（非静默） |
| session name 段 | `/session` 的 name 行略（需 `/name` SDK 支持，后续子项目） |

## 6. Follow-up
- **彩蛋**：`/arminsayshi` 需移植 armin 的位图→半块字符终帧渲染（`getPixel`/`getChar`/
  终态网格；不需图片协议，可作独立小项目）；`/dementedelves` 需先有终端图片渲染组件
  （重量级基建），且原上游内容（公司公告+PNG）不宜搬入——若做，换成 pi-python 自己原创
  的内容。
- CHANGELOG.md 落地后 `/changelog` 改读文件。
- `/session` 补 name 段（随 `/name` SDK 支持）与 cache 分项（随 Usage 扩展）。
- 第二批命令（`/name` `/compact` `/fork` 等）各自子项目。
