# pi-python 阶段四设计：footer 状态栏（可用子集）

- 日期：2026-07-05
- 状态：范围经维护者选定（AskUserQuestion：可用子集）
- 上游：`packages/coding-agent/src/modes/interactive/components/footer.ts`(246) +
  `core/footer-data-provider.ts`(388)；基线同前 `21cb3807`（本地 `~/Developer/nukcole-pi`）
- 前置：阶段三 TUI 引擎已合入 main（PR #8）
- 追踪：GitHub issue #9

## 1. 背景与目标

维护者并排验收阶段三时点名：底部缺 pi 那条状态栏，是"最不像 pi"的点。本
设计移植 footer 的**可用子集**——只做 pipython SDK 现在能真实喂出数据的字段，
缺数据的字段留白（不伪造），对齐 pi 版式。

**做的字段**（数据源都已存在）：

| 字段 | 数据源 |
|---|---|
| cwd（`~` 缩写，`formatCwdForFooter` 语义） | `session.cwd` + `$HOME` |
| git 分支（`(branch)` 附在 cwd 后） | 新 git provider（探测 + fs 监听） |
| token `↑<input> ↓<output>`（`formatTokens` 千分位） | session entries 里 `AssistantMessage.usage.input_tokens/output_tokens` 累加 |
| cost `$<total>.3f` | 同上 `usage.cost` 累加（cost 可能为 None，跳过缺失项） |

**非目标（缺 SDK 数据，留白，记入 §6 follow-up）**：cache 读/写 token 与
CH 命中率（Usage 无 cache 分项）、context 百分比/窗口（SDK 不追踪 context
window）、`(sub)` 订阅标记（需 OAuth，阶段五）、session name（需 `/name`）、
auto-compact 指示（SDK 无自动压缩）、xp 指示。

## 2. 组件与数据源

### 2.1 `components/footer.py` — Footer 组件

实现引擎 `Component` 契约（`render(width) -> list[str]` / `invalidate()`）。

- 构造：`Footer(session: AgentSession, git: GitBranchProvider)`。
- `render(width)`：
  1. 累加 usage：遍历 `session.store.entries`，对 `type=="message"` 且
     `message.role=="assistant"` 且含 `usage` 的条目累加
     `input_tokens`/`output_tokens`/`cost`（cost 为 None 则不计）。**注意**：
     直接读磁盘 entry 的原始 dict（`usage.inputTokens` camelCase），或经
     session 已加载的模型——实现时对齐阶段一 session store 的既有读法。
  2. pwd 段：`_format_cwd(session.cwd, os.environ.get("HOME"))`（移植
     `formatCwdForFooter`：在 HOME 内则 `~`/`~/rel`，否则原样）；git 分支非空
     则追加 ` (branch)`。
  3. stats 段：`↑{_format_tokens(input)}`、`↓{_format_tokens(output)}`（各自
     >0 才加）；cost>0 则 `${cost:.3f}`。用 ` ` 或上游分隔符拼接。
  4. 样式：pwd 与 stats 全部走 `dim`（dimGray `#666666` → truecolor
     `\x1b[38;2;102;102;102m` + `\x1b[39m`，样式常量集中模块顶，引用 dark.json
     `dimGray`/theme.ts；与 select_list/markdown 同款 PHASE-4 REVISIT 标记留
     256 色回退位）。
  5. 超宽截断：`truncate_to_width(line, width, dim("..."))`（engine.utils）。
  6. 单行（上游 footer 可多行含 status；本子集只做 pwd+stats 合成的主行——
     若两段合并超宽则 stats 优先保留、pwd 截断，对齐上游 `statsLeft`/
     `remainder` 布局意图；具体两段布局照 footer.ts render 主行逻辑移植）。

`_format_tokens`（照上游逐档）：<1000 原样；<10000 `X.Xk`；<1e6 `Xk`（四舍
五入）；<1e7 `X.XM`；否则 `XM`。

### 2.2 `components/git_branch.py` — GitBranchProvider

移植 `footer-data-provider.ts` 的 git 部分（**只要分支**，其余数据 footer 不
用）：

