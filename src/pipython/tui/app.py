import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from pipython import AgentSessionConfig, AssistantMessage, ModelClient, create_agent_session
from pipython.testing import FakeClient
from rich.text import Text

from .commands import AppState, CommandContext, build_registry, dispatch
from .completers import PiCompleter, build_file_list
from .keys import build_key_bindings
from .render import TurnRenderer

HISTORY_PATH = Path.home() / ".pi-python" / "tui-history"


def load_fake_client(path: str) -> FakeClient:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FakeClient(script=[AssistantMessage.model_validate(d) for d in data])


def make_client(model: str) -> ModelClient | None:
    fake = os.environ.get("PI_PYTHON_FAKE_SCRIPT")
    if fake:
        return load_fake_client(fake)
    return None


async def _consume(events, console: Console) -> None:
    renderer = TurnRenderer(console)
    try:
        async for event in events:
            await renderer.handle(event)
    finally:
        renderer.finish()  # 取消/异常也清 Live（spec §4）


async def run_app(*, model: str, cwd: Path) -> None:
    console = Console()

    async def make_session():
        client = make_client(model)
        return await create_agent_session(AgentSessionConfig(model=model, cwd=cwd, client=client))

    app = AppState(session=await make_session(), make_session=make_session)
    registry = build_registry()
    completer = PiCompleter(commands={n: c.description for n, c in registry.items()})
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    prompt_session: PromptSession = PromptSession(
        "> ",
        history=FileHistory(str(HISTORY_PATH)),
        completer=completer,
        key_bindings=build_key_bindings(),
        multiline=True,
    )
    # 路径/模型名是动态内容 → Text，不走 markup 解析
    console.print(Text(f"pipython · {model} · {cwd}", style="dim"))
    loop = asyncio.get_running_loop()
    try:
        while True:
            completer.file_list = await build_file_list(cwd)
            try:
                text = (await prompt_session.prompt_async()).strip()
            except EOFError:  # Ctrl+D 空缓冲
                break
            except KeyboardInterrupt:  # 输入期 Ctrl+C：pt 抛出 → 清空重来
                continue
            if not text:
                continue
            if text.startswith("/"):
                ctx = CommandContext(console=console, app=app)
                try:
                    await dispatch(registry, ctx, text)
                except Exception as exc:
                    # handler bug 不得掀翻主循环（复审发现：/branch 命中 header id 会崩）
                    msg = f"[command error] {type(exc).__name__}: {exc}"
                    console.print(Text(msg, style="red"))
                    continue
                if app.should_quit:
                    break
                continue
            task = asyncio.create_task(_consume(app.session.prompt(text), console))
            loop.add_signal_handler(signal.SIGINT, task.cancel)
            try:
                await task
            except asyncio.CancelledError:
                console.print(Text("[interrupted]", style="yellow"))
            except Exception as exc:  # 渲染层意外不掀翻主循环（防御性兜底）
                console.print(Text(f"[error] {type(exc).__name__}: {exc}", style="red"))
            finally:
                with contextlib.suppress(ValueError):
                    loop.remove_signal_handler(signal.SIGINT)
    except KeyboardInterrupt:
        pass  # handler 摘除后到 pt 接管前的窄窗口兜底
    finally:
        # soft_wrap=True：路径是不可分割的 token，禁用 Rich 的按词换行（默认会在
        # "session:" 后的空格处硬拆行，把后续路径拆到下一行），让终端做原生的
        # 按列软换行——退出横幅在窄终端/长路径下仍保持逻辑上的单行可读。
        console.print(Text(f"session: {app.session.store.path}", style="dim"), soft_wrap=True)
