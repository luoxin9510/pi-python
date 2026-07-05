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

Phase 2/3 add an interactive CLI on top of the same SDK: a `pipython` command
that streams the agent's replies into your terminal's normal scrollback, with
a live input line at the bottom. It is an optional extra — the SDK stays
two-dependency (`litellm` + `pydantic`). The TUI is POSIX-only (macOS/Linux);
it is not supported on Windows.

The TUI's rendering engine is a from-scratch Python port of upstream
[pi](https://github.com/earendil-works/pi)'s own terminal engine (not
`prompt_toolkit`/`rich`, which pi-python's TUI used through phase 2): it
diff-renders each frame against the last one (only changed rows are
repainted), keeps the input editor pinned to the bottom of a growing
transcript, and — the point of porting it at all — never switches to the
terminal's alternate screen buffer, so everything the agent has ever said
stays in your terminal's normal scrollback/`capture-pane` history after the
process exits, exactly like upstream pi.

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
| `Shift+Enter` / `Ctrl+J` / `Alt+Enter` | Insert a newline (multi-line input) |
| `Ctrl+C` | During a running turn: interrupt the agent and return to the prompt. At the prompt: discard whatever is typed so far (including a multi-line draft) and start a fresh prompt |
| `Ctrl+D` | Exit at an empty prompt (readline EOF semantics); on a non-empty line, deletes the character under the cursor |
| `Up` / `Down` | At the start/end of the draft: browse prompt history (your current, unsent draft is preserved and restored when you arrow back down past it). Elsewhere: move the cursor a line up/down |
| `Ctrl+O` | Toggle expand/collapse of tool call output — applies to every tool execution shown so far this session, not just the most recent one |

Prompt history is per-session and in-memory, matching upstream pi (the old
`~/.pi-python/tui-history` file from the previous prompt_toolkit UI is no
longer used; history replay on `/resume` is planned alongside that command).
There is no `Ctrl+R` reverse search — that was a prompt_toolkit extra with no
upstream pi equivalent.
| `Ctrl+A` / `Home`, `Ctrl+E` / `End` | Move to the start/end of the line |
| `Ctrl+B`/`Ctrl+F`, `Left`/`Right` | Move the cursor one character left/right |
| `Alt+B`/`Alt+F`, `Ctrl+Left`/`Ctrl+Right`, `Alt+Left`/`Alt+Right` | Move the cursor one word left/right |
| `Ctrl+W`, `Alt+Backspace` | Delete (kill) the word before the cursor |
| `Alt+D`, `Alt+Delete` | Delete (kill) the word after the cursor |
| `Ctrl+U` | Kill from the cursor to the start of the line |
| `Ctrl+K` | Kill from the cursor to the end of the line |
| `Ctrl+Y` | Yank (paste) the last kill; `Alt+Y` afterwards cycles to older kills |
| `Ctrl+-` | Undo |
| `Ctrl+]`, then any character | Jump the cursor forward to the next occurrence of that character (`Ctrl+Alt+]` jumps backward) |
| `Tab` | Accept the highlighted autocomplete suggestion (see below); a no-op otherwise |

**Declared deviation from upstream pi:** `Alt+Enter` is *not* one of
upstream's default newline keys (upstream only binds `Shift+Enter` and
`Ctrl+J`) — pipython adds it as an extra default binding, both to keep the
muscle memory phase 2's prompt_toolkit-based TUI trained and to give
`Alt+Enter`-only editors (like Terminal.app users typically expect, see
below) a working newline key out of the box.

**Known limitations on Apple's Terminal.app** (both apply equally to
upstream pi — this is a terminal-emulator limitation, not a porting gap):

- **`Shift+Enter` is indistinguishable from plain `Enter`** — Terminal.app
  doesn't report the Shift modifier on Enter at all, so it always submits.
  Use `Ctrl+J` (works everywhere) or `Alt+Enter` (see next point) instead.
- **`Alt+Enter` requires enabling "Use Option as Meta Key"** in
  Terminal.app's Profile settings (Keyboard tab) — without it, Option+Enter
  types a literal character instead of sending an Escape-prefixed sequence.
  Terminals with proper Kitty-protocol support (Ghostty, WezTerm, Kitty
  itself) or `xterm`'s `metaSendsEscape` need no such toggle.

Typing `@` opens fuzzy path completion for the current working directory;
typing `/` at the start of a line opens completion over the slash commands
below. Either kind of suggestion appears as a small overlay above the input
line — `Tab` accepts the highlighted item and writes it back into the
draft, `Escape` or continuing to type past it dismisses it.

**CJK word movement:** upstream pi's word-boundary movement (`Alt+B`/`Alt+F`
and friends) uses ICU dictionary segmentation for CJK text, treating each
Han/Kana/Hangul character as its own "word". This port simplifies that to
"one continuous run of CJK characters counts as a single word" — a
deliberate, documented divergence (not a bug) for Western-heavy text; ASCII
word movement is unaffected and follows the same rules as upstream.

### Slash commands

| Command | Behavior |
|---|---|
| `/help` | List all registered commands with their descriptions |
| `/model [id]` | No argument: show the current model. With an argument: switch the session's model to that litellm id |
| `/clear` | Start a new session (new JSONL file) that keeps the current model — any `/model` switch survives `/clear`; the old session's file is left on disk |
| `/tree` | Render the session's entry tree (connector-drawn, dim off the current path / bold-green on it), highlighting the path to the current leaf and marking it with `←` |
| `/branch <id-prefix>` | Branch to the entry whose id starts with the given prefix; errors on no match or an ambiguous (multi-match) prefix |
| `/quit` | Quit (equivalent to Ctrl+D) |

Unknown commands print an error and a `/help` hint instead of failing
silently.

### Terminal capabilities

The TUI detects true-color and [OSC 8 hyperlink](https://gist.github.com/egmontkob/eb114294efbcd5adb1944c9f3cb5feda)
support per-terminal (Kitty, Ghostty, WezTerm, iTerm2, VS Code, Alacritty,
Windows Terminal, Warp all get real clickable links where the TUI emits one;
unrecognized terminals fall back to plain text). **Under tmux, hyperlinks
are always rendered as plain text** — tmux only forwards OSC 8 sequences on
some terminfo/version combinations, and that support can't be probed
reliably, so this port conservatively never emits the escape sequence when
`$TMUX` is set (matching upstream's own conservative default for tmux).

### Environment variable

- `PI_PYTHON_MODEL` — default model id used when `--model` isn't passed.
