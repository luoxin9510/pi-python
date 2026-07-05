# pi-python 阶段四设计：footer 状态栏（可用子集）

- 日期：2026-07-05
- 状态：范围经维护者选定（可用子集）；独立 subagent 审核后修订（rev 2：pwd/stats
  两独立行、Footer 持 app_state 应对 /clear、cwd 走 session.agent.cwd、usage dict
  camelCase 读取、read_branch 直读 HEAD+detached 保真、model 段纳入、git 生命周期
  try/finally、§1/§5 矛盾修正）
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
| cwd（`~` 缩写，`formatCwdForFooter` 语义） | `str(session.agent.cwd)` + `$HOME`（**注意**：`AgentSession` 无 `.cwd`；cwd 在 `session.agent.cwd`，是 `Path`，需 `str()`） |
| git 分支（`(branch)` 附在 cwd 后；detached 显示 `(detached)`） | 新 git provider（探测 + **轮询**） |
| model（当前模型 id） | `app_state.session.model`（现成 property，`/model` 命令已在用） |
| token `↑<input> ↓<output>`（`formatTokens` 千分位） | 遍历 `session.store.entries` 累加带 usage 的 assistant 条目 |
| cost `$<total>.3f` | 同上 `usage.cost` 累加（cost 可能为 None，跳过缺失项） |

**非目标（缺 SDK 数据，留白，记入 §6 follow-up）**：cache 读/写 token 与
CH 命中率（Usage 无 cache 分项）、context 百分比/窗口（SDK 不追踪 context
window）、`(sub)` 订阅标记（需 OAuth，阶段五）、session name（需 `/name`）、
auto-compact 指示（SDK 无自动压缩）、xp 指示。

## 2. 组件与数据源

### 2.1 `components/footer.py` — Footer 组件

实现引擎 `Component` 契约（`render(width) -> list[str]` / `invalidate()`）。

- 构造：`Footer(app_state, git: GitBranchProvider)`——**持 `app_state`（不是固定
  的 session 引用）**。理由（阻塞修复）：`/clear`（commands.py `_clear`）会整体
  替换 `app_state.session` 为全新 AgentSession（store 空、usage 归零）；footer 每
  次 render 读 `app_state.session`，从根上避免旧引用冻结 token/cwd。上游用
  `FooterComponent.setSession()`（footer.ts:59-61）达到同效；本移植改为读
  app_state 更简单、无需把 footer 实例穿透进 commands。
- `render(width) -> list[str]`（**两条独立行**，各自单独 truncate——对齐上游
  footer.ts 的 pwd 行与 stats 行互不竞争宽度，不做合并）：
  - `session = app_state.session`（每次现取）。
  - **行 1（pwd）**：`_format_cwd(str(session.agent.cwd), os.environ.get("HOME"))`
    （移植 `formatCwdForFooter`：在 HOME 内则 `~`/`~/rel`，否则原样）；git
    `current_branch` 非空则追加 ` (branch)`（detached 时 branch 值为
    `"detached"`，显示 `(detached)`）。dim 样式后
    `truncate_to_width(line, width, dim("..."))`。
  - **行 2（stats）**：累加 usage——遍历 `session.store.entries`，筛
    `isinstance(e, MessageEntry)` 且 `e.message.get("role") == "assistant"`，读
    `(e.message.get("usage") or {}).get("inputTokens"/"outputTokens"/"cost")`
    （**camelCase + dict 下标**，因 `MessageEntry.message` 是裸 dict、从不解析成
    AssistantMessage）。拼段：`↑{_format_tokens(input)}`、
    `↓{_format_tokens(output)}`（各自 >0 才加）；cost 累加>0 则 `${cost:.3f}`；
    末尾附 model 段 `session.model`。以 ` ` 分隔，dim 样式，独立
    `truncate_to_width`。
- 样式：dim（dimGray `#666666` → truecolor `\x1b[38;2;102;102;102m` +
  `\x1b[39m`，常量集中模块顶，引用 dark.json `dimGray`；同 select_list 挂
  `PHASE-4 REVISIT` 标记留 256 色回退位）。

`_format_tokens`（照上游 footer.ts:23-29 逐档，`Math.round` = Python `round`）：
`<1000` 原样；`<10000` `f"{c/1000:.1f}k"`；`<1_000_000` `f"{round(c/1000)}k"`；
`<10_000_000` `f"{c/1_000_000:.1f}M"`；否则 `f"{round(c/1_000_000)}M"`。

### 2.2 `components/git_branch.py` — GitBranchProvider

移植 `footer-data-provider.ts` 的 git 部分（**只要分支**，其余数据 footer 不
用）：

- `findGitPaths(cwd)`：从 cwd 向上找 `.git`（目录=普通仓库；文件=worktree，读
  `gitdir:` 指向）→ 得 `HEAD` 路径。移植上游 16-48 行逻辑。
