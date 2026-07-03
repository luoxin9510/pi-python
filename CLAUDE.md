# CLAUDE.md

本文件是 pi-python 仓库对 Claude Code 的工作指引。

## 仓库定位

pi-python 是 [earendil-works/pi](https://github.com/earendil-works/pi)（TypeScript
极简 coding harness，作者 Mario Zechner）的 **Python 移植**，MIT 双署名。

- **权威设计文档**：`docs/superpowers/specs/2026-07-03-pi-python-phase1-sdk-design.md`
  —— 一切实现决策以它为准，先读它再动代码。
- **移植基线**：上游 `main` @ `21cb3807`（v0.80.3）。对照上游源码时读本机参考
  仓库 `~/Developer/nukcole-pi`（已同步至该基线），用
  `git show upstream/main:<path>` 查阅，不要凭记忆复述上游行为。
- **阶段一范围**：可 import 的 agent SDK（loop + 内置 7 工具 + JSONL 树状
  session）。TUI/CLI/orchestrator 均为后续阶段，不要顺手实现。

## 设计三原则（评审否决标准）

1. **一切皆可注入，无一强制**——门面之下每个部件（Agent/ToolRegistry/
   SessionStore/模型客户端/事件总线）都可单独实例化与替换，边界用
   `typing.Protocol`。
2. **扩展 = 普通 Python 函数**——唯一钩子是事件订阅（`tool_call` 可否决）；不
   发明插件 DSL，不为具体扩展需求往 core 加代码。
3. **用足 Python 优势**——`@tool` 装饰器、async generator 流式、Pydantic v2 边
   界校验。

违反任一条的实现，评审时直接打回，不讨论例外。

## 模型分工（重要）

本仓库的开发采用 orchestrator/subagent 分工：

- **主循环（Fable/Opus）只做 orchestrator**：拆解任务、撰写 subagent 任务书、
  集成结果、把守质量门（跑 check/测试、对照 spec 验收）。**不直接写实现代码**；
  允许的直接编辑仅限：琐碎修补（typo、import 顺序）、合并冲突处置、文档。
- **实现交给 Sonnet 5 subagent**（Agent 工具，`model: "sonnet"`）：每个任务书
  必须包含——目标、涉及文件、spec 相关章节摘录、完成定义（含要通过的测试）。
- **审核也由 subagent 做**：实现完成后派**独立的**审核 subagent（不能是实现者
  本身）对照 spec 与三原则评审 diff；orchestrator 只裁决审核结论，不亲自逐行
  评审。
- 互相独立的实现任务并行派发；有依赖的串行。

## 常用命令

```bash
uv sync                      # 安装依赖（含 dev）
uv run pytest                # 全部测试
uv run pytest tests/test_x.py::test_case   # 单测
uv run ruff check --fix . && uv run ruff format .   # lint + 格式
uv run pyright               # 类型检查
```

提交前必须全绿：`ruff check`、`pyright`、`pytest`。

## 工程约束

- Python 3.11+；运行时依赖仅 `litellm` 与 `pydantic>=2`，新增运行时依赖需先改
  spec 并获维护者同意。
- src 布局；测试不用真实 API key（注入 FakeClient，见 spec §7）。
- session 文件字段名保持 pi 的 camelCase（数据交换格式），Python 代码内用
  snake_case + Pydantic alias。
- commit 信息：`{feat,fix,docs,test,chore}(scope): message`，scope 取模块名
  （ai/agent/tools/session）。非用户要求不 commit。
