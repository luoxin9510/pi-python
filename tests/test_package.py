import pipython


def test_version():
    assert pipython.__version__ == "0.1.0"


def test_session_symbols_exported():
    import pipython

    for name in [
        "SessionStore",
        "SessionHeader",
        "MessageEntry",
        "ModelChangeEntry",
        "CompactionEntry",
        "Entry",
        "entry_id",
        "entry_parent_id",
        "entry_type",
        "current_path",
        "find_entry",
        "AssistantMessage",
        "TextContent",
        "ThinkingContent",
        "ToolCallContent",
        "ToolResultMessage",
        "UserMessage",
        "Usage",
        "ModelClient",
    ]:
        assert hasattr(pipython, name), name
        assert name in pipython.__all__, name
