"""MiniCheck inputs: one sentence at a time, cited passages together, P(yes)."""

import math

from spacedoc.answer.schema import DraftAnswer, Passage
from spacedoc.llm.client import ChatResult, FakeLLM
from spacedoc.verify.grounding import (
    LexicalOverlapChecker,
    MiniCheckChecker,
    split_sentences,
    yes_probability,
)


def test_split_sentences():
    assert split_sentences("Kidney stones cause pain.") == ["Kidney stones cause pain."]
    assert split_sentences("Stones cause pain. They may pass in 2.5 weeks.") == [
        "Stones cause pain.",
        "They may pass in 2.5 weeks.",
    ]
    # Abbreviations and lower-case continuations do not split.
    assert len(split_sentences("Use a sealed kit, e.g. A contained irrigator.")) == 1
    assert len(split_sentences("Pain radiates to the groin; fever suggests infection.")) == 1


def test_yes_probability():
    assert yes_probability(None) is None
    p = yes_probability([("Yes", math.log(0.9)), ("No", math.log(0.1))])
    assert abs(p - 0.9) < 1e-9
    assert yes_probability([("Maybe", -0.1)]) is None


def test_minicheck_reports_probability_and_requests_logprobs():
    reply = ChatResult(
        text="Yes", seconds=0.0, top_logprobs=[("Yes", math.log(0.97)), ("No", math.log(0.03))]
    )
    llm = FakeLLM(lambda m, s: reply)
    checker = MiniCheckChecker(llm, num_ctx=4096)
    v = checker.check("Stones cause pain.", "Kidney stones cause colicky pain.")
    assert v.supported and abs(v.probability - 0.97) < 1e-9 and "P(yes)=0.97" in v.raw
    p = llm.params[0]
    assert p.logprobs == 5 and p.num_ctx == 4096 and p.temperature == 0.0
    assert llm.calls[0][0]["content"].startswith("Document: Kidney stones")


def passage(cid, text):
    return Passage(cid=cid, chunk_id=f"c-{cid}", source_id="s", title="t", text=text)


def verify(demo_system, env, claim_text, cites, passages):
    verifier = demo_system.orchestrator.verifier
    verifier.checker = LexicalOverlapChecker(threshold=1.0)  # every content word must appear
    draft = DraftAnswer(
        summary="x",
        uncertainty="low",
        claims=[{"id": "C1", "kind": "sourced", "citations": cites, "text": claim_text}],
    )
    return verifier.verify("q", draft, passages, [], env, None, []).claims[0]


def test_every_sentence_must_be_supported(demo_system, env_t4):
    ps = [passage("S1", "Kidney stones cause colicky flank pain in astronauts.")]
    v = verify(
        demo_system,
        env_t4,
        "Kidney stones cause colicky flank pain. Tamsulosin always dissolves them overnight.",
        ["S1"],
        ps,
    )
    assert v.status == "unsupported" and not v.shown


def test_claim_combining_two_passages_is_checked_against_both(demo_system, env_t4):
    ps = [
        passage("S1", "Spaceflight raises urinary calcium through bone demineralization."),
        passage("S2", "Higher urinary calcium increases kidney stone formation."),
    ]
    claim = "Spaceflight raises urinary calcium and increases kidney stone formation."
    v = verify(demo_system, env_t4, claim, ["S1", "S2"], ps)
    assert v.status == "supported" and v.shown
    assert "S1+S2 together" in v.detail
