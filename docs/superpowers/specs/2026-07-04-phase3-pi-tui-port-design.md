# pi-python 阶段三设计：pi-tui 差分渲染引擎架构级移植

- 日期：2026-07-04
- 状态：已由维护者逐段评审通过（5 段）；两轮独立 subagent 审核后修订（rev 3：
  select-list 入目标、settings-list/input 非目标理由改为功能面差异并列阶段四
  候选、native-modifiers 降级+alt+enter 声明偏离、已知差异挂钩 §1 验收、
  terminal_colors/term_caps/editor_protocol/spacer 补入布局、markdown-it 三重
  坑显式化、RGI_Emoji 正则限定、CJK 词边界裁决）
- 上游参考：`earendil-works/pi` `packages/tui`（28 文件 / 约 12,118 行 TS；基线同阶段一 `21cb3807` v0.80.3，本地对照仓库 `~/Developer/nukcole-pi`）
- 前置：阶段一 SDK 与阶段二 inline TUI 已合入 main（PR #1、#7）

## 1. 背景与目标

维护者明确否决阶段二的 inline REPL 形态（prompt_toolkit + rich 逐行输出），要求
**与 pi 完全一样的 TUI 体验**。经上游源码核实：

> pi **不是备用屏（alternate screen）应用**。它在主缓冲区做**差分渲染**——底部
> 常驻编辑器、上方内容原地增量重绘、终端滚动历史完整保留。"全屏感"来自常驻编
> 辑框、原地刷新、浮层与动画，而非切屏。滚动历史保留是 pi 哲学的一部分，必须
> 原样保真。

**目标**：把 pi-tui 的差分渲染引擎与驱动 pipython 所需的全部组件**架构级移植**
为 Python（模块一一对应、语义级照搬、命名转 snake_case），替换阶段二 TUI 并删
除其代码与依赖。

**验收标准**（缺一不可）：
1. 迁移后的 tmux e2e 全绿（含三条新增：补全浮层、**滚动历史保留**、多行提交）；
2. CJK/emoji 宽度金标准测试通过；
3. **维护者手感对比验收**：同一任务在 pi 与 pipython 并排跑，逐项确认编辑手感
   /流式刷新/补全浮层/中文 IME 候选窗跟随/滚动历史，维护者点头才算完成。
   **以下已声明差异不计入本条判定**（预期管理，验收前先读）：
   - Apple Terminal.app 上 Shift+Enter 无法与 Enter 区分（native-modifiers 降
     级，§5）；换行用 Ctrl+J 或 pipython 新增的 Alt+Enter；
   - CJK 词级移动按"连续 CJK 段一个词"简化，与 pi 的 ICU 字典分词不同（§9）；
   - coding-agent 功能层差异：`/settings` 菜单、登录对话框、`/model` 选择器
     UI 等 pipython 尚无对应功能（见非目标），不属于 TUI 手感范畴。

**非目标**：
- 图片显示（terminal-image/image 组件整体，SDK 尚无多模态——但其中
  `hyperlink()`/`isImageLine()`/终端能力探测子集**必须**单独挖出，见 §3 的
  `term_caps.py`，markdown 渲染依赖它们）；
- **settings-list 与 input 组件——理由是功能面差异，不是"无人用"**：它们在
  pi 里的真实消费方是 coding-agent 功能层（`/settings` 菜单、`/model` 选择
  器、登录对话框、扩展输入框），这些功能依赖 pipython **尚不存在**的子系统
  （settings 注册表、OAuth 登录、模型注册表 UI）。阶段三移植的是 TUI 引擎与
  pipython 现有功能面；上述功能列为**阶段四候选**，届时随功能一起移植这两个
  组件。**select-list 在目标内**（editor 补全下拉本体）。
- 主题系统（只做 pi 默认主题一套，样式表留注入位；§3 terminal_colors.py 是终
  端背景/深浅探测，不属于主题系统）；
- Windows 支持（POSIX only 不变）、备用屏模式、macOS 原生修饰键探测
  （native-modifiers，见 §5 裁决）。

## 2. 移植策略（方案 A：忠实逐模块，"解析借库、渲染照搬"）

- **模块一一对应上游文件**，便于后续 `git show upstream/main:packages/tui/src/<file>`
  逐文件对照升级。
- 只借"数据/解析"库，不借 UI 框架（对齐 pi 仅依赖 `marked` +
  `get-east-asian-width` 的哲学）：

