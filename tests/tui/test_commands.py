import json
from pathlib import Path

from prompt_toolkit import PromptSession
from rich.console import Console

from pipython import (
    AgentSessionConfig,
    AssistantMessage,
    TextContent,
    create_agent_session,
    entry_id,
)
from pipython.testing import FakeClient
from pipython.tui import app as app_module
from pipython.tui.commands import AppState, Command, CommandContext, build_registry, dispatch


def done(text="done"):
    return AssistantMessage(content=[TextContent(text=text)])


async def make_ctx(tmp_path: Path, script=None):
    async def factory():
        return await create_agent_session(
            AgentSessionConfig(
                model="fake",
                cwd=tmp_path,
                session_dir=tmp_path / "s",
                client=FakeClient(script=script or []),
            )
        )

    session = await factory()
    console = Console(record=True, width=100)
    return CommandContext(console=console, app=AppState(session=session, make_session=factory))


async def drain(session, text):
    return [e async for e in session.prompt(text)]


async def test_help_lists_all(tmp_path):
    ctx = await make_ctx(tmp_path)
    await dispatch(build_registry(), ctx, "/help")
    text = ctx.console.export_text()
    for name in ["help", "model", "clear", "tree", "branch", "quit"]:
        assert name in text


async def test_model_show_and_set(tmp_path):
    ctx = await make_ctx(tmp_path)
    reg = build_registry()
    await dispatch(reg, ctx, "/model")
    assert "fake" in ctx.console.export_text()
    await dispatch(reg, ctx, "/model openai/gpt-5.2")
    assert ctx.app.session.model == "openai/gpt-5.2"


async def test_clear_swaps_session(tmp_path):
    ctx = await make_ctx(tmp_path)
    old = ctx.app.session
    await dispatch(build_registry(), ctx, "/clear")
    assert ctx.app.session is not old
    assert ctx.app.session.store.path != old.store.path


async def test_clear_inherits_current_model(tmp_path, monkeypatch):
    # /clear 曾闭包捕获启动时的 model，/model 切换后 /clear 会静默地把会话
    # 拉回启动模型（issue #2）；期望语义是继承 /clear 发生时的当前模型。
    monkeypatch.setattr("pipython.session_facade.DEFAULT_SESSION_DIR", tmp_path / "sessions")
    app = await app_module._build_app(
        "fake/model", tmp_path, client_factory=lambda _model: FakeClient(script=[])
    )
    ctx = CommandContext(console=Console(record=True, width=100), app=app)
    reg = build_registry()
    await dispatch(reg, ctx, "/model other/model")
    await dispatch(reg, ctx, "/clear")
    assert ctx.app.session.model == "other/model"


async def test_quit_sets_flag(tmp_path):
    ctx = await make_ctx(tmp_path)
    await dispatch(build_registry(), ctx, "/quit")
    assert ctx.app.should_quit is True


async def test_tree_shows_structure_and_leaf(tmp_path):
    ctx = await make_ctx(tmp_path, script=[done("first reply")])
    await drain(ctx.app.session, "first question")
    await dispatch(build_registry(), ctx, "/tree")
    text = ctx.console.export_text()
    assert "first question"[:20] in text and "←" in text


async def test_tree_dim_off_path_bold_green_on_path(tmp_path):
    # 分叉出一个节点不在当前路径上，验证 /tree 的样式：路径外 dim，路径上
    # bold green（issue #4，此前无断言覆盖 src/pipython/tui/commands.py 的
    # off-path 着色逻辑）。
    ctx = await make_ctx(tmp_path, script=[done("first reply"), done("second reply")])
    reg = build_registry()
    await drain(ctx.app.session, "first question")
    lines = [json.loads(x) for x in ctx.app.session.store.path.read_text().splitlines()]
    first_user_id = next(x["id"] for x in lines if x["type"] == "message")
    await dispatch(reg, ctx, f"/branch {first_user_id[:8]}")
    await drain(ctx.app.session, "second question")  # 从 first_user_id 分叉出新路径
    await dispatch(reg, ctx, "/tree")

    def style_of(substr: str) -> str | None:
        for seg in ctx.console._record_buffer:
            if substr in seg.text:
                return str(seg.style)
        return None

    assert style_of("first reply") == "dim"  # 分叉前的旧回复，已离开当前路径
    assert style_of("second reply") == "bold green"  # 当前叶子，仍在路径上


async def test_tree_shows_model_change_target(tmp_path):
    ctx = await make_ctx(tmp_path)
    reg = build_registry()
    await dispatch(reg, ctx, "/model somemodel/xyz")
    await dispatch(reg, ctx, "/tree")
    text = ctx.console.export_text()
    assert "model_change → xyz" in text


