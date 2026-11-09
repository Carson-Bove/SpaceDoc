"""Local model access for the harness's own agents (the AI crewmember, action extraction).

Ollama's native API, as SpaceDoc uses: it is the only way to set the context window, seed and
JSON schema per request. `FakeLLM` stands in for a model in tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx


class LLM(Protocol):
    model: str

    def chat(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        temperature: float = 0.7,
        seed: int | None = None,
        max_tokens: int = 400,
    ) -> str: ...


@dataclass
class OllamaLLM:
    model: str
    base_url: str = "http://localhost:11434"
    num_ctx: int = 8192
    timeout_s: float = 600

    def chat(self, messages, *, schema=None, temperature=0.7, seed=None, max_tokens=400) -> str:
        options = {"temperature": temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens}
        if seed is not None:
            options["seed"] = seed
        body = {"model": self.model, "messages": messages, "stream": False, "options": options}
        if schema is not None:
            body["format"] = schema
        r = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout_s)
        if r.status_code == 404:
            raise RuntimeError(
                f"Ollama has no model {self.model!r}: run `ollama pull {self.model}`"
            )
        r.raise_for_status()
        return r.json()["message"]["content"]

    def check(self) -> str | None:
        """None if Ollama is up and has the model, else what is wrong."""
        try:
            tags = httpx.get(f"{self.base_url}/api/tags", timeout=10).json()
        except httpx.HTTPError as e:
            return f"Ollama is not reachable at {self.base_url} ({e}); start it with `ollama serve`"
        names = {m["name"] for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return f"Ollama has no model {self.model!r}: run `ollama pull {self.model}`"
        return None


@dataclass
class FakeLLM:
    """Answers from a function of (messages, schema); for tests."""

    respond: Callable[[list[dict], dict | None], str | dict]
    model: str = "fake"

    def chat(self, messages, *, schema=None, temperature=0.7, seed=None, max_tokens=400) -> str:
        out = self.respond(messages, schema)
        return out if isinstance(out, str) else json.dumps(out)
