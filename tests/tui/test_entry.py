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