- `findGitPaths(cwd)`：从 cwd 向上找 `.git`（目录=普通仓库；文件=worktree，读
  `gitdir:` 指向）→ 得 `HEAD` 路径。移植上游 16-45 行逻辑。
- `read_branch(cwd) -> str | None`：`git --no-optional-locks symbolic-ref
  --quiet --short HEAD`（`subprocess`，超时保护）；detached/无 git 返回 None。
- 监听：**Python 无 Node `watchFile`，用异步轮询**——`start(on_change)` 起一个
  asyncio 任务，按固定间隔（如 2s）`stat` HEAD 文件 mtime，变化则重读分支并
  回调 `on_change`；`stop()` 取消任务。去抖/refresh-in-flight 语义照上游
  `refreshTimer`/`refreshInFlight` 简化为"轮询+仅在分支值真变时回调"。
  （**声明偏离**：上游是 fs watch 事件驱动，本移植是轮询——原因见 §5。）
- `current_branch -> str | None`：缓存的最新值，footer.render 读它（不阻塞渲
  染）。

## 3. app 接线

`app.py` `run_app`：
- 构造 `git = GitBranchProvider(cwd)`；`footer = Footer(session, git)`。
- **root Container 结构**：`Container[transcript, loader_slot, editor, footer]`
  ——footer 在编辑器**下方**常驻（上游 `ui.addChild(footer)` 在末尾）。
- `git.start(on_change=lambda: tui.request_render())`；`run_app` 退出的
  finally 里 `git.stop()`。
- footer 需随 usage 变化刷新：每回合 `message_end`/`agent_end` 后
  `footer.invalidate()` + `tui.request_render()`（token/cost 更新）。git 分支
  变化经轮询回调触发 render。
- 非 TTY / 降级路径不变。

## 4. 测试

1. **Footer 组件单测**：给一个脚本化 session（store 里放带 usage 的 assistant
   entry），断言 render 输出精确金行——cwd `~` 缩写、`(branch)` 附加、
   `↑/↓` token 档位（各边界值）、`$cost`、dim 样式字节、超宽截断。
2. **_format_tokens/_format_cwd 纯函数**：逐档边界（999/1000/9999/10000/
   999999/…）与 HOME 内外/worktree 路径。
3. **GitBranchProvider**：真实 tmp git 仓库（`git init` + 建分支），
   `read_branch` 返回分支名；detached HEAD 返回 None；非 git 目录返回 None；
   worktree（`.git` 文件）解析。轮询监听：切分支后回调触发（有界等待，注入
   短轮询间隔，不裸 sleep）。
4. **app 接线测试**：FakeClient 两回合 + RecordingTerm，断言 footer 行出现在
   底部、token 随回合累加、cwd/branch 段正确。
5. **e2e**：给 test_tui_tmux.py 加一条——真实 pty 下 footer 显示 cwd（脚本仓库
   在 tmp git 下则含 branch），poll capture 断言。

## 5. 风险/偏离

| 项 | 处理 |
|---|---|
| git 监听：轮询 vs 上游 fs watch | 声明偏离——Python 无跨平台等价的低开销 fs watch，轮询 2s stat HEAD mtime 足够（分支切换非高频）；mtime 无变化不回调，无渲染抖动 |
| usage 读取路径 | 对齐阶段一 session store 既有读法（camelCase entry dict）；实现前先读 session/store.py 确认字段名 |
| 主题 256 色回退 | 同 select_list：truecolor 固定 + PHASE-4 REVISIT 标记，theme 系统移植时统一 |
| 两段布局超宽 | 照 footer.ts render 主行的 statsLeft/remainder 逻辑移植；金行测试钉边界 |

## 6. Follow-up（缺 SDK 数据的字段，记 issue）

完整 footer 还需 SDK 侧支持：Usage 增 cache 读/写 token 分项；session 追踪
context window + getContextUsage；OAuth（`(sub)`）；`/name`（session name）；
自动压缩指示。这些随各自子系统在后续阶段补齐后，footer 再加对应段。
