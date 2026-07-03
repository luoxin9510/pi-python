# pi-python 阶段二设计：交互式 TUI/CLI

- 日期：2026-07-03
- 状态：已由维护者逐段评审通过；已按独立 subagent 审核修订（rev 3：PR-0 前置(含 entry_type、AgentSession.model)、退出路径三条汇一、Live 清理；rev 2：PR-0 前置
  补丁、SIGINT 机制、中断分场景、补全边界/异步化、/clear 会话替换、/tree 摘要
  规则、FakeClient 脚本对齐、降级行为）
- 前置：阶段一 SDK（main @ `80e4ba6`，spec 见 `2026-07-03-pi-python-phase1-sdk-design.md`）
- 上游参照：`earendil-works/pi` 的 `packages/tui`（~12k 行 TS，自研差分渲染）与
  coding-agent 交互模式；本阶段**不逐行移植**，用 Python 生态等价重写

## 1. 目标与边界

**交付物：可用的交互式 CLI。** 装上 `pi-python[tui]` 后终端敲 `pipython` 即可与
coding agent 对话：流式回复、工具调用展示、多行编辑、Ctrl+C 中断、@ 文件补全、
/ 斜杠命令、markdown 富渲染、会话树导航（/tree + /branch）。

**明确非目标（YAGNI）：**
- 不承诺组件级公开 API（TUI 是 `pipython.tui` 私有实现；对外只有 `main()`）
- 不做全屏 alt-buffer 应用、不做交互式树浏览器
- 不移植 pi 的差分渲染器/自研编辑器/kitty 图片协议/主题系统
- 不做 extension/皮肤/配置文件系统——运行时可变项全走斜杠命令

**验收标准（§7 第 3 层）**：`uv add "pi-python[tui]"` 后在 sample repo 交互式让
agent 修复失败测试，全程流式/工具行/markdown 正常，`/tree` 可视化会话结构，
Ctrl+D 退出后终端滚动区保留完整对话、session 文件可读。

## 2. 关键决策（已拍板）

| 决策 | 选择 | 理由 |
|---|---|---|
| 渲染模型 | **混合模式**：对话流进终端滚动区（rich），仅底部输入区活动（prompt_toolkit） | 忠于 pi"不占屏"哲学：可回滚/可复制/退出留痕 |
| 依赖 | `prompt_toolkit`、`rich`、`rapidfuzz`、`pathspec`，**全部钉精确版**，挂 **optional extra `[tui]`** | 阶段一"SDK 仅两依赖"承诺不破；生产嵌入零负担 |
| 内部架构 | **薄事件循环应用**（方案 A）：无组件框架，TUI 只是 SDK 事件流的又一个订阅者/消费者 | 与 rich/pt 生态互补而非重造；顺带检验阶段一 API 完备性 |
| SDK 边界 | TUI **只 import `pipython` 公开 API**（含 `pipython.testing`）；需要伸手进内部即视为阶段一 API 缺口，先补 SDK 再继续 | 吃自己的狗粮 |

**已确认的阶段一 API 缺口（独立审核发现）→ 本阶段的前置补丁 PR-0**，先于一切
TUI 代码合入：

1. **导出 session 层公开符号**：`/tree`/`/branch` 需要而 `pipython.__init__`
   未导出的——`SessionStore`、`SessionHeader`、`MessageEntry`、
   `ModelChangeEntry`、`CompactionEntry`、`Entry`、`entry_id`、
   `entry_parent_id`、**`entry_type`（新增 helper，dict/模型双表示统一取
   type）**、`current_path`、`find_entry`。这些对生产用户审计会话同样有用，属
   正当公开面扩容。
1a. **导出消息类型与协议**（计划审核发现 TUI 生产代码必需）：
   `AssistantMessage`、`TextContent`、`ThinkingContent`、`ToolCallContent`、
   `ToolResultMessage`、`UserMessage`、`Usage`、`ModelClient`。
1b. **`AgentSession.model` 只读属性**（返回 `self.agent.model`）：`/model` 无
   参回显需要；初始模型不写 model_change entry、无法从 store 反推，且 `Agent`
   类型不公开——没有这个 getter 实现者只能违规伸手 `session.agent.model`。
