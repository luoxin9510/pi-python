# pi-python

Python port of [pi](https://github.com/earendil-works/pi) — a minimal coding
agent harness by Mario Zechner. Phase 1 delivers an embeddable agent SDK:
async agent loop, the seven built-in coding tools, and pi's tree-structured
JSONL sessions. MIT, dual attribution.

## Install

    uv add pi-python   # or: pip install pi-python

## Quick start

    from pipython import AgentSessionConfig, create_agent_session

    session = await create_agent_session(AgentSessionConfig(
        model="anthropic/claude-sonnet-5", cwd="/path/to/repo"))
    async for event in session.prompt("fix the failing test in tests/"):
        ...

## Design principles (the "free harness" rules)

1. Everything injectable, nothing mandatory — every part (Agent, tools,
   session store, model client, event bus) can be instantiated and replaced
   on its own; boundaries are `typing.Protocol`.
2. Extension = a plain Python function — subscribe to events
   (`session.on("tool_call", handler)`); return `Deny(reason)` to veto.
   No plugin DSL.
3. Use Python's strengths — `@tool` decorator, async generators, Pydantic
   validation at every boundary.

See `docs/superpowers/specs/` for the full design; `examples/` for the
acceptance demo.

## Interactive TUI

Phase 2 adds an interactive CLI on top of the same SDK: a `pipython` command
that streams the agent's replies into your terminal's normal scrollback, with
a live input line at the bottom (rich for output, prompt_toolkit for input).
It is an optional extra — the SDK stays two-dependency (`litellm` +
`pydantic`).

### Install

    pip install "pi-python[tui]"   # or: uv add "pi-python[tui]"

### Usage

    pipython [--model <litellm-id>] [--cwd <path>]

- `--model` — a litellm model id (e.g. `anthropic/claude-sonnet-5`,
  `deepseek/deepseek-chat`). Defaults to the `PI_PYTHON_MODEL` environment
  variable if set, otherwise `anthropic/claude-sonnet-5`.
- `--cwd` — the agent's working directory. Defaults to the current directory.

If the `tui` extra isn't installed, `pipython` prints a one-line install hint
and exits instead of raising a traceback.

### Keybindings

| Key | Action |
|---|---|
| `Enter` | Submit the current input |
| `Alt+Enter` / `Ctrl+J` | Insert a newline (multi-line input) |
| `Ctrl+C` | During a running turn: interrupt the agent and return to the prompt. At the prompt: discard whatever is typed so far (including a multi-line draft) and start a fresh prompt |
| `Ctrl+D` | Exit at an empty prompt (readline EOF semantics); on a non-empty line, deletes the character under the cursor |
| `Ctrl+R` | Reverse history search (prompt_toolkit default, backed by `~/.pi-python/tui-history`) |

Emacs-style editing (`Ctrl+A/E/K/Y/W`, `Alt+F/B`, arrow-key history, etc.) is
prompt_toolkit's built-in default editing mode — nothing custom is added on
top beyond the bindings listed above.

Typing `@` opens fuzzy path completion for the current working directory;
typing `/` at the start of a line opens completion over the slash commands
below.

### Slash commands

| Command | Behavior |
|---|---|
| `/help` | List all registered commands with their descriptions |
| `/model [id]` | No argument: show the current model. With an argument: switch the session's model to that litellm id |
| `/clear` | Start a new session (new JSONL file); the old session's file is left on disk |
| `/tree` | Render the session's entry tree (`rich.Tree`), highlighting the path to the current leaf and marking it with `←` |
| `/branch <id-prefix>` | Branch to the entry whose id starts with the given prefix; errors on no match or an ambiguous (multi-match) prefix |
| `/quit` | Quit (equivalent to Ctrl+D) |

Unknown commands print an error and a `/help` hint instead of failing
silently.

### Environment variable

- `PI_PYTHON_MODEL` — default model id used when `--model` isn't passed.
