"""LLM clients against a fake server that returns Ollama's real response shapes."""

import json

import httpx
import pytest

from spacedoc.config import Settings
from spacedoc.llm.client import (
    ContextOverflow,
    GenParams,
    LLMError,
    OllamaLLM,
    OpenAICompatLLM,
    estimate_tokens,
)
from spacedoc.system import generation_plan

MESSAGES = [
    {"role": "system", "content": "You are SpaceDoc. " * 40},
    {"role": "user", "content": "Sharp right flank pain that moves toward my groin."},
]


def fake_server(client, handler):
    """Route the client's HTTP calls to `handler(request) -> httpx.Response`."""
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    client._client._http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return seen


def ollama_reply(content="{}", thinking="", **extra):
    body = {
        "model": "qwen3:8b",
        "message": {"role": "assistant", "content": content, "thinking": thinking},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 400,
        "prompt_eval_cached_count": 0,
        "eval_count": 120,
    }
    body.update(extra)
    return httpx.Response(200, json=body)


def test_ollama_native_request_carries_context_thinking_and_sampling():
    llm = OllamaLLM("http://localhost:11434/v1", "qwen3:8b")
    seen = fake_server(llm, lambda r: ollama_reply('{"a": 1}', thinking="Consider stones."))
    params = GenParams(
        temperature=0.6, top_p=0.95, top_k=20, seed=42, max_tokens=6144, num_ctx=12288, think=True
    )
    result = llm.chat(MESSAGES, schema={"type": "object"}, params=params)

    req = seen[0]
    assert req.url.path == "/api/chat"  # "/v1" is stripped: the native API is used
    body = json.loads(req.content)
    assert body["think"] is True and body["stream"] is False
    assert body["truncate"] is False and body["shift"] is False  # fail rather than cut text
    assert body["format"] == {"type": "object"}
    assert body["options"] == {
        "temperature": 0.6,
        "top_p": 0.95,
        "top_k": 20,
        "seed": 42,
        "num_predict": 6144,
        "num_ctx": 12288,
    }
    assert result.text == '{"a": 1}' and result.thinking == "Consider stones."
    assert result.completion_tokens == 120 and result.prompt_tokens == 400
    assert result.done_reason == "stop"
    assert result.load_s is None  # no durations in this reply


def test_ollama_durations_are_reported_in_seconds():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    reply = ollama_reply(
        load_duration=2_000_000_000, prompt_eval_duration=500_000_000, eval_duration=8_250_000_000
    )
    fake_server(llm, lambda r: reply)
    result = llm.chat(MESSAGES)
    assert (result.load_s, result.prompt_s, result.gen_s) == (2.0, 0.5, 8.25)


def test_thinking_is_dropped_for_models_that_cannot_think():
    llm = OllamaLLM("http://localhost:11434", "medgemma:4b")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body.get("think"):
            return httpx.Response(400, json={"error": '"medgemma:4b" does not support thinking'})
        return ollama_reply("{}")

    fake_server(llm, handler)
    llm.chat(MESSAGES, params=GenParams(think=True))
    llm.chat(MESSAGES, params=GenParams(think=True))
    assert [("think" in c) for c in calls] == [True, False, False]  # remembered after one refusal


def test_server_side_prompt_truncation_is_detected():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    long = [{"role": "user", "content": "word " * 4000}]  # ~20,000 characters
    fake_server(llm, lambda r: ollama_reply(prompt_eval_count=900, prompt_eval_cached_count=0))
    with pytest.raises(ContextOverflow):
        llm.chat(long)


def test_keep_alive_is_sent_when_set():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b", "qwen3-embedding:0.6b", keep_alive="30m")
    seen = fake_server(
        llm,
        lambda r: (
            ollama_reply()
            if r.url.path == "/api/chat"
            else httpx.Response(200, json={"embeddings": [[0.1]]})
        ),
    )
    llm.chat(MESSAGES)
    llm.embed(["x"])
    assert [json.loads(r.content)["keep_alive"] for r in seen] == ["30m", "30m"]
    plain = OllamaLLM("http://localhost:11434", "qwen3:8b")
    seen = fake_server(plain, lambda r: ollama_reply())
    plain.chat(MESSAGES)
    assert "keep_alive" not in json.loads(seen[0].content)


def test_server_refusing_a_long_prompt_is_a_context_overflow():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    error = {"error": "the request exceeds the available context size, try increasing it"}
    fake_server(llm, lambda r: httpx.Response(400, json=error))
    with pytest.raises(ContextOverflow, match="chat_num_ctx"):
        llm.chat(MESSAGES)


def test_cached_tokens_count_towards_the_prompt():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    long = [{"role": "user", "content": "word " * 4000}]
    fake_server(llm, lambda r: ollama_reply(prompt_eval_count=10, prompt_eval_cached_count=4000))
    assert llm.chat(long).prompt_tokens == 4010