2. **修 bash 工具的中止缺口（阶段一遗留 bug）**：`bash.py` 的 `os.killpg` 只挂
   在 `except asyncio.TimeoutError` 上；`task.cancel()`（本阶段 Ctrl+C 路径）
   抛的是 `asyncio.CancelledError`，现有代码不杀进程树、子进程变孤儿——违反阶
   段一 spec §6 "超时/**中止**须杀整棵进程树"。补
   `except asyncio.CancelledError: killpg; raise`，并配真实子进程测试（取消
   task 后断言进程组已死）。

## 3. 模块布局与打包

```
src/pipython/tui/           # 新增；全私有，只导出 main()
├── __init__.py             #   main()：参数解析 + 依赖检测 + 启动 app
├── app.py                  #   主循环：会话生命周期 + 输入/输出回合交替
├── render.py               #   SDK 事件流 → rich Console 输出
├── completers.py           #   @路径 + /命令补全（prompt_toolkit Completer 协议）
├── commands.py             #   Command 注册表 + 6 个内置命令
└── keys.py                 #   KeyBindings 装配
tests/tui/                  #   单元测试（补全/命令/渲染）
tests/e2e/test_tui_tmux.py  #   tmux 驱动真实交互测试
```

**pyproject.toml 增量：**

```toml
[project.optional-dependencies]
tui = [  # 实现时以 uv 解析结果钉 == 精确版
    "prompt_toolkit==<pin>", "rich==<pin>", "rapidfuzz==<pin>", "pathspec==<pin>",
]

[project.scripts]
pipython = "pipython.tui:main"
```

- `main()` 启动时 try-import 四件套，缺失则打印一行
  `pip install "pi-python[tui]"` 提示后 `sys.exit(1)`，不 traceback
- CLI 参数极简：`pipython [--model <litellm-id>] [--cwd <path>]`；默认
  model 取 `PI_PYTHON_MODEL` 环境变量，再默认 `anthropic/claude-sonnet-5`
- 测试钩子：环境变量 `PI_PYTHON_FAKE_SCRIPT=<json路径>` 存在时，app 用
  `pipython.testing.FakeClient`（脚本从 JSON 反序列化为 AssistantMessage 列表）
  替代真实 client——"唯一允许的 LLM 替身"原则在 CLI 层的延伸

## 4. 主循环与渲染

**回合制主循环**（输入期/输出期不重叠，无需 patch_stdout）：

```python
try:
    while True:
        try:
            text = await prompt_session.prompt_async(...)   # 输入期
        except EOFError:            # Ctrl+D（空缓冲）→ 退出
            break
        if text.startswith("/"):
            await dispatch(text)
            if app.should_quit:     # /quit handler 置位，此处检查跳出
                break
            continue
        task = asyncio.create_task(consume(app.session.prompt(text)))  # 输出期
        loop.add_signal_handler(signal.SIGINT, task.cancel)  # 关键机制，见下
        try:
            await task
        except asyncio.CancelledError:
            console.print("[interrupted]")
        finally:
            loop.remove_signal_handler(signal.SIGINT)
except KeyboardInterrupt:
    pass  # handler 摘除后到 pt 重新接管前的窄窗口兜底，不留 traceback
finally:
    console.print(f"session: {app.session.store.path}")   # 退出统一出口
```

- **退出路径三条汇一**：Ctrl+D → `EOFError` → break；`/quit` →
  `app.should_quit=True` → break；窄窗口 SIGINT → 最外层兜底。session 文件路
  径在统一出口打印。
- `consume()` 内的 `rich.Live` 必须用 `with` 上下文管理——取消时
  `CancelledError` 穿出也能保证 `__exit__` 恢复光标/清行，Ctrl+C 后终端不残留
  半个预览区。

**SIGINT 机制（Ctrl+C 承诺的地基，显式规定）**：输出期没有 prompt_toolkit 在
跑，默认 SIGINT 会以 `KeyboardInterrupt` 炸穿事件循环的同步栈、**注入不到协程
的 await 点**——所以必须用 `loop.add_signal_handler(SIGINT, task.cancel)` 让取
消走 Task 机制正确传入嵌套的 SDK async generator。输出期结束即移除 handler，
把 SIGINT 交还给输入期的 prompt_toolkit。**平台边界：阶段二仅支持 POSIX**
（`add_signal_handler` 限制；Windows 支持列入后续，pi 上游同样以 POSIX 为主）。

- 主循环从 `app.session` 读会话引用而**不是**局部变量——`/clear` 等命令替换会
  话的机制（见 §6）。

