# pi-python 阶段二设计：交互式 TUI/CLI

- 日期：2026-07-03
- 状态：已由维护者逐段评审通过
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
while True:
    text = await prompt_session.prompt_async(...)   # 输入期
    if text.startswith("/"): await dispatch(text); continue
    task = asyncio.create_task(consume(session.prompt(text)))  # 输出期
    await task   # Ctrl+C → task.cancel() → SDK generator 关闭
```

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

**中断语义：**
- 输出期 Ctrl+C → `task.cancel()` → async generator 关闭；已产生的消息/工具结
  果已由 SDK 订阅者落盘不丢；打印 `[interrupted]` 回输入区
- 输入区 Ctrl+C：清空当前缓冲；Ctrl+D（空缓冲）：退出并打印 session 文件路径

## 5. 补全与键位

**@ 路径补全**：光标前存在未闭合 `@片段` 触发；候选 =
`rapidfuzz.process.extract(片段, 文件列表, limit=10)`；选中插入相对路径。
文件列表：git 仓库用 `git ls-files --cached --others --exclude-standard`（快、
gitignore 天然生效）；非 git 目录降级 `os.walk` + **pathspec** 解析
`.gitignore`。每次 prompt 懒刷新，上限 5000 条。

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

`CommandContext`：`session`（AgentSession）、`console`（rich）、`app`（可变应
用态，如"请求退出"标志、当前 model 显示名）。

| 命令 | 行为 |
|---|---|
| `/help` | 列出注册表（名字 + 描述） |
| `/model [id]` | 无参显示当前；有参 `session.set_model(id)` |
| `/clear` | 开新会话（新 JSONL），滚动区打分隔线 |
| `/tree` | `rich.Tree` 渲染 `store.entries`：节点 = id 前 8 位 + 角色/类型 + 内容前 50 字符；当前路径高亮、叶子标 `←` |
| `/branch <id前缀>` | 唯一前缀匹配 → `session.branch(id)`；歧义/无匹配报错 |
| `/quit` | 请求退出（同 Ctrl+D） |

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
3. **真实 API 验收**（维护者在场）：见 §1 验收标准。

## 8. 工程增量

- CI：矩阵增加 `uv sync --extra tui` + `apt-get install tmux`；e2e job 跑
  tmux 测试
- README：TUI 章节（安装 extra、`pipython` 用法、斜杠命令表）
- 四件套依赖以 uv 实际解析结果钉 `==` 精确版（阶段一同规矩）

## 9. 风险与后续

- **终端兼容性**：尾部预览依赖 rich.Live 的光标控制，在哑终端（CI 无 tty）自
  动降级为纯打印——render 层留 `console.is_terminal` 分支
- 后续（非本阶段）：交互式树浏览器、主题、图片渲染、`AgentSession.open()`
  resume 接入 TUI（依赖阶段二之后的 SDK resume 能力）
