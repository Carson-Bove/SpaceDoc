"""How the orchestrator behaves when the model server misbehaves or the context is tight."""

import json

from spacedoc.agent.orchestrator import GenerationPlan
from spacedoc.answer.schema import DraftAnswer
from spacedoc.llm.client import ChatResult, FakeLLM, GenParams, LLMError, estimate_tokens
from spacedoc.verify.rules import screen_passage


class FailingLLM(FakeLLM):
    def chat(self, messages, schema=None, params=None):
        raise LLMError("Cannot reach the model server at http://localhost:11434.")


class FailingEmbedder(FakeLLM):
    def embed(self, texts):
        raise LLMError("Model server error 404 for qwen3-embedding:0.6b: not found")


def draft_json(**kw):
    return json.dumps(DraftAnswer(summary="ok", uncertainty="low", **kw).model_dump())


def test_unreachable_model_becomes_an_abstention(demo_system, env_t4):
    orch = demo_system.orchestrator
    orch.llm = FailingLLM()
    v = orch.ask("kidney stones", env_t4, None)
    assert v.abstained
    assert "Cannot reach the model server" in v.abstain_reason
    assert "MODEL-ERROR" in {f.rule_id for f in v.findings}


def test_failed_search_abstains_without_calling_the_model(demo_system, env_t4):
    orch = demo_system.orchestrator
    orch.retriever.embedder = FailingEmbedder()
    orch.llm = FakeLLM([])  # any call would fail: the reply list is empty
    v = orch.ask("kidney stones", env_t4, None)
    assert v.abstained and "Source search failed" in v.abstain_reason
    assert not orch.llm.calls


def test_passages_are_trimmed_to_fit_the_context(demo_system, env_t4):
    orch = demo_system.orchestrator
    found = orch.retriever.search("flank pain kidney stones eye", env_t4, 6)
    # Mirror ask(): injected passages are screened out and the rest renumbered.
    clean = [p for p in found if not screen_passage(p)]
    passages = [p.model_copy(update={"cid": f"S{i + 1}"}) for i, p in enumerate(clean)]
    assert len(passages) >= 2
    full = orch._messages("flank pain kidney stones eye", env_t4, None, passages)
    one_less = orch._messages("flank pain kidney stones eye", env_t4, None, passages[:-1])
    max_tokens = 200
    # Room for all but the last passage.
    orch.generation = GenerationPlan(
        draft=GenParams(num_ctx=estimate_tokens(one_less) + max_tokens, max_tokens=max_tokens)
    )
    assert estimate_tokens(full) + max_tokens > orch.generation.draft.num_ctx
    orch.llm = FakeLLM([draft_json(abstain=True)])
    v = orch.ask("flank pain kidney stones eye", env_t4, None)
    assert "CONTEXT-TRIM" in {f.rule_id for f in v.findings}
    assert len(v.passages) == len(passages) - 1


def test_reply_cut_off_at_length_is_retried_without_the_fragment(demo_system, env_t4):
    orch = demo_system.orchestrator
    replies = [
        ChatResult(text='{"summary": "Kidney st', seconds=0.0, done_reason="length"),
        ChatResult(text=draft_json(abstain=True), seconds=0.0),
    ]

    class LengthLLM(FakeLLM):
        def chat(self, messages, schema=None, params=None):
            self.calls.append(messages)
            return replies.pop(0)

    orch.llm = LengthLLM()
    v = orch.ask("kidney stones", env_t4, None)
    assert "OUTPUT-LIMIT" in {f.rule_id for f in v.findings}
    retry = orch.llm.calls[1]
    assert all('"summary": "Kidney st' not in m["content"] for m in retry)
    assert "cut off" in retry[-1]["content"]


def test_consistency_samples_use_different_seeds(demo_system, env_t4):
    orch = demo_system.orchestrator
    orch.consistency_samples = 3
    orch.generation = GenerationPlan(draft=GenParams(temperature=0.6, seed=42))
    reply = draft_json(differential=[{"condition": "Nephrolithiasis", "likelihood": "high"}])
    orch.llm = FakeLLM([reply, reply, reply])
    orch.ask("kidney stones", env_t4, None)
    assert [p.seed for p in orch.llm.params] == [42, 43, 44]


def test_failed_grounding_check_hides_the_claim(demo_system, env_t4):
    orch = demo_system.orchestrator

    class BrokenChecker:
        name = "broken"

        def check(self, claim, passage):
            raise LLMError("The model server did not answer within 300 s (bespoke-minicheck:7b).")

    orch.verifier.checker = BrokenChecker()
    claim = {
        "id": "C1",
        "kind": "sourced",
        "citations": ["S1"],
        "text": "Kidney stones typically cause colicky flank pain that may radiate to the groin.",
    }
    orch.llm = FakeLLM([draft_json(claims=[claim])])
    v = orch.ask("colicky flank pain kidney stones", env_t4, None)
    assert not v.claims[0].shown and v.claims[0].status == "unsupported"
    assert "CHECK-ERROR" in {f.rule_id for f in v.findings}