**流式渲染——"尾部实时、完稿重排"：**
- 输出期用 `rich.Live` 维护 **≤8 行尾部预览**（spinner + 正在生成文本的最后几
  行，原样无格式）；不把半成品刷进滚动区
- `message_end`：清 Live，把完整 assistant 文本用 `rich.Markdown` 一次性渲染进
  滚动区（代码块语法高亮/列表/表格）
- 依据：Live 区超过屏高即无法可靠擦除——pi 用 1714 行自研差分渲染解决；本设计
  用尾部预览绕开，这是选四件套而非移植 tui.ts 的核心权衡
- `tool_call`：一行青色摘要（工具名 + 参数 JSON 截断 ~100 字符）
- `tool_result`：仅 `is_error=True` 打红色一行（截断）
- `agent_end`：reason != "done" 时黄色提示（max_turns / error / 中断）
- thinking：不展示内容（SDK 事件层本就无 thinking 增量），Live spinner 文案在
  收到首个 text_delta 前显示 "thinking…"

**中断语义（分场景，不许含糊）：**
- 输出期 Ctrl+C → `task.cancel()` → async generator 关闭。**已被消费者看到的事
  件**（message_end/tool_result）其落盘先于 yield，已写盘不丢。
- **工具执行中被中断**：该次未完成的工具调用**不产生 tool_result、不落盘**；
  bash 子进程由 PR-0 的 `CancelledError → killpg` 保证被杀（依赖前置补丁）。
- deny 产生的 `ToolResult(is_error=True)` 复用 §4 的红色渲染路径，无需特判。
- 输入区 Ctrl+C：清空当前缓冲；**Ctrl+D 沿用 prompt_toolkit 默认 readline 语
  义**（空缓冲 = EOF 退出，非空 = 删除光标处字符），退出时打印 session 文件路
  径，无需自定义绑定。

## 5. 补全与键位

**@ 路径补全**：片段边界规则明确为——**从光标向左扫描，遇到最近的 `@` 停止，
`@` 与光标之间不含空白/换行即视为活动片段**（正则：光标前文本匹配
`@([^\s@]*)$`）；含空格的路径不支持模糊触发（可手输）。候选 =
`rapidfuzz.process.extract(片段, 文件列表, limit=10)`；选中插入相对路径。
文件列表：git 仓库用 `git ls-files --cached --others --exclude-standard`（快、
gitignore 天然生效）；非 git 目录降级 `os.walk` + **pathspec** 解析
`.gitignore`。**列表刷新不得阻塞事件循环**——子进程用
`asyncio.create_subprocess_exec`、os.walk 走 `run_in_executor`；每次 prompt 懒
刷新，上限 5000 条。

**/ 命令补全**：行首 `/` 触发，候选来自命令注册表，`display_meta` 显示描述。

**键位**（`keys.py` 只是薄装配层）：Enter 提交；Alt+Enter / Ctrl+J 换行；
↑/↓ 历史（`FileHistory` → `~/.pi-python/tui-history`）；Ctrl+R 反向搜索；
Emacs 系（Ctrl+A/E/K/Y/W、Alt+F/B）全部用 prompt_toolkit 内置——pi 手写的
kill-ring/word-navigation/undo-stack 在 pt 里是自带能力，不重写。

## 6. 斜杠命令

注册表 = dict + 普通函数（自由 harness 原则贯到 UI 层，不发明插件机制）：

```python
@dataclass(frozen=True)
class Command:
    name: str
    description: str
    handler: Callable[[CommandContext, str], Awaitable[None]]  # (ctx, 参数串)
```

`CommandContext`：`console`（rich）、`app`（**可变应用态，持有 `session` 引
用**——主循环每轮从 `app.session` 读；`/clear` 只需
`ctx.app.session = await create_agent_session(...)`，旧对象随 GC 走，其 JSONL
文件保留在磁盘）。

| 命令 | 行为 |
|---|---|
| `/help` | 列出注册表（名字 + 描述） |
| `/model [id]` | 无参显示当前；有参 `app.session.set_model(id)` |
| `/clear` | `app.session` 替换为新会话（新 JSONL），滚动区打分隔线 |
| `/tree` | `rich.Tree` 渲染 `store.entries`；当前路径高亮、叶子标 `←` |
| `/branch <id前缀>` | 唯一前缀匹配 → `session.branch(id)`；歧义/无匹配报错 |
| `/quit` | 请求退出（同 Ctrl+D） |