async def test_branch_prefix_match_and_errors(tmp_path):
    ctx = await make_ctx(tmp_path, script=[done()])
    await drain(ctx.app.session, "hello")
    lines = [json.loads(x) for x in ctx.app.session.store.path.read_text().splitlines()]
    first_id = next(x["id"] for x in lines if x["type"] == "message")
    await dispatch(build_registry(), ctx, f"/branch {first_id[:4]}")
    assert ctx.app.session.store.leaf_id == first_id
    await dispatch(build_registry(), ctx, "/branch zzzz")
    assert "no match" in ctx.console.export_text().lower()


async def test_branch_header_prefix_reports_no_match(tmp_path):
    # session header id 也是合法 id，前缀能唯一命中它；命中 header 绝不能当成
    # 可 branch 的节点——否则 leaf_id 被指向一个 current_path 会剔除的条目，
    # 后续 /tree 与每次 prompt 都会 ValueError 崩溃（复审发现的阻塞项）。
    ctx = await make_ctx(tmp_path, script=[done()])
    await drain(ctx.app.session, "hello")
    header_id = entry_id(ctx.app.session.store.entries[0])
    assert header_id is not None
    leaf_before = ctx.app.session.store.leaf_id
    await dispatch(build_registry(), ctx, f"/branch {header_id[:8]}")
    assert "no match" in ctx.console.export_text().lower()
    assert ctx.app.session.store.leaf_id == leaf_before


async def test_branch_ambiguous_prefix_leaves_leaf_unchanged(tmp_path, monkeypatch):
    from pipython.session import ids

    seq = iter(["aaaa1111", "aaaa2222", "bbbb3333", "cccc4444"])
    monkeypatch.setattr(ids, "new_entry_id", lambda: next(seq))

    ctx = await make_ctx(tmp_path, script=[done(), done()])
    await drain(ctx.app.session, "one")
    await drain(ctx.app.session, "two")

    leaf_before = ctx.app.session.store.leaf_id
    await dispatch(build_registry(), ctx, "/branch aaaa")
    text = ctx.console.export_text().lower()
    assert "ambiguous" in text
    assert ctx.app.session.store.leaf_id == leaf_before


async def test_command_handler_exception_does_not_crash_run_app(tmp_path, monkeypatch, capsys):
    # app.py 的 dispatch 调用曾无防护：任何 handler 抛异常都会带着 traceback
    # 掀翻整个 TUI 主循环（/branch 命中 header id 就是一例）。用真实 run_app()
    # 跑一遍——只在 I/O 边界（prompt_async）和会话落盘目录打桩，dispatch 与
    # 命令查找都走生产代码——证明 handler 抛异常后循环仍能继续、最终正常退出。
    monkeypatch.setattr(app_module, "HISTORY_PATH", tmp_path / "hist")
    monkeypatch.setattr("pipython.session_facade.DEFAULT_SESSION_DIR", tmp_path / "sessions")

    async def boom(_ctx, _arg):
        raise RuntimeError("boom-handler")

    registry = build_registry()
    registry["boom"] = Command("boom", "raises for testing", boom)
    monkeypatch.setattr(app_module, "build_registry", lambda: registry)

    inputs = iter(["/boom", "/quit"])

    async def fake_prompt_async(self, *a, **kw):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(PromptSession, "prompt_async", fake_prompt_async)

    await app_module.run_app(model="fake", cwd=tmp_path)  # 不得抛出

    assert "boom-handler" in capsys.readouterr().out


async def test_unknown_command_hint(tmp_path):
    ctx = await make_ctx(tmp_path)
    await dispatch(build_registry(), ctx, "/nope")
    assert "/help" in ctx.console.export_text()


async def test_ctrl_c_during_file_list_refresh_falls_through_to_prompt(tmp_path, monkeypatch):
    # pre-prompt 的 file_list 刷新期间冒出 KeyboardInterrupt 不该让整个 run_app
    # 提前退出（之前会直接被外层 except KeyboardInterrupt 吞掉、跳过本轮
    # prompt），而是保留旧列表、照常落到这一轮 prompt（issue #6）。用真实
    # run_app()：只在 file_list 刷新与 prompt_async 这两个 I/O 边界打桩。
    monkeypatch.setattr(app_module, "HISTORY_PATH", tmp_path / "hist")
    monkeypatch.setattr("pipython.session_facade.DEFAULT_SESSION_DIR", tmp_path / "sessions")

    build_calls = {"n": 0}

    async def flaky_build_file_list(_cwd):
        build_calls["n"] += 1
        if build_calls["n"] == 1:
            raise KeyboardInterrupt
        return []

    monkeypatch.setattr(app_module, "build_file_list", flaky_build_file_list)

    prompt_calls = {"n": 0}
    inputs = iter(["/quit"])

    async def fake_prompt_async(self, *a, **kw):
        prompt_calls["n"] += 1
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(PromptSession, "prompt_async", fake_prompt_async)

    await app_module.run_app(model="fake", cwd=tmp_path)  # 不得抛出、不得提前退出

    assert prompt_calls["n"] == 1  # 首次 refresh 被打断后，循环仍落到了这一轮 prompt
