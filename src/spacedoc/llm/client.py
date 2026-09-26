"""LLM access through an OpenAI-compatible HTTP API (Ollama, llama.cpp server, LM Studio...).

SpaceDoc never imports a runtime directly, so the backend can change without touching
the rest of the code. `FakeLLM` stands in for a real model in tests and demo mode.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass
class ChatResult:
    text: str
    seconds: float
    completion_tokens: int | None = None
    prompt_tokens: int | None = None


class LLM(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> ChatResult: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatLLM:
    """Client for any server that implements /chat/completions and /embeddings."""

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embed_model: str | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model
        self._http = httpx.Client(timeout=timeout_s)

    def chat(self, messages, schema=None, temperature=0.0) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if schema is not None:
            # Constrained decoding: the server masks tokens that would break the schema.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema},
            }
        start = time.perf_counter()
        resp = self._http.post(f"{self.base_url}/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        return ChatResult(
            text=data["choices"][0]["message"]["content"] or "",
            seconds=time.perf_counter() - start,
            completion_tokens=usage.get("completion_tokens"),
            prompt_tokens=usage.get("prompt_tokens"),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embed_model:
            raise RuntimeError("No embedding model configured")
        resp = self._http.post(
            f"{self.base_url}/embeddings", json={"model": self.embed_model, "input": texts}
        )
        resp.raise_for_status()
        items = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]


Responder = Callable[[list[dict[str, str]], dict[str, Any] | None], str]


class FakeLLM:
    """Deterministic stand-in for tests and demo mode. Not a model.

    `responder` receives the messages (and schema) and returns the reply text.
    Embeddings are hashed bag-of-words vectors: crude, but deterministic and
    good enough to exercise the retrieval code without a model.
    """

    DIM = 256

    def __init__(self, responder: Responder | list[str] | None = None) -> None:
        if isinstance(responder, list):
            replies = list(responder)
            responder = lambda _m, _s: replies.pop(0)  # noqa: E731
        self.responder = responder or (lambda _m, _s: "{}")
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages, schema=None, temperature=0.0) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(text=self.responder(messages, schema), seconds=0.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out
