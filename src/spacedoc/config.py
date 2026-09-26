"""Settings, loaded from spacedoc.toml (or the file named by $SPACEDOC_CONFIG)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    # Local model server (Ollama exposes an OpenAI-compatible API under /v1)
    llm_base_url: str = "http://localhost:11434/v1"
    chat_model: str = "qwen3:8b"
    embed_model: str = "qwen3-embedding:0.6b"
    checker_model: str = "bespoke-minicheck"
    request_timeout_s: float = 300.0

    # Storage
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    corpus_dir: Path = field(default_factory=lambda: REPO_ROOT / "corpus")
    db_path: Path = field(default_factory=lambda: REPO_ROOT / "spacedoc.db")
    audit_path: Path = field(default_factory=lambda: REPO_ROOT / "audit" / "audit.jsonl")

    # Retrieval
    top_k: int = 6

    # Verification
    min_support_fraction: float = 0.5  # below this share of supported claims, abstain
    consistency_samples: int = 1  # >1 enables self-consistency sampling (slower)

    # Default environment tier when none is given
    default_tier: str = "T4"


def load_settings(path: str | Path | None = None) -> Settings:
    """Read settings from TOML; missing keys keep their defaults."""
    path = Path(path or os.environ.get("SPACEDOC_CONFIG", REPO_ROOT / "spacedoc.toml"))
    settings = Settings()
    if not path.exists():
        return settings
    with path.open("rb") as f:
        raw = tomllib.load(f)
    for fld in fields(Settings):
        if fld.name in raw:
            value = raw[fld.name]
            if isinstance(getattr(settings, fld.name), Path):
                value = Path(value)
                if not value.is_absolute():
                    value = path.parent / value
            setattr(settings, fld.name, value)
    return settings
