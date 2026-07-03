"""AgentSessionConfig: the single injection point for AgentSession construction (spec §4.1)."""

from dataclasses import dataclass
from pathlib import Path

from .ai.client import ModelClient
from .tools.base import Tool


@dataclass
class AgentSessionConfig:
    model: str
    cwd: str | Path
    system_prompt: str | None = None
    tools: list[Tool] | None = None
    session_dir: str | Path | None = None
    max_turns: int = 50
    client: ModelClient | None = None
