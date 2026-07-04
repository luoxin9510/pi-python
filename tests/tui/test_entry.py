import pipython.tui as tui


def test_parse_args_model_priority(monkeypatch):
    monkeypatch.setenv("PI_PYTHON_MODEL", "env/model")
    assert tui._parse_args(["--model", "cli/model"]).model == "cli/model"
    assert tui._parse_args([]).model == "env/model"
    monkeypatch.delenv("PI_PYTHON_MODEL")
    assert tui._parse_args([]).model == "anthropic/claude-sonnet-5"


def test_parse_args_cwd_defaults_to_dot():
    assert str(tui._parse_args([]).cwd) == "."


def test_main_missing_deps_graceful(monkeypatch, capsys):
    monkeypatch.setattr(tui, "_tui_deps_available", lambda: False)
    assert tui.main([]) == 1
    err = capsys.readouterr().err
    assert "pi-python[tui]" in err and "Traceback" not in err


def test_main_windows_guard(monkeypatch, capsys):
    # TUI 依赖 loop.add_signal_handler，POSIX-only；issue #5：Windows 用户不该
    # 拿到 NotImplementedError 的 traceback，而是干净的一行提示 + exit 1。
    monkeypatch.setattr(tui.sys, "platform", "win32")
    assert tui.main([]) == 1
    err = capsys.readouterr().err
    assert "Windows" in err and "Traceback" not in err


def test_main_keyboard_interrupt_exit_130(monkeypatch):
    # signal 窗口之外冒出的 KeyboardInterrupt（比如 asyncio.run 自身、或
    # pre-prompt file-list 刷新期）不该带着 traceback 崩出去（issue #6）。
    from pipython.tui import app as app_module

    async def boom(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(app_module, "run_app", boom)
    assert tui.main([]) == 130
