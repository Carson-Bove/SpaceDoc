"""LLM access. Two backends, chosen by `llm_backend` in spacedoc.toml:

- `ollama` (default): Ollama's native API (/api/chat, /api/embed). It is the only way to set
  the context window, thinking mode, top_k and seed per request. Ollama's OpenAI-compatible
  endpoint cannot set the context size, and Ollama's default (4,096 tokens on machines with
  less than 24 GiB of VRAM) is too small for SpaceDoc's prompts.
- `openai`: any OpenAI-compatible server (llama.cpp server, LM Studio, ...). The context size
  is whatever the server was started with.

`FakeLLM` stands in for a real model in tests and demo mode.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GenParams:
    """Generation settings for one call. `None` leaves the server or model default."""

    temperature: float = 0.0
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None
    max_tokens: int | None = None
    num_ctx: int | None = None  # context window; honored by the Ollama backend only
    think: bool | None = None  # thinking mode for models that support it; None = model default
    logprobs: int = 0  # >0: also return the top-N alternatives for the first output token

    @classmethod
    def from_profile(cls, profile: dict[str, Any], **overrides: Any) -> GenParams:
        known = {k: v for k, v in profile.items() if k in cls.__dataclass_fields__}
        return replace(cls(**known), **overrides)


@dataclass
class ChatResult:
    text: str
    seconds: float
    completion_tokens: int | None = None
    prompt_tokens: int | None = None
    thinking: str = ""
    done_reason: str | None = None  # "length" means the output hit max_tokens
    top_logprobs: list[tuple[str, float]] | None = None  # first output token's alternatives
    # Where the time went, as reported by the server (Ollama only): loading the model,
    # reading the prompt, writing the reply (thinking included).
    load_s: float | None = None
    prompt_s: float | None = None
    gen_s: float | None = None


class LLMError(RuntimeError):
    """The model server failed or could not be reached. Callers turn this into an abstention."""


class ContextOverflow(LLMError):
    """The prompt does not fit the context window, or the server shortened it."""


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    """Deliberately high estimate of a prompt's token count, for budget checks.

    English prose runs about 3.7-4.2 characters per token with Qwen3's tokenizer; dividing
    by 3 overestimates, so a prompt that passes this check fits in practice.
    """
    chars = sum(len(m.get("content") or "") for m in messages)
    return math.ceil(chars / 3.0) + 8 * len(messages)


def _check_budget(messages: list[dict[str, str]], p: GenParams) -> None:
    if p.num_ctx:
        need = estimate_tokens(messages) + (p.max_tokens or 0)
        if need > p.num_ctx:
            raise ContextOverflow(
                f"The prompt and answer need about {need} tokens but the context window is "
                f"{p.num_ctx}. Shorten the prompt or raise the context size in spacedoc.toml."
            )


def _looks_truncated(messages: list[dict[str, str]], prompt_tokens: int) -> bool:
    """True if the server evaluated far fewer prompt tokens than the text could contain.

    Even dense text averages more than one token per 6 characters, so a lower count means
    the server cut the prompt (Ollama does this silently when it exceeds the context).
    """
    chars = sum(len(m.get("content") or "") for m in messages)
    return prompt_tokens < chars / 6


def _ns_to_s(value: Any) -> float | None:
    """Ollama reports durations in nanoseconds."""
    return value / 1e9 if isinstance(value, int | float) else None


def _is_context_error(message: str) -> bool:
    """The server refused a prompt or answer that does not fit its context window."""
    m = message.lower()
    return "context" in m and ("exceed" in m or "longer than" in m)


class LLM(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None = None,
        params: GenParams | None = None,
    ) -> ChatResult: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _skip(_data: dict) -> None:
    pass


class _HTTPClient:
    def __init__(self, root: str, timeout_s: float) -> None:
        self.root = root
        self.timeout_s = timeout_s
        self._http = httpx.Client(timeout=timeout_s)

    def get(self, path: str, label: str = "model list") -> dict[str, Any]:
        return self.post(path, None, label)

    def post(self, path: str, body: dict[str, Any] | None, model: str) -> dict[str, Any]:
        with self._errors(model):
            if body is None:
                resp = self._http.get(f"{self.root}{path}", timeout=min(self.timeout_s, 10.0))
            else:
                resp = self._http.post(f"{self.root}{path}", json=body)
        self._check(resp, model)
        try:
            return resp.json()
        except ValueError as e:
            raise LLMError(f"Model server returned invalid JSON for {model}") from e

    def delete(self, path: str, body: dict[str, Any], model: str) -> None:
        with self._errors(model):
            resp = self._http.request("DELETE", f"{self.root}{path}", json=body)
        self._check(resp, model)

    def stream(
        self, path: str, body: dict[str, Any], model: str, on_line: Callable[[dict], None]
    ) -> None:
        """POST and hand each JSON line of the streamed reply to `on_line`."""
        with (
            self._errors(model),
            self._http.stream("POST", f"{self.root}{path}", json=body) as resp,
        ):
            if resp.status_code >= 400:
                resp.read()
                self._check(resp, model)
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError as e:
                    raise LLMError(f"Model server returned invalid JSON for {model}") from e
                if data.get("error"):
                    raise LLMError(f"Model server error for {model}: {data['error']}")
                on_line(data)

    @contextmanager
    def _errors(self, model: str) -> Iterator[None]:
        try:
            yield
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot reach the model server at {self.root}. Is Ollama running?"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMError(
                f"The model server did not answer within {self.timeout_s:.0f} s ({model})."
            ) from e
        except httpx.HTTPError as e:
            raise LLMError(f"Model server request failed: {e}") from e

    @staticmethod
    def _check(resp: httpx.Response, model: str) -> None:
        if resp.status_code < 400:
            return
        try:
            detail = resp.json().get("error") or resp.text
        except ValueError:
            detail = resp.text
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        raise LLMError(f"Model server error {resp.status_code} for {model}: {detail}")


class OllamaLLM:
    """Ollama's native API: per-request context size, thinking control, top_k and seed."""

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embed_model: str | None = None,
        timeout_s: float = 300.0,
        keep_alive: str | None = None,
    ) -> None:
        root = base_url.rstrip("/")
        root = root.removesuffix("/v1")
        self._client = _HTTPClient(root, timeout_s)
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.keep_alive = keep_alive  # e.g. "30m"; None = Ollama's default (5 minutes)
        self._cannot_think = False

    def chat(self, messages, schema=None, params=None) -> ChatResult:
        p = params or GenParams()
        _check_budget(messages, p)
        options = {
            "temperature": p.temperature,
            "top_p": p.top_p,
            "top_k": p.top_k,
            "seed": p.seed,
            "num_predict": p.max_tokens,
            "num_ctx": p.num_ctx,
        }
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            "options": {k: v for k, v in options.items() if v is not None},
            # Fail instead of silently dropping text that does not fit the context window:
            # truncate=false for the prompt, shift=false during generation. Recent Ollama
            # versions honor both; older ones ignore them, and the prompt-token check below
            # still catches a shortened prompt.
            "truncate": False,
            "shift": False,
        }
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        if schema is not None:
            body["format"] = schema  # constrained decoding; applied after any thinking block
        if p.think is not None and not (p.think and self._cannot_think):
            body["think"] = p.think
        if p.logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = p.logprobs

        start = time.perf_counter()
        try:
            data = self._client.post("/api/chat", body, self.chat_model)
        except LLMError as e:
            # Models without thinking support reject think=true; ask again without it.
            if body.get("think") is True and "does not support thinking" in str(e):
                self._cannot_think = True
                body.pop("think")
                data = self._client.post("/api/chat", body, self.chat_model)
            elif _is_context_error(str(e)):
                raise ContextOverflow(
                    f"{e}. Raise the context size (chat_num_ctx or checker_num_ctx) in "
                    "spacedoc.toml."
                ) from e
            else:
                raise
        msg = data.get("message") or {}

        prompt_tokens = data.get("prompt_eval_count")
        cached = data.get("prompt_eval_cached_count")
        if prompt_tokens is not None and cached is not None:
            prompt_tokens += cached
            # Only trusted when the cached count is reported; otherwise a cache hit would look
            # like truncation.
            if _looks_truncated(messages, prompt_tokens):
                raise ContextOverflow(
                    f"The model server evaluated only {prompt_tokens} prompt tokens, so it cut "
                    "the prompt to fit its context window. Raise chat_num_ctx in spacedoc.toml."
                )

        top = None
        if p.logprobs and data.get("logprobs"):
            first = data["logprobs"][0]
            top = [(t["token"], t["logprob"]) for t in first.get("top_logprobs") or []]
            if not top:
                top = [(first["token"], first["logprob"])]

        return ChatResult(
            text=msg.get("content") or "",
            seconds=time.perf_counter() - start,
            completion_tokens=data.get("eval_count"),
            prompt_tokens=prompt_tokens,
            thinking=msg.get("thinking") or "",
            done_reason=data.get("done_reason"),
            top_logprobs=top,
            load_s=_ns_to_s(data.get("load_duration")),
            prompt_s=_ns_to_s(data.get("prompt_eval_duration")),
            gen_s=_ns_to_s(data.get("eval_duration")),
        )

    def installed_models(self) -> list[str]:
        """Names of the models this Ollama server has, e.g. ["qwen3:8b", ...]."""
        return list(self.model_sizes())

    def model_sizes(self) -> dict[str, int]:
        """Installed models and their size on disk in bytes."""
        models = self._client.get("/api/tags").get("models", [])
        return {m["name"]: int(m.get("size") or 0) for m in models}

    def pull_model(self, name: str, progress: Callable[[dict], None] | None = None) -> None:
        """Download a model. Re-pulling a tag makes Ollama delete the files it replaced."""
        self._client.stream("/api/pull", {"model": name, "stream": True}, name, progress or _skip)

    def delete_model(self, name: str) -> None:
        self._client.delete("/api/delete", {"model": name}, name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embed_model:
            raise LLMError("No embedding model configured")
        body: dict[str, Any] = {"model": self.embed_model, "input": texts}
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        data = self._client.post("/api/embed", body, self.embed_model)
        return data["embeddings"]


class OpenAICompatLLM:
    """Any server that implements /chat/completions and /embeddings (llama.cpp, LM Studio...)."""

    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embed_model: str | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self._client = _HTTPClient(base_url.rstrip("/"), timeout_s)
        self.chat_model = chat_model
        self.embed_model = embed_model

    def chat(self, messages, schema=None, params=None) -> ChatResult:
        p = params or GenParams()
        _check_budget(messages, p)
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": p.temperature,
        }
        for key, value in (("top_p", p.top_p), ("seed", p.seed), ("max_tokens", p.max_tokens)):
            if value is not None:
                body[key] = value
        if p.top_k is not None:
            body["top_k"] = p.top_k  # extension: llama.cpp and LM Studio honor it
        if p.think is not None:
            # Ollama and OpenAI read reasoning_effort; llama.cpp reads chat_template_kwargs.
            body["reasoning_effort"] = "medium" if p.think else "none"
            body["chat_template_kwargs"] = {"enable_thinking": p.think}
        if p.logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = p.logprobs
        if schema is not None:
            # Constrained decoding: the server masks tokens that would break the schema.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema},
            }
        start = time.perf_counter()
        data = self._client.post("/chat/completions", body, self.chat_model)
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        top = None
        content_lp = ((choice.get("logprobs") or {}).get("content")) or []
        if p.logprobs and content_lp:
            first = content_lp[0]
            top = [(t["token"], t["logprob"]) for t in first.get("top_logprobs") or []]
        return ChatResult(
            text=msg.get("content") or "",
            seconds=time.perf_counter() - start,
            completion_tokens=usage.get("completion_tokens"),
            prompt_tokens=usage.get("prompt_tokens"),
            thinking=msg.get("reasoning") or msg.get("reasoning_content") or "",
            done_reason=choice.get("finish_reason"),
            top_logprobs=top,
        )

    def installed_models(self) -> list[str]:
        return [m["id"] for m in self._client.get("/models").get("data", [])]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embed_model:
            raise LLMError("No embedding model configured")
        data = self._client.post(
            "/embeddings", {"model": self.embed_model, "input": texts}, self.embed_model
        )
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]


def connect(
    backend: str,
    base_url: str,
    chat_model: str,
    embed_model: str | None,
    timeout_s: float,
    keep_alive: str | None = None,
) -> OllamaLLM | OpenAICompatLLM:
    """Create a client for the configured backend ("ollama" or "openai")."""
    if backend == "ollama":
        return OllamaLLM(base_url, chat_model, embed_model, timeout_s, keep_alive)
    if backend == "openai":
        return OpenAICompatLLM(base_url, chat_model, embed_model, timeout_s)
    raise ValueError(f"Unknown llm_backend {backend!r}; use 'ollama' or 'openai'")


Responder = Callable[[list[dict[str, str]], dict[str, Any] | None], "str | ChatResult"]


class FakeLLM:
    """Deterministic stand-in for tests and demo mode. Not a model.

    `responder` receives the messages (and schema) and returns the reply text, or a full
    ChatResult (e.g. to include thinking notes).
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
        self.params: list[GenParams | None] = []

    def chat(self, messages, schema=None, params=None) -> ChatResult:
        self.calls.append(messages)
        self.params.append(params)
        reply = self.responder(messages, schema)
        return reply if isinstance(reply, ChatResult) else ChatResult(text=reply, seconds=0.0)

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
