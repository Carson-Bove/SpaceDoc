"""Settings, loaded from spacedoc.toml (or the file named by $SPACEDOC_CONFIG)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    # Local model server. "ollama" uses Ollama's native API, which can set the context
    # window, thinking mode, top_k and seed per request; "openai" works with any
    # OpenAI-compatible server (llama.cpp, LM Studio) at its own context size.
    llm_backend: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    chat_model: str = "qwen3:8b"
    embed_model: str = "qwen3-embedding:0.6b"
    checker_model: str = "bespoke-minicheck:7b"
    request_timeout_s: float = 300.0

    # Generation. Ollama's default context (4,096 tokens on machines with < 24 GiB VRAM)
    # is too small: a first-pass prompt is ~3,300 tokens before the model writes anything.
    chat_num_ctx: int = 12288
    checker_num_ctx: int = 4096
    think_draft: bool = True  # thinking for the first (reasoning) pass
    think_finalize: bool = False  # the second pass only inserts calculator results
    draft_max_tokens: int = 6144  # thinking + JSON answer
    finalize_max_tokens: int = 2048
    seed: int = 42  # fixed so sampled runs are repeatable
    review_max_tokens: int = 1024  # reasoning summaries for clinical review
    # Qwen3's recommended settings. Its model card warns against greedy decoding
    # (temperature 0) in thinking mode, which can cause endless repetition.
    sampling_thinking: dict = field(
        default_factory=lambda: {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
    )
    sampling_plain: dict = field(
        default_factory=lambda: {"temperature": 0.7, "top_p": 0.8, "top_k": 20}
    )

    # Storage
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    corpus_dir: Path = field(default_factory=lambda: REPO_ROOT / "corpus")
    db_path: Path = field(default_factory=lambda: REPO_ROOT / "spacedoc.db")
    audit_path: Path = field(default_factory=lambda: REPO_ROOT / "audit" / "audit.jsonl")

    # Retrieval
    top_k: int = 6
    # Qwen3-Embedding expects an instruction on queries (not documents); its model card
    # reports 1-5% worse retrieval without one. Set to "" for embedders that don't use one.
    embed_query_instruction: str = (
        "Given a medical question from a spacecraft crew member, retrieve reference "
        "passages that answer it"
    )

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