- `read_branch(cwd) -> str | None`（照上游 footer-data-provider.ts:239-267 的
  真实数据流）：**主路径直读 `HEAD` 文件内容**——`ref: refs/heads/X` 前缀则
  返回 `X`；内容非该前缀（即 detached HEAD）返回字面 `"detached"`（footer 显示
  `(detached)`，保真上游语义，不返回 None）；仅当 HEAD 值是 `.invalid` 哨兵才
  回退 `git --no-optional-locks symbolic-ref --quiet --short HEAD`（subprocess，
  超时保护）。找不到 repo 返回 None。
- 监听：**Python 无 Node `watchFile`，用异步轮询**——`start(on_change)` 起一个
  asyncio 任务，按固定间隔（如 2s）`stat` HEAD 文件 mtime，变化则重读分支并
  回调 `on_change`；`stop()` 取消任务。去抖/refresh-in-flight 语义照上游
  `refreshTimer`/`refreshInFlight` 简化为"轮询+仅在分支值真变时回调"。
  （**声明偏离**：上游是 fs watch 事件驱动，本移植是轮询——原因见 §5。）
- `current_branch -> str | None`：缓存的最新值，footer.render 读它（不阻塞渲
  染）。

## 3. app 接线

`app.py` `run_app`：
- 构造 `git = GitBranchProvider(cwd)`；`footer = Footer(app_state, git)`。
- **root Container 结构**：`Container[transcript, loader_slot, editor, footer]`
  ——footer 在编辑器**下方**常驻（上游 `ui.addChild(footer)` 在末尾）。
- `git.start(on_change=lambda: tui.request_render())`。**生命周期（C2 修复）**：
  git provider 的构造+start 放进护住 setup 全程的 try/finally，finally 里
  `git.stop()`——防止 git.start 之后、其余 setup 中途抛异常导致轮询 asyncio 任务
  泄漏（现有 `_run` 末尾的 finally 范围不够，需扩大或另包一层）。
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
   `read_branch` 返回分支名；detached HEAD 返回 `"detached"`（显示 `(detached)`，
   非 None）；非 git 目录返回 None；
   worktree（`.git` 文件）解析。轮询监听：切分支后回调触发（有界等待，注入
   短轮询间隔，不裸 sleep）。
4. **app 接线测试**：FakeClient 两回合 + RecordingTerm，断言 footer 两行出现在
   底部、token 随回合累加、cwd/branch/model 段正确；**`/clear` 后 footer 归零/
   跟到新 session**（C1 回归：驱动 `/clear` 命令，断言 footer token 清零、cwd
   仍对——证明持 app_state 而非旧引用）。
5. **e2e**：给 test_tui_tmux.py 加一条——真实 pty 下 footer 显示 cwd（脚本仓库
   在 tmp git 下则含 branch），poll capture 断言；**窄终端下光标仍正确定位**
   （footer 多占 2 行不把编辑器光标挤出视口，C3）。

## 5. 风险/偏离

| 项 | 处理 |
|---|---|
| git 监听：轮询 vs 上游 fs watch | 声明偏离——Python 无跨平台等价的低开销 fs watch，轮询 2s stat HEAD mtime 足够（分支切换非高频）；mtime 无变化不回调，无渲染抖动。**已知例外**：reftable 后端下某些 ref 切换不 touch HEAD mtime（上游另监听 reftable 目录，本移植不做）——reftable 非默认后端，低概率，记 §6 |
| usage 读取路径 | `MessageEntry.message` 是裸 dict，永不解析成 AssistantMessage；用 dict 下标读 camelCase（inputTokens/outputTokens/cost），不是属性访问 |
| 主题 256 色回退 | 同 select_list：truecolor 固定 + PHASE-4 REVISIT 标记，theme 系统移植时统一 |
| pwd/stats 两行布局 | **两条独立行各自 truncate_to_width，不合并、不竞争宽度**（对齐上游 footer.ts 真实结构；上游 statsLeft/remainder 是 stats 行内部 token-左/model-右的分配，本子集 model 简单附在 stats 尾，不做左右对齐）；金行测试钉边界 |
| detached HEAD | 保真上游——返回 `"detached"` 显示 `(detached)`，不静默为 None |

## 6. Follow-up（缺 SDK 数据的字段，记 issue）

完整 footer 还需 SDK 侧支持：Usage 增 cache 读/写 token 分项 + CH 命中率；session
追踪 context window + getContextUsage（context 百分比段）；OAuth（`(sub)` 标记）；
`/name`（session name 段）；自动压缩指示；xp 指示；reftable 后端的 ref 监听。这些
随各自子系统在后续阶段补齐后，footer 再加对应段。
