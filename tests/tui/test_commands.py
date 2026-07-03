import json
from pathlib import Path

from rich.console import Console

from pipython import AgentSessionConfig, AssistantMessage, TextContent, create_agent_session
from pipython.testing import FakeClient
from pipython.tui.commands import AppState, CommandContext, build_registry, dispatch


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


async def test_unknown_command_hint(tmp_path):
    ctx = await make_ctx(tmp_path)
    await dispatch(build_registry(), ctx, "/nope")
    assert "/help" in ctx.console.export_text()