| 上游 | Python 替代 | 说明 |
|---|---|---|
| `marked`（CommonMark 解析） | `markdown-it-py`（**gfm-like 预设**，需伴随 `linkify-it-py`） | 默认 commonmark 预设**不解析** GFM 表格/删除线（已实测），必须 gfm-like。token 形状不同：marked 是嵌套树、markdown-it 是扁平 open/close 流——渲染前需**扁平流→树重建适配层**；pi 的 StrictStrikethroughTokenizer 用 marked 子类覆写机制，Python 侧改用 ruler 插件等价实现。此两项是显式任务，不算"照抄"轻量活 |
| `get-east-asian-width` | `wcwidth` | 宽度数据；pi utils.ts 三个宽度分类正则中 zero-width/leading-non-printing 两个可照抄（`\p{Control}` 等 Python regex 支持），**`\p{RGI_Emoji}` 除外**（Python regex 不支持该属性，实测报 unknown property）——emoji 判定改由 Unicode emoji-data 码位表构造，金标准兜底 |
| `Intl.Segmenter`（字素/词分割） | 字素：`regex` 模块 `\X`；词边界：**无轻量等价**（见 §9 风险） | 上游是 JS 引擎内置 ICU，**无可抄源码**——按 UAX #29 语义重实现，金标准测试兜底 |
| pi 自研 fuzzy.ts（137 行） | 直接移植 | **移除 rapidfuzz 依赖** |

- `[tui]` extra 最终依赖：`markdown-it-py + linkify-it-py + wcwidth + regex +
  pathspec`（全部钉精确版）；**prompt_toolkit、rich、rapidfuzz 移除**。核心
  SDK 依赖不变（litellm + pydantic）。
- SDK 层零改动：引擎只消费 `pipython` 公开 API 的事件流。

## 3. 模块布局

```
src/pipython/tui/
├── engine/                    # ← packages/tui/src 引擎层（文件名一一对应）
│   ├── tui.py                 #   TUI 类：差分渲染/overlay/光标      (tui.ts 1714)
│   ├── terminal.py            #   raw mode/能力探测/ANSI 输出口      (terminal.ts 531)
│   ├── stdin_buffer.py        #   stdin 字节流切帧                   (stdin-buffer.ts 434)
│   ├── keys.py                #   按键解析，kitty CSI-u 子集         (keys.ts 1400 子集)
│   ├── keybindings.py         #   键位表→动作映射                    (keybindings.ts 244)
│   ├── utils.py               #   visible_width/ANSI 折行/字素/OSC-8 (utils.ts 1188 子集)
│   ├── fuzzy.py               #   模糊匹配                           (fuzzy.ts 137)
│   ├── kill_ring.py           #   剪切环                             (kill-ring.ts)
│   ├── undo_stack.py          #   撤销栈                             (undo-stack.ts)
│   ├── word_navigation.py     #   词级移动                           (word-navigation.ts 117)
│   ├── terminal_colors.py     #   OSC 11 背景色查询/深浅探测         (terminal-colors.ts 73；tui.ts 核心直接使用，非主题系统)
│   ├── term_caps.py           #   hyperlink()/isImageLine()/能力子集 (从 terminal-image.ts 488 行中仅挖此三件；图片渲染仍是非目标)
│   └── editor_protocol.py     #   可插拔编辑器 Protocol              (editor-component.ts 74；对齐三原则之"一切可注入")
├── components/
│   ├── editor.py              #   多行编辑器（功能不阉割，见 §6）    (editor.ts 2307)
│   ├── select_list.py         #   选择列表——editor 补全下拉的本体    (select-list.ts 229；editor.ts 直接 new SelectList)
│   ├── markdown.py            #   markdown-it token → pi 风格 ANSI   (markdown.ts 858)
│   ├── autocomplete.py        #   Provider 接口 + 浮层               (autocomplete.ts 786)
│   ├── text.py                #   静态 ANSI 文本块                   (text.ts)
│   ├── box.py                 #   边距/边框容器                      (box.ts)
│   ├── loader.py              #   spinner                            (loader.ts)
│   ├── spacer.py              #   N 空行排版件                       (spacer.ts 28)
│   └── truncated_text.py      #                                      (truncated-text.ts)
├── app.py                     # 重写：新引擎主循环（事件→组件树）
├── commands.py                # 逻辑保留，渲染出口改组件
├── completers.py              # 文件列表/gitignore 逻辑保留，包装成 Provider
└── __init__.py                # 入口/降级检查（TTY 硬要求）
```

