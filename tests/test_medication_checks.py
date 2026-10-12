"""Medication actions: doses from the calculator, allergies, and plain explanations.

The first test replays the actions from a real practice consult (patient C1, 64 kg), where
every one of them was blocked with a message nobody could act on.
"""

import json

from spacedoc.answer.schema import Action, DraftAnswer, draft_json_schema
from spacedoc.config import REPO_ROOT
from spacedoc.consult.roster import load_roster
from spacedoc.llm.client import LLMError
from spacedoc.tools.formulary import Formulary
from spacedoc.verify import rules

C1 = load_roster(REPO_ROOT / "data")["C1"].record | {"crew_id": "C1"}


def ask_with_actions(system, env, actions, patient=C1, claims=()):
    draft = DraftAnswer(summary="x", uncertainty="moderate", actions=actions, claims=list(claims))
    system.orchestrator.llm.responder = lambda m, s: json.dumps(draft.model_dump())
    return system.orchestrator.ask("vomiting and bloody stools", env, patient)


def action(aid, text, item=None, kind="medication"):
    return {"id": aid, "text": text, "kind": kind, "item": item, "risk_tier": "R2"}


def test_replayed_consult_actions_get_checked_doses(demo_system, env_t4):
    v = ask_with_actions(
        demo_system,
        env_t4,
        [
            action("A1", "Calculate maintenance fluids for weight 64 kg", "normal saline"),
            action("A2", "Calculate dose of ondansetron for weight 64 kg", "ondansetron"),
            action("A3", "Calculate dose of acetaminophen for weight 64 kg", "acetaminophen"),
            action("A4", "Calculate dose of ciprofloxacin for weight 64 kg", "ciprofloxacin"),
        ],
    )
    a = {x.action.id: x for x in v.actions}
    # "64 kg" is the recorded weight, so it no longer blocks anything.
    assert not any("64" in r for x in v.actions for r in x.reasons)
    assert a["A1"].calc_text == "Maintenance fluids 104 mL/h"  # 4-2-1 rule for 64 kg
    assert a["A2"].calc_text.startswith("Ondansetron 4 mg oral")  # 0.1 mg/kg, 4 mg tablets
    assert a["A3"].calc_text.startswith("Acetaminophen 500 mg oral")  # 960 mg, 500 mg tablets
    assert all(a[i].status == "requires_confirmation" for i in ("A1", "A2", "A3"))
    # Ciprofloxacin: used up, and the formulary has no dosing data for it.
    assert a["A4"].status == "blocked"
    assert any("used up" in r for r in a["A4"].reasons)
    assert any(r.startswith("No checked dose") for r in a["A4"].reasons)
    assert v.patient_summary == "C1 · 46 F · 64 kg · allergies: none · medications: none"


def test_model_dose_is_replaced_by_the_calculator(demo_system, env_t4):
    v = ask_with_actions(
        demo_system, env_t4, [action("A1", "Ondansetron 8 mg orally every 8 hours", "ondansetron")]
    )
    [a] = v.actions
    assert a.status == "requires_confirmation"
    assert a.display_text == "Ondansetron orally every 8 hours"  # the interval stays
    assert a.calc_text.startswith("Ondansetron 4 mg")
    assert any("removed it" in r for r in a.reasons)


def test_dose_without_a_calculator_is_not_ready(demo_system, env_t4):
    v = ask_with_actions(
        demo_system,
        env_t4,
        [action("A1", "Trimethoprim-sulfamethoxazole 2 tablets twice daily", "tmp-smx")],
    )
    [a] = v.actions
    assert a.status == "blocked"
    assert a.display_text == "Trimethoprim-sulfamethoxazole twice daily"
    assert any("no dosing data" in r for r in a.reasons)


def test_missing_weight_means_no_checked_dose(demo_system, env_t4):
    no_weight = {k: v for k, v in C1.items() if k != "weight_kg"}
    v = ask_with_actions(
        demo_system, env_t4, [action("A1", "Acetaminophen for pain", "acetaminophen")], no_weight
    )
    [a] = v.actions
    assert a.status == "blocked" and a.calc_text is None
    calc_error = next(f for f in v.findings if f.rule_id == "CALC-ERROR")
    assert "weight is not in the record" in calc_error.message


def test_allergy_by_drug_class():
    formulary = Formulary.load("example-transit", REPO_ROOT / "data")
    c4 = load_roster(REPO_ROOT / "data")["C4"].record  # sulfonamide antibiotics
    bactrim = Action(id="A1", text="TMP-SMX", kind="medication", item="bactrim", risk_tier="R2")
    [f] = rules.check_allergies(bactrim, formulary, c4)
    assert f.rule_id == "ALLERGY" and f.severity == "block"
    assert "sulfonamide antibiotics" in f.message
    tylenol = Action(
        id="A2", text="Acetaminophen", kind="medication", item="acetaminophen", risk_tier="R2"
    )
    assert rules.check_allergies(tylenol, formulary, c4) == []
    assert rules.check_allergies(bactrim, formulary, {"allergies": []}) == []


def test_missing_checker_is_explained_and_the_answer_still_says_what_to_do(demo_system, env_t4):
    class Missing:
        name = "minicheck"

        def check(self, claim, passage):
            raise LLMError(
                "Model server error 404 for bespoke-minicheck:7b: "
                "model 'bespoke-minicheck:7b' not found"
            )

    demo_system.orchestrator.verifier.checker = Missing()
    claims = [{"id": "C1", "kind": "sourced", "citations": ["S1"], "text": "Stones hurt."}]
    v = ask_with_actions(demo_system, env_t4, [], claims=claims)
    assert v.abstained and "source checker could not run" in v.abstain_reason
    assert v.uncertainty == "high"
    err = next(f for f in v.findings if f.rule_id == "CHECK-ERROR")
    assert "(bespoke-minicheck:7b) is not installed" in err.message
    assert "spacedoc models pull" in err.message
    assert v.next_steps[0].startswith("SpaceDoc could not give a full, checked answer")
    assert any("ground medical team" in s for s in v.next_steps)


def test_unsourced_claim_detail_is_plain(demo_system, env_t4):
    claims = [{"id": "C1", "kind": "sourced", "citations": [], "text": "Stones hurt."}]
    v = ask_with_actions(demo_system, env_t4, [], claims=claims)
    assert "did not name a source" in v.claims[0].detail


def test_every_field_is_required_so_none_is_skipped():
    schema = draft_json_schema()
    assert schema["$defs"]["Claim"]["required"] == ["id", "text", "kind", "citations"]
    assert "item" in schema["$defs"]["Action"]["required"]