def test_no_truncation_check_without_cache_information():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    long = [{"role": "user", "content": "word " * 4000}]
    reply = ollama_reply()
    body = reply.json()
    body.pop("prompt_eval_cached_count")
    body["prompt_eval_count"] = 5  # could be a cache hit; must not be treated as truncation
    fake_server(llm, lambda r: httpx.Response(200, json=body))
    assert llm.chat(long).text == "{}"


def test_budget_check_refuses_a_prompt_that_cannot_fit():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    seen = fake_server(llm, lambda r: ollama_reply())
    params = GenParams(num_ctx=estimate_tokens(MESSAGES) + 100, max_tokens=500)
    with pytest.raises(ContextOverflow):
        llm.chat(MESSAGES, params=params)
    assert not seen  # nothing was sent


@pytest.mark.parametrize(
    "error,match",
    [
        (httpx.ConnectError("refused"), "Is Ollama running"),
        (httpx.ReadTimeout("slow"), "did not answer within"),
    ],
)
def test_transport_failures_become_llm_errors(error, match):
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b", timeout_s=5)

    def handler(request):
        raise error

    fake_server(llm, handler)
    with pytest.raises(LLMError, match=match):
        llm.chat(MESSAGES)


def test_missing_model_reports_the_server_message():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    fake_server(llm, lambda r: httpx.Response(404, json={"error": 'model "qwen3:8b" not found'}))
    with pytest.raises(LLMError, match="not found"):
        llm.chat(MESSAGES)


def test_first_token_logprobs_are_returned():
    llm = OllamaLLM("http://localhost:11434", "bespoke-minicheck:7b")
    logprobs = [
        {
            "token": "Yes",
            "logprob": -0.05,
            "top_logprobs": [{"token": "Yes", "logprob": -0.05}, {"token": "No", "logprob": -3.0}],
        }
    ]
    seen = fake_server(llm, lambda r: ollama_reply("Yes", logprobs=logprobs))
    result = llm.chat(MESSAGES, params=GenParams(logprobs=5))
    assert json.loads(seen[0].content)["top_logprobs"] == 5
    assert result.top_logprobs == [("Yes", -0.05), ("No", -3.0)]


def test_native_embeddings():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b", "qwen3-embedding:0.6b")
    seen = fake_server(llm, lambda r: httpx.Response(200, json={"embeddings": [[0.1, 0.2]]}))
    assert llm.embed(["kidney stone"]) == [[0.1, 0.2]]
    assert seen[0].url.path == "/api/embed"


def test_openai_backend_maps_thinking_and_reads_reasoning():
    llm = OpenAICompatLLM("http://localhost:8080/v1", "qwen3-8b")
    reply = {
        "choices": [
            {
                "message": {"content": "{}", "reasoning_content": "Let me think."},
                "finish_reason": "length",
            }
        ],
        "usage": {"prompt_tokens": 300, "completion_tokens": 50},
    }
    seen = fake_server(llm, lambda r: httpx.Response(200, json=reply))
    result = llm.chat(MESSAGES, params=GenParams(think=False, top_k=20, seed=7))
    body = json.loads(seen[0].content)
    assert body["reasoning_effort"] == "none"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["top_k"] == 20 and body["seed"] == 7
    assert result.thinking == "Let me think." and result.done_reason == "length"


def test_generation_plan_uses_qwen_thinking_settings():
    d = generation_plan(Settings()).draft
    assert (d.think, d.temperature, d.top_p, d.top_k) == (True, 0.6, 0.95, 20)
    assert d.num_ctx == 12288 and d.seed == 42
    assert d.temperature > 0  # Qwen3: no greedy decoding in thinking mode


def test_model_check_names_missing_models(monkeypatch):
    import spacedoc.system as system_mod

    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    tags = {"models": [{"name": "qwen3:8b"}, {"name": "qwen3-embedding:0.6b"}]}
    fake_server(llm, lambda r: httpx.Response(200, json=tags))
    monkeypatch.setattr(system_mod, "connect", lambda *a, **k: llm)
    check = system_mod.check_models(Settings(consult_model="qwen3:4b"))
    assert check.reachable and check.missing == ["qwen3:4b", "bespoke-minicheck:7b"]
    assert check.problems()[1] == (
        "Model bespoke-minicheck:7b is not installed. Run: spacedoc models pull"
    )


def test_model_check_reports_an_unreachable_server(monkeypatch):
    import spacedoc.system as system_mod

    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")

    def refuse(request):
        raise httpx.ConnectError("refused")

    fake_server(llm, refuse)
    monkeypatch.setattr(system_mod, "connect", lambda *a, **k: llm)
    check = system_mod.check_models(Settings())
    assert not check.reachable and "Is Ollama running?" in check.problems()[0]
