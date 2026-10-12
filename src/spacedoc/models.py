"""Which local models SpaceDoc needs, and which old ones it may offer to remove.

A model is "old" when SpaceDoc downloaded it (`spacedoc models pull`), compared it
(`spacedoc bench`) or its setup guide named it, and spacedoc.toml no longer names it.
Other models on the Ollama server are never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from spacedoc.config import Settings

# Every model tag docs/phase1-getting-started.md tells you to download or try.
GUIDE_MODELS = (
    "qwen3:8b",
    "qwen3:4b",
    "qwen3-embedding:0.6b",
    "bespoke-minicheck:7b",
    "gemma4:e4b",
    "gemma4:e4b-it-qat",
    "medgemma:4b",
    "medgemma1.5:4b",
)


def tag(name: str) -> str:
    """Ollama's full name for a model: "mistral" is stored as "mistral:latest"."""
    return name if ":" in name else f"{name}:latest"


def configured_models(settings: Settings) -> list[str]:
    """The models spacedoc.toml names, in the order they are downloaded."""
    names = [
        settings.chat_model,
        settings.consult_model,
        settings.embed_model,
        settings.checker_model,
    ]
    return list(dict.fromkeys(n for n in names if n))


def missing_models(settings: Settings, installed: dict[str, int]) -> list[str]:
    have = {tag(n) for n in installed}
    return [n for n in configured_models(settings) if tag(n) not in have]


def old_models(
    settings: Settings, installed: dict[str, int], record: ModelRecord
) -> dict[str, int]:
    """Installed models SpaceDoc used before and spacedoc.toml no longer names, with sizes."""
    keep = {tag(n) for n in configured_models(settings)}
    known = {tag(n) for n in GUIDE_MODELS} | record.names()
    return {n: size for n, size in installed.items() if tag(n) in known and tag(n) not in keep}


def gigabytes(size: int) -> str:
    return f"{size / 1e9:.1f} GB"


class ModelRecord:
    """The models SpaceDoc has downloaded or compared, kept in a small JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def names(self) -> set[str]:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return set()
        return {tag(n) for n in data.get("models", [])}

    def add(self, names: list[str]) -> None:
        self._write(self.names() | {tag(n) for n in names})

    def discard(self, names: list[str]) -> None:
        self._write(self.names() - {tag(n) for n in names})

    def _write(self, names: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"models": sorted(names)}, indent=2) + "\n")
