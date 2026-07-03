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
