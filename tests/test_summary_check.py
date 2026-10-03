"""The summary and patient-record claims are checked before they are shown."""

from spacedoc.agent.orchestrator import NO_MODEL
from spacedoc.answer.schema import DraftAnswer, Passage
from spacedoc.demo import DEMO_PATIENT
from spacedoc.llm.client import FakeLLM, LLMError
from spacedoc.verify.grounding import LexicalOverlapChecker
from spacedoc.verify.pipeline import SUMMARY_ABSTAINED, SUMMARY_REMOVED
from spacedoc.verify.rules import patient_document

STONE = Passage(
    cid="S1",
    chunk_id="c1",
    source_id="s",
    title="t",
    text="Kidney stones cause colicky flank pain that radiates to the groin.",
)
STONE_CLAIM = {
    "id": "C1",
    "kind": "sourced",
    "citations": ["S1"],
    "text": "Kidney stones cause colicky flank pain that radiates to the groin.",
}


def verify(system, env, summary, claims=(), patient=None, actions=(), abstain=False, **kw):
    verifier = system.orchestrator.verifier
    verifier.checker = LexicalOverlapChecker(threshold=1.0)  # every content word must appear
    draft = DraftAnswer(
        summary=summary,
        uncertainty="low",
        claims=list(claims),
        actions=list(actions),
        abstain=abstain,
    )
    return verifier.verify("q", draft, [STONE], [], env, patient, [], **kw)


def rule_ids(v):
    return [f.rule_id for f in v.findings]


def test_supported_summary_is_kept(demo_system, env_t4):
    v = verify(demo_system, env_t4, "Kidney stones cause flank pain.", [STONE_CLAIM])
    assert v.summary == "Kidney stones cause flank pain."
    assert not any(r.startswith("SUMMARY") for r in rule_ids(v))


def test_unsupported_sentence_is_trimmed(demo_system, env_t4):
    v = verify(
        demo_system,
        env_t4,
        "Kidney stones cause flank pain. Tamsulosin always dissolves them overnight.",
        [STONE_CLAIM],
    )
    assert v.summary == "Kidney stones cause flank pain."
    trimmed = next(f for f in v.findings if f.rule_id == "SUMMARY-TRIMMED")
    assert "Tamsulosin always dissolves" in trimmed.message


def test_summary_numbers_must_be_traceable(demo_system, env_t4):
    v = verify(demo_system, env_t4, "Kidney stones cause flank pain in 80 percent.", [STONE_CLAIM])
    assert v.summary == SUMMARY_REMOVED
    replaced = next(f for f in v.findings if f.rule_id == "SUMMARY-REPLACED")
    assert "80" in replaced.message


def test_summary_cannot_lean_on_hidden_claims_or_blocked_actions(demo_system, env_t4):
    hidden = {**STONE_CLAIM, "id": "C2", "citations": ["S9"], "text": "Stones dissolve in juice."}
    evacuate = {"id": "A1", "text": "Evacuate to a hospital", "kind": "escalate", "risk_tier": "R3"}
    v = verify(
        demo_system,
        env_t4,
        "Stones dissolve in juice. Evacuate to a hospital.",
        [STONE_CLAIM, hidden],
        actions=[evacuate],
    )
    assert v.actions[0].status == "blocked"  # no evacuation from deep space
    assert v.summary == SUMMARY_REMOVED and "SUMMARY-REPLACED" in rule_ids(v)


def test_abstention_summary_with_nothing_checked(demo_system, env_t4):
    v = verify(demo_system, env_t4, "It is probably appendicitis.", abstain=True)
    assert v.abstained and v.summary == SUMMARY_ABSTAINED


def test_failed_check_hides_the_summary(demo_system, env_t4):
    verifier = demo_system.orchestrator.verifier

    class Down:
        def check(self, claim, passage):
            raise LLMError("checker offline")

    verifier.checker = Down()
    draft = DraftAnswer(summary="Kidney stones cause pain.", uncertainty="low")
    v = verifier.verify("q", draft, [STONE], [], env_t4, DEMO_PATIENT, [])
    assert v.summary == SUMMARY_REMOVED and "CHECK-ERROR" in rule_ids(v)


def test_system_summaries_are_not_checked(demo_system, env_t4):
    class Unreachable(FakeLLM):
        def chat(self, messages, schema=None, params=None):
            raise LLMError("Cannot reach the model server")

    demo_system.orchestrator.llm = Unreachable()
    v = demo_system.orchestrator.ask("flank pain", env_t4, None)
    assert v.abstained and v.summary == NO_MODEL


def test_patient_claims_are_checked_against_the_record(demo_system, env_t4):
    claims = [
        {"id": "C1", "kind": "patient", "text": "Flank pain radiating to the groin."},
        {"id": "C2", "kind": "patient", "text": "Allergic to penicillin."},
    ]
    v = verify(demo_system, env_t4, "x", claims, patient=DEMO_PATIENT)
    shown = {c.claim.id: c.shown for c in v.claims}
    assert shown == {"C1": True, "C2": False}
    assert v.claims[1].status == "unsupported" and "patient record" in v.claims[1].detail

    none = verify(demo_system, env_t4, "x", claims[:1], patient=None)
    assert not none.claims[0].shown and none.claims[0].detail == "No patient record was provided"


def test_patient_document_reads_as_plain_lines():
    doc = patient_document({"allergies": [], "vitals": {"heart_rate": 96}, "crew_id": "C3"})
    assert doc.splitlines() == ["allergies: none", "vitals heart rate: 96", "crew id: C3"]


def test_demo_flank_summary_loses_the_evacuation_sentence(demo_system, env_t4):
    v = demo_system.orchestrator.ask(
        "Sharp right flank pain that moves toward my groin", env_t4, DEMO_PATIENT
    )
    assert v.summary.startswith("Colicky flank pain") and "evacuation" not in v.summary.lower()
    assert "SUMMARY-TRIMMED" in rule_ids(v)
    patient = next(c for c in v.claims if c.claim.kind == "patient")
    assert patient.shown


def test_summary_is_generated_after_the_claims_it_restates():
    from spacedoc.agent.prompts import SYSTEM
    from spacedoc.answer.schema import draft_json_schema

    schema = draft_json_schema()
    order = list(schema["properties"])
    assert order.index("summary") > order.index("claims")
    assert order.index("summary") > order.index("actions")
    assert schema["required"] == order  # required-first decoders keep the declared order
    assert "must not add any fact" in SYSTEM
