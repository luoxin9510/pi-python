# pi-python 阶段四设计：自足斜杠命令（第一批）

- 日期：2026-07-05
- 状态：范围经维护者选定（全部 6 条 + 彩蛋）
- 上游：`packages/coding-agent/src/modes/interactive/interactive-mode.ts`（各 handler）+
  `components/{armin,daxnuts}.ts`（彩蛋，MIT，随移植合法复制）；基线同前
- 前置：footer 已合入 main（PR #12）；issue #10 的第一档
- 追踪：issue #10

## 1. 背景与目标

移植 pi 剩余 24 命令里**无 SDK 依赖**的第一批，接进 pipython 现有命令注册机制。
本批 7 条命令（含 2 彩蛋），全部数据源已在 pipython SDK/引擎里。

| 命令 | 行为 | 数据源 |
|---|---|---|
| `/hotkeys` | 渲染键位帮助表 | `engine.keybindings.DEFAULT_EDITOR_BINDINGS` + app 级 Ctrl+O |
| `/new` | 开新会话（**= `/clear`**：上游 `/new` 直接调 `handleClearCommand`；pipython 保留当前模型） | `app.make_session()`（复用 `/clear` 逻辑） |
| `/copy` | 复制最后一条助手文本到剪贴板 | store 里最后一条 assistant message + 剪贴板 util |
| `/session` | 会话统计（消息数/工具调用/token↑↓/cost） | `session.store.entries` 累加 |
| `/changelog` | 显示版本 + 仓库链接（**pipython 无 CHANGELOG 文件，不伪造**） | `pipython.__version__` |
| `/arminsayshi` | 彩蛋 ASCII 艺术 | 移植 `armin.ts` |
| `/dementedelves` | 彩蛋 ASCII 艺术 | 移植 `daxnuts.ts` |

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
渲染键位帮助：遍历 `DEFAULT_EDITOR_BINDINGS`（`engine.keybindings`，key_id→action
名）分组成 pi `handleHotkeysCommand` 的板块（导航/编辑/历史/补全），外加 app 级
`Ctrl+O`（工具展开）、`Ctrl+C`/`Ctrl+D`。渲染成 `list[str]`（dim 标题 + `key —
action` 行），经 `ctx.sink.emit_lines`。分组与文案对齐上游 handleHotkeysCommand
（interactive-mode.ts:5478 起）。

### 3.2 `/new` — `_new(ctx, _)`
**与 `/clear` 同实现**（上游 `/new`===`/clear`）。直接复用 `_clear` 的 body（`ctx.app.session
= await ctx.app.make_session()` + 分隔提示），或让 `/new` handler 调 `_clear`。保留当前
模型（承接 pipython `/clear` 语义）。

### 3.3 `/copy` — `_copy(ctx, _)`
- 取最后一条 assistant 文本：反向遍历 `session.store.entries`，找 `type=="message"`
  且 `message["role"]=="assistant"` 的条目，从其 `message["content"]` 里拼接
  `type=="text"` 块的 text（跳过纯 toolCall/空内容——对齐上游 `getLastAssistantText`
  跳过 aborted 空消息）。无则 `emit_text("No agent messages to copy yet.", 红)`。
- 剪贴板 util（`src/pipython/tui/components/clipboard.py`，零新依赖）：`copy_to_clipboard(text)
  -> None`，按平台探测——macOS `pbcopy`、Wayland `wl-copy`、X11 `xclip -selection clipboard`
  /`xsel`；`subprocess` 管道写入，全不可用则 raise。成功 `emit_text("Copied last agent
  message to clipboard", dim)`，异常 `emit_text(<msg>, 红)`。

### 3.4 `/session` — `_session(ctx, _)`
遍历 `session.store.entries` 统计：user/assistant/toolResult 消息数；assistant 里
`content` 的 `type=="toolCall"` 计 tool calls；`usage` 累加 `inputTokens`/`outputTokens`/
`cost`（camelCase dict，同 footer）。渲染成信息块（`Session Info` 粗体标题 + 各行），经
`emit_lines`。字段对齐上游 `getSessionStats`（cache 分项 pipython 无，略）。

### 3.5 `/changelog` — `_changelog(ctx, _)`
pipython 无 CHANGELOG 文件——**不伪造**。渲染 `pi-python <__version__>` +
`https://github.com/luoxin9510/pi-python` + 一句"full history in git log / releases"。
（若日后加 CHANGELOG.md 再改读文件；记 §5。）

### 3.6 彩蛋 `/arminsayshi` `/dementedelves`
移植上游 `armin.ts`（382）与 `daxnuts.ts`（164）的 ASCII 艺术为 Python 字符串常量
（`src/pipython/tui/components/easter_eggs.py`），handler 经 `emit_lines` 输出。**逐字符
照搬上游艺术内容**（MIT，随移植合法）；若上游是动画/多帧，取静态首帧即可（本批不做动画）。

## 4. 测试

1. **各 handler 单测**（`tests/tui/test_commands_selfcontained.py`）：用一个记录型 sink
   stub（收集 emit_text/emit_lines）+ 轻量 app_state/session stub 驱动每个 handler，断言
   输出内容——`/hotkeys` 含关键键位行；`/new` 换了 session（app.session 变新对象）；
   `/copy` 取对最后一条 assistant 文本、无消息时红字；`/session` 统计数正确（含 tool
   calls 与 token 累加）；`/changelog` 含版本号与仓库链接；彩蛋非空且含标志性行。
2. **clipboard util 单测**：monkeypatch subprocess，断言按平台选对命令、写入正确 stdin、
   全不可用时 raise；成功/失败路径。**真实剪贴板不测**（CI 无显示环境）——这是本任务唯一
   允许 mock 的边界（subprocess）。
3. **注册测试**：`build_registry()` 含全部 7 新命令 + 原 6，`/help` 列全。
4. **e2e（可选，1 条）**：tmux 下发 `/hotkeys`，poll capture 断言键位帮助出现；发
   `/session` 断言统计出现。（彩蛋/copy 不进 e2e——copy 需剪贴板环境。）

## 5. 风险/偏离

| 项 | 处理 |
|---|---|
| `/new` == `/clear` 冗余 | 上游即如此（`/new` 调 `handleClearCommand`），保真移植；`/help` 里两条描述可区分措辞 |
| `/changelog` 无源 | 显示版本+链接，不伪造 changelog；有 CHANGELOG.md 后再改（follow-up） |
| 彩蛋动画 | 上游若多帧，本批取静态首帧；动画留 follow-up |
| 剪贴板跨平台 | 探测 pbcopy/wl-copy/xclip/xsel，全无则明确报错（非静默） |
| session name 段 | `/session` 的 name 行略（需 `/name` SDK 支持，后续子项目） |

## 6. Follow-up
CHANGELOG.md 落地后 `/changelog` 读文件；彩蛋动画；`/session` 补 name 段与 cache 分项
（随 SDK 能力）。第二批命令（/name /compact /fork 等）各自子项目。