**/tree 与 /branch 的实现规则（消除歧义）：**
- entry 遍历一律用 PR-0 导出的 `entry_id()`/`entry_parent_id()` 访问——
  `store.entries` 混有 Pydantic 模型与**裸 dict**（未知类型透传，阶段一 §5.3），
  直接 `.id` 会在 dict 上崩，前缀匹配必须兼容两种表示。
- 节点摘要提取规则：`MessageEntry.message` 是裸 dict——role=user 且 content 为
  str 时直接截 50 字符；content 为数组时取**首个 `text` block** 截 50 字符；纯
  工具调用的 assistant 消息显示 `[tool: <首个 toolCall 的 name>]`；非 message
  类型显示其 `type`（如 `model_change → deepseek-chat`）。
- 当前路径 = PR-0 导出的 `current_path(store.entries, store.leaf_id)`。

未知命令：红色一行 + 提示 `/help`。

## 7. 测试策略

1. **单元测试**（pytest，真实文件系统，无 mock）：
   - completers：tmp_path 造真实 git 仓库与 .gitignore，断言模糊排序与过滤
     （git 路径 + 非 git 降级路径都测）
   - commands：`CommandContext` + **FakeClient 驱动的真 session**（复用
     `pipython.testing`），断言 /model /branch /tree 对 session 的真实效果
   - render：`rich.Console(record=True)` 捕获，断言 markdown 重排/工具行/错
     误行的输出文本
2. **tmux e2e**（pi 同款）：脚本真启动 `pipython`（注入
   `PI_PYTHON_FAKE_SCRIPT`），`tmux send-keys` 输入、`capture-pane` 断言：流
   式预览出现、完稿 markdown 重排、工具行、`/tree` 树形、Ctrl+C 中断回输入
   区、Ctrl+D 退出留痕。CI 安装 tmux 执行。
   **FakeClient 脚本对齐规则**：JSON 文件是 `AssistantMessage` 数组（camelCase
   字段，经 `model_validate` 反序列化，Pydantic union 按 content block 的
   `type` 匹配）；**脚本条数 = LLM 调用次数（≠工具调用次数）**——一轮
   "text+toolCall → 工具真实执行 → 收尾 text" 消耗 2 条脚本。示例（修一次文
   件的 e2e 剧本 = 2 条）：`[{content:[{type:"toolCall",id:"t1",name:"edit",
   arguments:{...}}]}, {content:[{type:"text",text:"done"}]}]`。工具是**真实执
   行**的，脚本里的 edit/bash 参数必须与 tmux 沙箱仓库的真实状态对齐。
   tmux pane 环境 `console.is_terminal` 为 True（tmux 提供 pty），e2e 走的是
   正常渲染路径而非降级分支——用例断言前先以一条探针输出验证这一点。
3. **真实 API 验收**（维护者在场）：见 §1 验收标准。

## 8. 工程增量

- CI：矩阵增加 `uv sync --extra tui` + `apt-get install tmux`；e2e job 跑
  tmux 测试
- README：TUI 章节（安装 extra、`pipython` 用法、斜杠命令表）
- 四件套依赖以 uv 实际解析结果钉 `==` 精确版（阶段一同规矩）

## 9. 风险与后续

- **SIGINT 机制是 UX 承诺的地基**（§4 已显式规定 `add_signal_handler` 方案）：
  实现时先写通中断的 tmux 用例再扩其余功能，避免地基问题后置返工。
- **PR-0 是硬前置**：bash 中止杀进程树的缺口不修，Ctrl+C 会产生孤儿进程；SDK
  导出不补，`/tree`/`/branch` 只能违规伸手进内部。PR-0 必须先合入并过审。
- **终端兼容性/降级行为**：`console.is_terminal` 为 False（管道/哑终端）时跳
  过 Live 尾部预览，text_delta 静默累积，仅在 `message_end` 一次性打印完整
  markdown（工具行/错误行照打）——降级分支有专门单测；tmux 有 pty 不走此分支。
- **tmux e2e 有 flaky 前科**（上游同款套件即如此）：断言基于"轮询 capture-pane
  直到出现/超时"而非固定 sleep；预留去 flaky 的调试时间，里程碑估算不要按一次
  写通计。
- **平台**：阶段二仅 POSIX（macOS/Linux）；Windows 列入后续。
- 后续（非本阶段）：交互式树浏览器、主题、图片渲染、`AgentSession.open()`
  resume 接入 TUI（依赖阶段二之后的 SDK resume 能力）、Windows 支持。
