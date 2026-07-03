"""Model alias mapping (spec §3). Phase 1 keeps it empty but wired."""

MODEL_ALIASES: dict[str, str] = {}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)