删除：`render.py`（rich TurnRenderer）、旧 `keys.py`（pt bindings）及所有
prompt_toolkit/rich 引用。**执行时机见 §8——末位任务才删**，中途任何任务不得
移除旧 TUI 文件。旧测试里依赖 rich 输出格式的历史回归断言（如 issue #4 的
/tree dim 样式）须在新组件测试中建立等价覆盖后方可随旧码删除。

## 4. 引擎核心（engine/tui.py）

**Component 契约**（逐字对照 pi）：`render(width) -> list[str]`（ANSI 行数组）
+ `invalidate()`；可聚焦组件另有 `handle_input(data)` / `focus()` / `unfocus()`
/ `is_focused()`；`Container.add_child/remove_child/clear`。

**TUI 类**：
1. **渲染调度**：`request_render()` 合并式防抖（pi 用 setTimeout 归并；Python
   用 `loop.call_soon`/`call_later(0)` 归并到帧级 `do_render()`）。组件只准调
   `request_render()`，不许直绘。
2. **差分算法**：新行数组 vs `previous_lines` 逐行比对，光标寻址到首个变化行、
   只重写变化行；内容增长向下扩展（对应上游 `expandForLines`）。这是滚动历史
   保留的实现本体。
3. **Overlay 栈**：`show_overlay(component, options) -> OverlayHandle` /
   `hide_overlay()`；焦点保存/恢复状态机照移；按终端尺寸控制可见性。
4. **硬件光标/IME**：跟踪 `hardware_cursor_row`，把真实光标钉在编辑器输入点，
   保证中文输入法候选窗跟随（必移项，维护者刚需）。
5. **resize**：SIGWINCH → `previous_viewport_top` 尺寸感知光标修正 + 全量重
   绘；`clear_on_shrink` 选项照移。

**asyncio 接线**：`loop.add_reader(stdin_fd)` 喂 stdin_buffer；信号
`add_signal_handler`；无线程。

**忠实度基线**：实现时以上游对应 TS 文件为规范性参考（任务书附文件路径），语
义级照搬；凡主动偏离必须在报告中声明理由。

## 5. 输入栈

**terminal.py**：raw mode 进出（termios/tty）；异常退出的终端状态恢复保障
（还原 kitty 标志、显示光标——`finally` 级别）；kitty 键盘协议**能力协商**
（CSI ? u 查询/应答/超时，照抄 pi 探测顺序）；ANSI 输出唯一出口（测试时换记录
桩）。

**stdin_buffer.py**：字节流切帧——完整转义序列 / 半截序列等待 / 孤立 ESC 超时
判定 / bracketed paste 整块交付。

**keys.py 子集边界**：
- **移**：全部 legacy 序列；kitty CSI-u 基础+修饰键+ **flag 4 alternate keys**
  （Shift+Enter/Ctrl+Enter 区分依赖它）。
- **不移**：Node/浏览器环境特判、pi 未启用的协议标志。
- **native-modifiers 裁决（不移，降级）**：上游 native-modifiers.ts 实为
  darwin 预编译 `.node` 原生插件（轮询 macOS 物理修饰键，terminal.ts 用它在
  Apple Terminal.app 消歧 Shift+Enter）。Python 复刻需引入 pyobjc 级新依赖，
  违背依赖纪律。裁决：**不移植**——支持 kitty 协议的终端（iTerm2/kitty/
  Ghostty/WezTerm）经 CSI-u 天然区分 Shift+Enter；Apple Terminal.app 上
  Shift+Enter 不可区分。写入 README 已知限制。
- **键位声明偏离**：上游默认 newLine 键位为 `shift+enter` 与 `ctrl+j`
  （keybindings.ts:118，**无** alt+enter）。pipython **主动新增**
  `alt+enter → newLine` 默认绑定——理由：延续阶段二肌肉记忆 + 给
  Terminal.app 用户一条顺手换行路径。此为 §4 忠实度基线下的声明偏离。
- 产出统一 `KeyEvent`；`keybindings.py` 映射到编辑器动作，默认 Emacs 键位与
  pi 一致。

三层全部纯函数化：字节→帧、序列→KeyEvent、ANSI 出口可注入记录桩。**pi 自己
的输入栈测试用例直接翻译作为金标准**。

## 6. 组件层与 pipython 接线

**editor.py 功能不阉割**：多行编辑、字/词/行光标移动、kill-ring
（Ctrl+K/Y/W）、undo 栈、输入历史、bracketed paste 整段插入、IME 光标钉扎、补
全钩子（下拉渲染 = `select_list.py`，editor 直接持有 SelectList 实例，照上游
结构）。（上游 editor 无占位符功能，不发明。）

