import json

from spacedoc.answer.schema import DraftAnswer
from spacedoc.demo import DEMO_PATIENT
from spacedoc.llm.client import FakeLLM

QUESTION = "Sharp right flank pain radiating to the groin since this morning"


def by_id(items, attr):
    return {getattr(i, attr).id: i for i in items}


def test_demo_flank_end_to_end(demo_system, env_t4):
    v = demo_system.orchestrator.ask(QUESTION, env_t4, DEMO_PATIENT)
    claims = by_id(v.claims, "claim")
    assert claims["C1"].status == "supported" and claims["C1"].shown
    assert claims["C3"].status == "removed"  # invented "95%" statistic
    assert claims["C4"].status == "unsupported" and not claims["C4"].shown  # not in the source
    assert claims["C6"].status == "supported"  # patient-record claim, numbers in record
    assert claims["C7"].status == "reasoning"

    actions = by_id(v.actions, "action")
    assert actions["A1"].status == "requires_confirmation"
    assert actions["A2"].status == "blocked"  # expired tamsulosin
    # The model wrote 650 mg; SpaceDoc linked the calculator (15 mg/kg x 78 kg, capped at
    # 1000 mg) and removed the model's number.
    assert actions["A3"].status == "requires_confirmation"
    assert actions["A3"].calc_text.startswith("Acetaminophen 1000 mg")
    assert actions["A3"].display_text == "Acetaminophen oral for pain"
    assert actions["A4"].status == "blocked"  # evacuation impossible in T4
    assert actions["A5"].status == "ok"

    rule_ids = {f.rule_id for f in v.findings}
    assert {
        "INJECTION",
        "NUM-UNTRACED",
        "DOSE-REPLACED",
        "FORM-EXPIRED",
        "ENV-EVACUATE",
    } <= rule_ids
    assert v.next_steps and v.patient_summary.startswith("C3 · 34 M · 78 kg")
    assert all(p.source_id != "demo-injection" for p in v.passages)
    assert [p.cid for p in v.passages] == [f"S{i + 1}" for i in range(len(v.passages))]
    assert not v.abstained
    assert v.audit_id and demo_system.orchestrator.audit.verify() == (True, None)


def test_calculator_weight_comes_from_record(demo_system, env_t4):
    patient = {**DEMO_PATIENT, "weight_kg": 50}
    v = demo_system.orchestrator.ask(QUESTION, env_t4, patient)
    # 15 mg/kg x 50 kg = 750 mg, rounded down to one 500 mg tablet. The model's own "650 mg"
    # is removed and the calculated dose shown instead.
    [a3] = [a for a in v.actions if a.action.id == "A3"]
    assert a3.calc_text.startswith("Acetaminophen 500 mg")
    assert a3.status == "requires_confirmation" and "650" not in a3.display_text


def test_out_of_scope_question_abstains(demo_system, env_t4):
    v = demo_system.orchestrator.ask("Chemotherapy regimen for leukemia?", env_t4, None)
    assert v.abstained and v.missing_info


def test_invalid_json_retries_then_abstains(demo_system, env_t4):
    orch = demo_system.orchestrator
    orch.llm = FakeLLM(["not json", "still not json"])
    v = orch.ask("anything about kidney stones", env_t4, None)
    assert v.abstained
    assert v.timings["parse_failures"] == 2


def test_invalid_json_then_valid_recovers(demo_system, env_t4):
    orch = demo_system.orchestrator
    good = DraftAnswer(
        summary="ok",
        uncertainty="low",
        claims=[
            {
                "id": "C1",
                "kind": "sourced",
                "citations": ["S1"],
                "text": "Kidney stones typically cause colicky flank pain that may radiate to the groin.",
            }
        ],
    )
    orch.llm = FakeLLM(["oops", json.dumps(good.model_dump())])
    v = orch.ask("colicky flank pain kidney stones", env_t4, None)
    assert not v.abstained and v.timings["parse_failures"] == 1


def test_low_support_forces_abstention(demo_system, env_t4):
    orch = demo_system.orchestrator
    draft = DraftAnswer(
        summary="x",
        uncertainty="low",
        claims=[
            {
                "id": "C1",
                "kind": "sourced",
                "citations": ["S1"],
                "text": "Astronauts grow gills in transit.",
            },
            {
                "id": "C2",
                "kind": "sourced",
                "citations": ["S9"],
                "text": "Moon cheese cures stones.",
            },
        ],
    )
    orch.llm = FakeLLM([json.dumps(draft.model_dump())])
    v = orch.ask("kidney stones", env_t4, None)
    assert v.abstained and "sourced claims" in v.abstain_reason
    assert "CITE-INVALID" in {f.rule_id for f in v.findings}


def test_self_consistency_flags_disagreement(demo_system, env_t4):
    orch = demo_system.orchestrator
    orch.consistency_samples = 3

    def draft(dx):
        return json.dumps(
            DraftAnswer(
                summary="x",
                uncertainty="low",
                differential=[{"condition": dx, "likelihood": "high"}],
            ).model_dump()
        )

    orch.llm = FakeLLM([draft("Nephrolithiasis"), draft("Appendicitis"), draft("Pyelonephritis")])
    v = orch.ask("kidney stones", env_t4, None)
    assert "CONSISTENCY-LOW" in {f.rule_id for f in v.findings}
    assert v.uncertainty == "high"
