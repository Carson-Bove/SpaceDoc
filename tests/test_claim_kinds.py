"""Regressions from a practice consult (hand laceration, patient C4): the model filed the
crew's own report as sourced facts, which failed against the NASA standards and made SpaceDoc
abstain; a reasoning statement quoting the reported "1/2 inch" was hidden; and an action said
"ibuprofen 200 mg" while the calculator said 400 mg."""

import json

from spacedoc.answer.schema import DraftAnswer
from spacedoc.config import REPO_ROOT
from spacedoc.consult.roster import load_roster

REPORT = (
    'Crew Member sliced webbing between left hand pointer and middle finger, cut is 1/2" deep. '
    "Applied antiseptic and bandage, being held under pressure now. Patient cannot move either "
    "finger properly."
)
C4 = {
    "crew_id": "C4",
    **load_roster(REPO_ROOT / "data")["C4"].record,
    "reported_in_consult": [REPORT],
}


def ask(system, env, claims=(), actions=()):
    draft = DraftAnswer(
        summary="x", uncertainty="moderate", claims=list(claims), actions=list(actions)
    )
    system.orchestrator.llm.responder = lambda m, s: json.dumps(draft.model_dump())
    return system.orchestrator.ask("hand laceration", env, C4)


def test_reported_facts_filed_as_sourced_are_shown_as_patient_statements(demo_system, env_t4):
    v = ask(
        demo_system,
        env_t4,
        claims=[{"id": "C1", "kind": "sourced", "citations": ["S1"], "text": REPORT}],
    )
    [c] = v.claims
    assert c.shown and c.status == "supported" and c.claim.kind == "patient"
    assert "filed it as sourced" in c.detail
    assert not v.abstained  # it no longer counts against the sources
    assert v.patient_summary.startswith("C4 · 38 F · 59 kg")


def test_sourced_claims_with_invented_numbers_stay_removed(demo_system, env_t4):
    v = ask(
        demo_system,
        env_t4,
        claims=[
            {"id": "C1", "kind": "sourced", "citations": ["S1"], "text": "95% of such cuts heal."}
        ],
    )
    [c] = v.claims
    assert c.status == "removed" and not c.shown
    assert "NUM-UNTRACED" in {f.rule_id for f in v.findings}


def test_reasoning_may_quote_the_patients_numbers(demo_system, env_t4):
    quoted = 'The 1/2" deep cut with loss of finger movement suggests a tendon injury.'
    invented = "About 30 percent of such cuts damage a tendon."
    v = ask(
        demo_system,
        env_t4,
        claims=[
            {"id": "C1", "kind": "reasoning", "citations": [], "text": quoted},
            {"id": "C2", "kind": "reasoning", "citations": [], "text": invented},
        ],
    )
    shown = {c.claim.id: c.shown for c in v.claims}
    assert shown == {"C1": True, "C2": False}


def test_a_dose_that_differs_from_the_calculator_is_removed_even_if_it_is_a_tablet_size(
    demo_system, env_t4
):
    action = {
        "id": "A1",
        "text": "Administer ibuprofen 200 mg orally for pain and inflammation.",
        "kind": "medication",
        "item": "ibuprofen",
        "risk_tier": "R2",
    }
    v = ask(demo_system, env_t4, actions=[action])
    [a] = v.actions
    assert a.calc_text.startswith("Ibuprofen 400 mg oral")  # 10 mg/kg x 59 kg, capped
    assert a.display_text == "Administer ibuprofen orally for pain and inflammation."
    assert any("removed it" in r for r in a.reasons)