**markdown.py**：markdown-it-py（gfm-like 预设）token 流 → **扁平流→树重建适
配层** → pi 的 ANSI 渲染规则逐条对齐（标题/列表/代码块底色/引用/表格——上游
`renderTable` 吃嵌套树，适配层负责喂给它同构结构）；严格删除线用 ruler 插件等
价实现 pi 的 StrictStrikethroughTokenizer；链接 OSC-8（helper 在
engine/term_caps.py）；单一 pi 默认主题，样式表留注入位。

**autocomplete.py**：Provider 接口 + overlay 浮层列表；`completers.py` 的文件
列表/gitignore/斜杠命令逻辑包装成两个 Provider；模糊匹配用 engine/fuzzy.py。

**app.py 组件树**：
```
Container
├── 会话区: 每回合追加——用户输入回显(text) / 流式(text, 增量 invalidate)
│          → message_end 原地替换为 markdown / 工具行(text) / 错误(红 text)
├── loader（回合中）
└── editor（常驻底部，默认焦点）
```
- 提交/中断/退出语义与阶段二一致：SIGINT→cancel→`[interrupted]`；编辑器内
  Ctrl+C=清缓冲（pi 行为）；Ctrl+D 空缓冲=退出 + session 路径横幅。
- 斜杠命令输出改为追加 text 组件；`commands.py` 只换渲染出口。
- **TTY 硬要求**：非 TTY 一句话退出（e2e 走 tmux 真 pty）。

## 7. 测试策略

1. **引擎单测**：差分算法（记录桩断言光标寻址+重写序列）、overlay 焦点链、
   resize、`request_render` 归并。
2. **输入栈金标准**：翻译 pi 的既有测试用例；kitty 与 legacy 双路径。
3. **组件金行测试**：editor 各状态、markdown fixture → 期望 ANSI 行；
   **CJK/emoji 宽度专项金标准**（中英混排、emoji、折行），压制
   Intl.Segmenter↔regex `\X` + wcwidth 分歧。
4. **tmux e2e**：现有场景全部迁移 + 新增：补全浮层出现/选择、**滚动历史保留**
   （多轮后 `capture -S -` 断言早期回合仍在 scrollback）、编辑器多行提交。
5. **手感验收**（§1 第 3 条）：维护者并排对比，含 IME 候选窗跟随（明确不做自
   动化，手动验收项）。

## 8. 交付与迁移次序约束

- 新引擎旁路开发，**旧 TUI 最后一个任务才删**——开发全程 pipython 可用、每任
  务 CI 全绿。
- `[tui]` extra 依赖换血并钉版；`pipython` 入口不变；README TUI 章节重写。
- 计划规模预估：约 15 任务（与阶段一相当），单 spec 单计划。

## 9. 风险清单（计划阶段逐条布防）

| 风险 | 防线 |
|---|---|
| 终端兼容矩阵（Terminal.app/iTerm2/kitty/Ghostty 的 kitty 协议差异） | 能力协商+legacy 回退；验收在维护者实际终端过；Terminal.app 的 Shift+Enter 限制已裁决降级（§5） |
| 宽度/字素分歧（最大暗坑） | §7.3 金标准；宽度分类正则照抄 string-width 同款（RGI_Emoji 除外，见 §2）；字素按 UAX #29 重实现 |
| **词边界的 CJK 分词无轻量等价**（Intl.Segmenter word 粒度是 ICU 字典分词） | 裁决：CJK 下词级移动（Alt+F/B 等）按"连续 CJK 段视作一个词"简化，**允许与 pi 行为不同**；西文行为对齐 UAX #29。验收预期照此，写入 README 已知限制 |
| tui.ts 差分/光标/resize 核心（约 500 行高分支密度，与 editor/keys 同级硬骨头） | 拆分为独立任务（差分算法、overlay 栈、resize/光标修正分开），不与 request_render 归并逻辑合并 |
| editor/keys 体量（2307+1400 行）；**editor.test.ts 达 4051 行**，测试翻译本身是大活 | editor 拆多任务；测试翻译按行为域分批（编辑/光标/kill-ring/undo/粘贴/补全），每批随对应实现任务走 |
| IME 光标钉扎难自动化 | 手动验收项，不装自动化 |
| asyncio stdin 洪泛（大粘贴） | stdin_buffer 切帧专测 bracketed paste 大块 |
| markdown token 模型差异（marked 嵌套树 vs markdown-it 扁平流） | 适配层显式立项（§6）；gfm-like 预设+linkify-it-py 依赖已入 §2 |
