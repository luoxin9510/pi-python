# pi-python 阶段一设计：Python Coding Agent SDK

- 日期：2026-07-03
- 状态：已由维护者逐段评审通过；已通过独立 subagent 审核并修订（rev 2）
- 移植基线：[earendil-works/pi](https://github.com/earendil-works/pi) `upstream/main` @ `21cb3807`（v0.80.3，2026-06-30）
- License：MIT，双署名（原作者 Mario Zechner + 本仓库维护者）

## 1. 背景与目标

pi 是一个 TypeScript/Node 的极简终端 coding harness（"designed to stay small at the
core while being extended"）。本项目把 pi 的**内核哲学与核心能力**移植为地道的
Python 库，服务于以 Python 为主流的生产环境。

**分阶段路线：**

- **阶段一（本 spec）**：可 `import` 的 Python coding agent SDK —— agent loop、
  内置工具集、树状 JSONL 会话。不含任何终端 UI。
- 阶段二以后（各自单独 spec）：CLI/TUI、编排（对应上游 experimental 的
  `orchestrator` 包）等。

**阶段一验收标准**：一段脚本 `import pipython`，指向一个真实仓库并给出编码任务
（如"修复失败的测试"），agent 能自主多轮调用工具（搜索→读→改→跑命令）直到完成。

## 2. 设计原则：「自由 harness」三原则

移植**不是**逐行翻译。pi 哲学在 Python 里的地道表达是：

> **Python 本身就是扩展语言。** pi 在 TS 里需要 extensions/skills/prompt
> templates/packages 四种机制，因为 CLI 用户没有编程入口；SDK 使用者本来就在写
> 代码，所以不发明任何插件 DSL，而是让每个部件都是可注入、可替换、可组合的普通
> Python 对象。

1. **一切皆可注入，无一强制。** `create_agent_session()` 只是便捷门面；
   `Agent`、`ToolRegistry`、`SessionStore`、模型客户端、事件总线均可单独实例
   化、单独替换。边界用 `typing.Protocol`（结构化鸭子类型）而非强制继承。
2. **扩展 = 普通 Python 函数。** 事件订阅 `session.on("tool_call", handler)`
   （handler 可为 async callable，返回 deny 即否决该 tool call）。权限门控、审
   计、UI 桥接全走这一个机制，core 不为它们加一行代码。
3. **用足 Python 优势。** `@tool` 装饰器（函数签名 + type hints + docstring 自
   动生成 JSON schema）；`prompt()` 返回 async generator（原生流式）；
   `async with` 管理生命周期；Pydantic v2 校验一切边界。

**忠于 pi 的极简立场（非目标）：** 不内置权限系统（订阅 `tool_call` 自行拦
截）；不内置沙箱（生产用容器，pi 同款立场）；不做 MCP、子 agent、orchestrator
（上游自标 experimental）；不做 TUI/CLI（阶段二）。

## 3. 架构与模块布局

单包多模块（不做 monorepo——阶段一只发一个库）。PyPI 分发名 `pi-python`，
import 名 `pipython`，Python 3.11+。

```
pi-python/
├── src/pipython/
│   ├── ai/                     # ← 对齐 pi 的 packages/ai
│   │   ├── client.py           #   litellm 薄封装：stream() / complete()
│   │   ├── types.py            #   Message / ToolCall / Usage 等数据模型
│   │   └── models.py           #   模型别名 → litellm model id 映射
│   ├── agent/                  # ← 对齐 pi 的 packages/agent
│   │   ├── loop.py             #   async agent loop
│   │   ├── agent.py            #   Agent 类（编排入口，无持久化）
│   │   └── events.py           #   pub/sub 事件总线
│   ├── tools/                  # ← pi 内置工具集（coding-agent/src/core/tools）
│   │   ├── base.py             #   @tool 装饰器 + Tool 协议 + schema 生成
│   │   ├── read.py write.py edit.py bash.py grep.py find.py ls.py
│   │   └── registry.py         #   注册/查找/调度
│   ├── session/                # ← pi 的 "sessions 即数据"
│   │   ├── store.py            #   JSONL 读写
│   │   ├── tree.py             #   树状历史：branch()、当前路径重建
│   │   └── compaction.py       #   上下文压缩
│   └── __init__.py             #   顶层 API：create_agent_session() 等
├── tests/
├── examples/                   # 验收 demo
├── docs/superpowers/specs/     # 设计文档（本文件）
├── pyproject.toml              # uv + hatchling
├── LICENSE                     # MIT 双署名
└── README.md
```

核心依赖只有两个：`litellm`（provider 层，不自己移植 15+ 家 API）与
`pydantic` v2。

## 4. 核心组件接口

### 4.1 顶层 API（门面）

```python
from pipython import create_agent_session, AgentSessionConfig

session = await create_agent_session(AgentSessionConfig(
    model="anthropic/claude-opus-4-8",   # litellm 格式 model id
    cwd="/path/to/repo",                 # 工具工作目录
    system_prompt=None,                  # None → 内置默认 coding prompt
    tools=None,                          # None → 全部内置 7 工具
    session_dir=None,                    # None → ~/.pi-python/sessions/
    max_turns=50,                        # 安全阀，见 §4.4
))

async for event in session.prompt("修复 tests/test_foo.py 里的失败用例"):
    ...  # 流式事件

session.set_model("openai/gpt-5.2")      # 中途切模型（pi 特色）
session.branch(entry_id)                  # 叶子指针移回历史节点，续写即分叉
```

命名对齐上游：`branch(entry_id)` 对应上游 `SessionManager.branch()`（同一
JSONL 文件内移动叶子指针）；上游另有 `forkFrom()`（另开新文件、写
`parentSession`），属阶段二，不做。

### 4.2 三个核心抽象

1. **Tool（`tools/base.py`）**：`@tool` 装饰的 async 函数（签名+type hints →
   JSON schema，docstring → 描述），或实现 `Tool` Protocol 的对象。执行收到
   `ctx`（cwd、事件总线引用）。**内置工具与用户工具地位完全平等**：可整组用、
   单个挑、同名覆盖、全部丢弃。
2. **Agent（`agent/agent.py`）**：无持久化的纯循环编排器。`prompt()` 驱动
   loop：litellm 流式 → tool_calls 经 Pydantic 校验 → 执行 → 结果回灌 → 直到
   模型不再调工具。每步发事件。**Agent 不知道 session 文件的存在**（对齐 pi：
   agent 包不依赖 coding-agent 包）。
3. **AgentSession（门面 + `session/`）**：包装 Agent，**以事件订阅者身份**把每
   条 entry 落盘 JSONL；提供 `branch()` 与 `compact()`（阶段一的全部树操作，
   见 §5）。持久化不侵入 loop。

### 4.3 事件模型

阶段一事件子集：`agent_start / message_start / text_delta / tool_call /
tool_result / message_end / agent_end / error`。
（上游另有 thinking/toolcall 级增量事件；阶段一事件层不呈现 thinking 增量，但
session 落盘的 assistant message 中 `ThinkingContent` 照存，不丢数据。）

**订阅点与 deny 契约（权限门控的唯一钩子）：**

- 订阅挂在 **AgentSession 门面**上（`session.on(...)`）。**`session.on()` 就
  是把处理器注册进 Agent 持有的同一份底层总线**——不是镜像转发、没有中间层复
  制，因此门面层注册的 deny 与裸 `Agent` 上注册的效力完全相同。
- `tool_call` 处理器按注册顺序执行（同步或 async 均可）；返回 `None` 放行，返
  回 `Deny(reason: str)`（库提供的 frozen dataclass）即否决，**首个 Deny 短路**
  后续处理器。
- 否决后该工具不执行，模型收到
  `ToolResult(is_error=True, content="Tool call denied: {reason}")` 回灌，
  session 照常落盘这条被拒结果（审计可见）。
- 其余事件的处理器返回值一律忽略——deny 语义只存在于 `tool_call`。

### 4.4 错误处理

- 工具执行失败**不抛出**：错误文本作为 `ToolResult(is_error=True)` 回灌给模型
  自行纠错（pi 同款行为）。
- litellm 网络错误：**只保留一层重试**——自实现指数退避（可配次数），调用
  litellm 时显式 `num_retries=0` 关掉其内建重试，避免两层叠加导致超长挂起。
- `max_turns`（默认 50，`AgentSessionConfig` 字段，`prompt()` 可按次覆盖）：
  **一轮 = 一次 assistant 响应及其引发的全部工具执行**（借上游
  `turn_start`/`turn_end` 的边界定义作内部计数语义，**不**对外新增这两个事件
  类型，§4.3 的事件子集即全集）。触顶强制停止，发
  `agent_end(reason="max_turns")`。注意：上游核心并无此熔断，这是本移植**主动
  新增**的生产安全阀，不是照抄。

## 5. Session：JSONL 格式与树状历史

**直接采用 pi 的 v3 线格式。** 规范性参考 = 上游
`packages/coding-agent/docs/session-format.md`（基线 commit 内版本）。

文件布局：`~/.pi-python/sessions/<按 cwd 转义的目录>/<ISO时间戳>_<uuid7>.jsonl`
（自有根目录，不污染 pi 的 `~/.pi`；uuid7 标准库没有，自实现约十行，不为此引入
第三个依赖）。

首行 session 头，其后每行一条 entry，`parentId` 串成树：

```jsonl
{"type":"session","version":3,"id":"<uuid>","timestamp":"...","cwd":"/path/to/repo"}
{"type":"model_change","id":"3735e3b2","parentId":null,"timestamp":"...","provider":"anthropic","modelId":"claude-opus-4-8"}
{"type":"message","id":"a1b2c3d4","parentId":"3735e3b2","timestamp":"...","message":{...}}
```

**机制：**

1. **树 = `parentId` 链。** 追加 O(1)；`branch(entry_id)` = 叶子指针移回历史
   节点后继续追加；文件只追加、永不重写，天然崩溃安全。
2. **当前路径重建**：加载时全量读入，从最后一条 entry 沿 `parentId` 回溯到根；
   其余为休眠分支，`branch()` 切换。
3. **entry 类型（阶段一子集）**：`session` / `message`（内嵌完整 message 对
   象，含 user、assistant、toolResult 角色）/ `model_change` / `compaction`。
   **未知类型加载时原样保留、不报错**——承接 pi 的 `appendEntry()` 自定义状态扩
   展性，保证向前兼容。实现提示：这意味着不能只靠一个 Pydantic discriminated
   union——先按 `type` 分派，已知类型强校验，未知类型存原始 dict。
4. **Compaction 是 entry 不是重写**（字段对齐上游 `CompactionEntry`）：
   ```jsonl
   {"type":"compaction","id":...,"parentId":...,"summary":"...","firstKeptEntryId":"...","tokensBefore":12345}
   ```
   加载语义与上游 `buildContextEntries()` 一致：**只折叠 `firstKeptEntryId`
   之前的祖先为 summary；`firstKeptEntryId` 到 compaction entry 之间的原文全部
   保留**。历史原文永在文件里。缺 `firstKeptEntryId`/`tokensBefore` 的
   compaction 视为格式错误——这两个字段是与 pi 会话互通的必要条件。
5. **字段命名保持 pi 的 camelCase**（`parentId`、`modelId`、`toolResult`）——文
   件是数据交换格式而非代码，逐字段兼容才可能与 pi 会话互通。Pydantic alias 映
   射，代码内属性仍为 snake_case。写入行级 flush。
6. **阶段一 compaction 范围明确收窄**：只做 entry 格式、加载折叠语义、手动
   `session.compact()` API（summary 由调用方或一次显式 LLM 调用生成）。**自动
   触发**（token 阈值监测、触发策略、summary prompt 工程）不在阶段一，记入
   §9——避免把"一周的活"藏在"一天的模块名"里。

## 6. 内置工具集行为规格

7 个工具与上游 `allToolNames` 精确对齐：`read / bash / edit / write / grep /
find / ls`。**行为语义照抄 pi**（实战验证过），实现为地道 Python：

| 工具 | 关键语义（参数面照抄上游 schema） | 实现要点 |
|---|---|---|
| `read` | 行号输出、offset/limit、大文件截断。**阶段一仅文本**：上游支持图片附件（jpg/png/gif/webp/bmp），属多模态，明确排除、记入 §9 | `pathlib` |
| `write` | 覆盖写，自动建父目录 | `pathlib` |
| `edit` | **`{path, edits: [{oldText, newText}, ...]}` 数组式多处替换**（对齐上游 `editSchema`）：每处均相对**原文**定位（非增量应用）、不得重叠/嵌套、每个 `oldText` 要求唯一匹配，违反即整体报错回灌 | 上游另有 diff 变体（`EditToolOptions`），阶段一不做 |
| `bash` | 超时（默认可配）、输出截断、非零退出码回灌不抛出。**超时/中止须杀整棵进程树**（对齐上游 `killProcessTree`） | `asyncio.subprocess` + `start_new_session=True`，超时 `os.killpg`；**边读边截**（防 `yes` 类无限输出把内存吃满；注意 stream reader 的 limit 参数） |
| `grep` | 参数：`pattern`（必填，regex 或 literal）、`path`、`glob`、`ignoreCase`、`literal`、`context`、`limit`（默认 100） | 优先系统 `rg`，降级纯 Python |
| `find` | 参数：`pattern`（必填，glob）、`path`、`limit`（默认 1000） | 同上 |
| `ls` | 目录列表 | `pathlib` |

所有失败以 `ToolResult(is_error=True)` 回灌。路径解析以 `cwd` 为基准。

## 7. 测试策略

1. **Agent loop 不用真实 API**（对应 pi 的 faux provider 规矩）：模型客户端是
   Protocol，测试注入脚本化 **FakeClient**（预设逐轮返回），确定性覆盖多轮、
   deny 否决、错误回灌、max_turns。
2. **工具单测**：pytest + `tmp_path`，逐条覆盖第 6 节行为规格。
3. **Session 单测**：round-trip、`branch()` 分叉与当前路径重建、compaction 折
   叠语义、未知 entry 透传、半行损坏容错；外加**兼容性测试：加载一份真实 pi
   v3 session 样本**。
4. **验收 demo**：`examples/fix_failing_test.py` + 内置小型样例仓库（带故意失
   败的测试），agent 自主 grep→read→edit→bash 到测试转绿。真实 API，CI 中为
   手动/可选 job。

## 8. 工程交付

| 项 | 选择 |
|---|---|
| 构建 | `uv` + `pyproject.toml`（hatchling），src 布局 |
| Python | 3.11+ |
| 运行时依赖 | `litellm`、`pydantic>=2`（仅此两个） |
| 质量 | `ruff`（lint+format）、`pyright`、`pytest` + `pytest-asyncio` |
| CI | GitHub Actions：lint + typecheck + 单测，矩阵 3.11/3.12/3.13；**必须安装 `ripgrep`**——grep/find 的 rg 优先路径（生产主路径）必须被真实测到，纯 Python 降级路径另测 |
| 文档 | README：与 pi 的关系声明、快速上手、三原则 |
| 合规 | LICENSE = MIT，保留 Mario Zechner 原始版权行 + 维护者行 |

## 9. 与上游的关系及跟进策略

- 基线钉死 `21cb3807`（v0.80.3）；后续对照上游升级以此为锚点。
- 语义对齐"骨架"而非代码形态：7 工具语义、session v3 线格式、事件否决钩子、极
  简内核边界。
- 已知上游能力/动向（明确不在阶段一，后续按需跟进）：`orchestrator`
  （experimental 多实例编排 + radius.pi.dev 在场服务）、edit 的 diff 变体、
  edit 的空白规整模糊匹配容错（阶段一只做精确匹配）、`read` 的图片/多模态支
  持、`forkFrom()` 跨文件 fork、compaction 自动触发算法、thinking/toolcall 级
  细粒度增量事件、bash 全量输出转存临时文件（`fullOutputPath`，阶段一截断即
  丢）。
- **pi 会话互通的阶段一边界（终审裁定，2026-07-03）**：阶段一达成 **envelope
  级互通**——真实 pi v3 文件可经 `SessionStore.open` 加载（entry 字段兼容、未
  知类型透传、目录/文件命名一致），并有真实文件兼容测试锁定。**message body
  的强类型互通**（pi 的数组式 content、`Usage.input/output` 字段名、cost 对象
  展开）与 **resume 已有会话**（`AgentSession.open()`）列入阶段二——阶段一的
  门面只创建新会话，`_parse_message` 仅需解析自产格式。
- litellm 作为唯一重依赖：版本**钉精确版**（对齐 pi "依赖是受审代码"的立场），
  升级走显式 PR；其 cost/价格表对新模型可能滞后，usage 的 cost 字段允许缺省为
  `None`，不因价格表缺失报错。
