# pi-python 阶段一设计：Python Coding Agent SDK

- 日期：2026-07-03
- 状态：已由维护者逐段评审通过
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
│   │   ├── tree.py             #   树状历史：fork / navigate
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
))

async for event in session.prompt("修复 tests/test_foo.py 里的失败用例"):
    ...  # 流式事件

session.set_model("openai/gpt-5.2")      # 中途切模型（pi 特色）
session.fork()                            # 从当前节点分叉
session.navigate(entry_id)                # 回到历史节点
```

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
   条 entry 落盘 JSONL；提供 fork/navigate/compaction。持久化不侵入 loop。

### 4.3 事件模型

阶段一事件子集：`agent_start / message_start / text_delta / tool_call /
tool_result / message_end / agent_end / error`。
`tool_call` 处理器可返回 deny 否决执行——这是权限门控的唯一钩子（对应 pi
"extension 拦截 tool_call" 的哲学）。

### 4.4 错误处理

- 工具执行失败**不抛出**：错误文本作为 `ToolResult(is_error=True)` 回灌给模型
  自行纠错（pi 同款行为）。
- litellm 网络错误：指数退避重试。
- `max_turns`（默认 50）触顶：强制停止，发 `agent_end(reason="max_turns")`。

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

1. **树 = `parentId` 链。** 追加 O(1)；fork = 叶子指针移回历史节点后继续追加；
   文件只追加、永不重写，天然崩溃安全。
2. **当前路径重建**：加载时全量读入，从最后一条 entry 沿 `parentId` 回溯到根；
   其余为休眠分支，`navigate()` 切换。
3. **entry 类型（阶段一子集）**：`session` / `message`（内嵌完整 message 对
   象，含 user、assistant、tool_result）/ `model_change` / `compaction`。
   **未知类型加载时原样保留、不报错**——承接 pi 的 `appendEntry()` 自定义状态扩
   展性，保证向前兼容。
4. **Compaction 是 entry 不是重写**：追加
   `{"type":"compaction","summary":...,"parentId":...}`，加载器用 summary 替代
   其祖先链；历史原文永在。
5. **字段命名保持 pi 的 camelCase**（`parentId`、`modelId`）——文件是数据交换格
   式而非代码，逐字段兼容才可能与 pi 会话互通。Pydantic alias 映射，代码内属性
   仍为 snake_case。写入行级 flush。

## 6. 内置工具集行为规格

7 个工具与上游 `allToolNames` 精确对齐：`read / bash / edit / write / grep /
find / ls`。**行为语义照抄 pi**（实战验证过），实现为地道 Python：

| 工具 | 关键语义 | 实现要点 |
|---|---|---|
| `read` | 行号输出、offset/limit、大文件截断 | `pathlib` |
| `write` | 覆盖写，自动建父目录 | `pathlib` |
| `edit` | 精确串替换，**要求唯一匹配**，不唯一即报错回灌 | 上游另有 diff 变体（`EditToolOptions`），阶段一不做，记为后续跟进 |
| `bash` | 超时（默认可配）、输出截断、非零退出码回灌不抛出 | `asyncio.subprocess` |
| `grep` | 正则内容搜索 | 优先系统 `rg`，降级纯 Python |
| `find` | 文件名/glob 查找 | 同上 |
| `ls` | 目录列表 | `pathlib` |

所有失败以 `ToolResult(is_error=True)` 回灌。路径解析以 `cwd` 为基准。

## 7. 测试策略

1. **Agent loop 不用真实 API**（对应 pi 的 faux provider 规矩）：模型客户端是
   Protocol，测试注入脚本化 **FakeClient**（预设逐轮返回），确定性覆盖多轮、
   deny 否决、错误回灌、max_turns。
2. **工具单测**：pytest + `tmp_path`，逐条覆盖第 6 节行为规格。
3. **Session 单测**：round-trip、fork/navigate、compaction、未知 entry 透传、
   半行损坏容错；外加**兼容性测试：加载一份真实 pi v3 session 样本**。
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
| CI | GitHub Actions：lint + typecheck + 单测，矩阵 3.11/3.12/3.13 |
| 文档 | README：与 pi 的关系声明、快速上手、三原则 |
| 合规 | LICENSE = MIT，保留 Mario Zechner 原始版权行 + 维护者行 |

## 9. 与上游的关系及跟进策略

- 基线钉死 `21cb3807`（v0.80.3）；后续对照上游升级以此为锚点。
- 语义对齐"骨架"而非代码形态：7 工具语义、session v3 线格式、事件否决钩子、极
  简内核边界。
- 已知上游动向（不在阶段一）：`orchestrator`（experimental 多实例编排 +
  radius.pi.dev 在场服务）、edit 的 diff 变体。
