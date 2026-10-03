"""Consult safety nets, replaying a real practice consult: acute radiation syndrome that the
model never considered, and critical vital signs that did not stop routine questions."""

import json

from spacedoc.config import Settings
from spacedoc.consult.engine import Answer, ExamResult
from spacedoc.consult.render import record_markdown, render_turn
from spacedoc.llm.client import FakeLLM
from spacedoc.system import build_system

ARS_TURN_1 = (
    "Crewmember had sudden onset nausea and vomiting as well as headaches and dizziness 34 hours "
    "ago. Crewmember then felt fatigued until 12 hours ago, at which point crew member began "
    "feeling better. 4 hours ago crew member began violently vomiting and passing bloody stools, "
    "as well as showing skin discoloration and hair loss."
)
ARS_TURN_2 = (
    "1. No contact and no other sick crew\n"
    "Exam (Use the thermometer to check for fever.): 102 degrees F\n"
    "Exam (Use the blood pressure cuff to check for hypotension.): 70/50mm hg\n"
    "Exam (Use the pulse oximeter to check for hypoxia.): 85%"
)

# What the model actually answered in that consult: no radiation on the list.
HEMORRHAGIC = {
    "urgent": {"flag": True, "reason": ""},
    "message": "That sounds serious.",
    "working_ddx": [
        {"condition": "Hemorrhagic fever", "likelihood": "high", "why": "bleeding, fever"},
        {"condition": "Toxic shock syndrome", "likelihood": "moderate", "why": "skin changes"},
    ],
    "questions": [{"text": "Any recent travel?", "why": "infection source"}],
    "exam_requests": [],
    "ready_to_assess": False,
}


def engine_with(demo_system, reply=HEMORRHAGIC):
    engine = demo_system.consult
    engine.llm = FakeLLM(lambda m, s: json.dumps(reply))
    return engine


def test_radiation_syndrome_is_put_back_on_the_list(demo_system, env_t4):
    engine = engine_with(demo_system)
    c = engine.start("C3", "C1", env_t4)
    turn = engine.turn(c, ARS_TURN_1)
    conditions = [d.condition for d in turn.reply.working_ddx]
    assert "Acute radiation syndrome" in conditions
    ars = next(d for d in turn.reply.working_ddx if d.condition == "Acute radiation syndrome")
    assert ars.likelihood == "must not miss"
    assert "Acute radiation syndrome" in turn.must_not_miss_added
    # The model was told, in the message (the system prompt stays the same every turn).
    sent = engine.llm.calls[0][-1]["content"]
    assert "[SpaceDoc notes, not from the user]" in sent
    assert "Must not miss: Acute radiation syndrome (ask: Has there been a radiation alert" in sent
    assert "added back by SpaceDoc's must-not-miss list" in render_turn(turn)
    summary = engine.case_summary(c)
    assert "address each one: Acute radiation syndrome" in summary


def test_urgent_flag_without_a_reason_gets_one(demo_system, env_t4):
    engine = engine_with(demo_system)
    turn = engine.turn(engine.start("C3", "C1", env_t4), ARS_TURN_1)
    assert turn.reply.urgent.reason.startswith("The model flagged this as urgent")


def test_critical_vital_signs_pause_the_consult(demo_system, env_t4):
    engine = engine_with(demo_system)
    c = engine.start("C3", "C1", env_t4)
    engine.turn(c, ARS_TURN_1)
    calls = len(engine.llm.calls)
    turn = engine.turn(c, ARS_TURN_2)
    assert turn.paused and len(engine.llm.calls) == calls  # the model was not asked first
    alerts = {h.rule_id: h.message for h in turn.red_flags}
    assert alerts["VS-SYSTOLIC-BP"] == "Systolic blood pressure 70 mmHg (below 90)"
    assert alerts["VS-SPO2"] == "Oxygen saturation 85% (below 90)"
    assert any("oxygen" in s for s in turn.red_flags[0].steps)
    engine.resume(c)
    assert (
        "Vital-sign or red-flag alert: Oxygen saturation 85%" in engine.llm.calls[-1][-1]["content"]
    )


def test_reversed_blood_pressure_is_flagged_for_recheck(demo_system, env_t4):
    engine = engine_with(demo_system)
    c = engine.start("C3", "C1", env_t4)
    turn = engine.turn(c, "Exam (blood pressure cuff): 40/60 mmhg")
    [bp] = [h for h in turn.red_flags if h.rule_id == "VS-SYSTOLIC-BP"]
    assert "recheck the reading" in bp.message


def test_exposure_check_comes_once_after_the_first_message(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C1", "C3", env_t4)
    first = engine.turn(c, "flank pain in waves")
    assert [i.id for i in first.screen][:2] == ["EXP-EVA", "EXP-RAD"]
    assert "Exposure check" in render_turn(first)
    second = engine.turn(c, "no fever")
    assert second.screen == []


def test_assessment_starts_with_the_urgent_steps(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C3", "C1", env_t4)
    engine.turn(c, "flank pain in waves")
    paused = engine.turn(c, "BP 80/50 mmHg and SpO2 86%")
    assert paused.paused
    v = engine.assess(c)
    assert v.next_steps[0].startswith("Urgent signs were raised in this consult")
    assert any("give oxygen" in s for s in v.next_steps)


def test_reply_record_and_patient_record_are_shown(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C3", "C1", env_t4)
    turn = engine.turn(c, "flank pain in waves")
    assert turn.reply.message.startswith("Thanks")
    assert render_turn(turn).startswith("SpaceDoc: Thanks")
    record = record_markdown(c)
    assert "**Patient record used:** C1 · 46 F · 64 kg" in record
    assert "_(not checked)_" in record


def test_conversation_reply_answers_how_to_questions(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C3", "C1", env_t4)
    engine.turn(c, "flank pain in waves")
    turn = engine.turn(c, "how do I use this urine dipstick")
    assert "no reviewed guide" in turn.reply.message


def test_consult_prompt_is_spaceflight_aware():
    from spacedoc.consult.prompts import SYSTEM

    assert "never ask about travel" in SYSTEM and "radiation exposure" in SYSTEM
    assert "set urgent" in SYSTEM and "Never give step-by-step instructions" in SYSTEM


def test_consult_model_can_differ_from_the_main_model(tmp_path):
    s = Settings(
        db_path=tmp_path / "kb.db", audit_path=tmp_path / "a.jsonl", consult_model="qwen3:4b"
    )
    system = build_system(s)
    assert system.consult.model_name == "qwen3:4b"
    assert system.consult.llm.chat_model == "qwen3:4b"
    assert system.orchestrator.llm.chat_model == "qwen3:8b"
    assert system.orchestrator.verifier.checker.llm.keep_alive == "1m"


def screen(item_id, answer, demo_system):
    item = next(i for i in demo_system.consult.screen.items if i.id == item_id)
    return Answer(kind="screen", question=item.question, answer=answer, screen_id=item_id)


def test_spacedocs_own_question_wording_is_never_screened(demo_system, env_t4):
    """Replays a practice turn where answering "No" to the atmosphere question (which mentions
    smoke) raised a fire alarm."""
    engine = engine_with(demo_system)
    c = engine.start("C2", "self", env_t4)
    engine.turn(c, "Deep cut on my hand from a panel edge")
    answers = [
        Answer(
            question="Can you tell me if there is any numbness, tingling, or pain in the fingers?",
            answer="Yes",
        ),
        screen("EXP-EVA", "Yes", demo_system),
        screen("EXP-RAD", "No", demo_system),
        screen("EXP-ATMOS", "No", demo_system),
        screen("EXP-PAYLOAD", "Yes", demo_system),
        screen("EXP-MEDS", "No", demo_system),
        screen("EXP-OTHERS", "No", demo_system),
    ]
    exams = [
        ExamResult(request="ultrasound", result="not trained on ultrasound"),
        ExamResult(
            request="stethoscope", result="since bandage on hand cannot get stethoscope to listen"
        ),
    ]
    text = (
        "pain near the cut, deep and radiating. not much numbness except for close to finger tips"
    )
    turn = engine.turn(c, text, answers, exams)
    assert not turn.paused and turn.red_flags == []
    assert "smoke" in turn.user_text and "smoke" not in turn.check_text
    # A spacewalk plus numbness and tingling does call for decompression sickness.
    assert "MNM-DCS" in c.must_not_miss
    assert "MNM-TOXIC" not in c.must_not_miss  # payload work alone is not enough


def test_a_yes_to_a_question_counts_as_the_users_words(demo_system, env_t4):
    engine = engine_with(demo_system)
    c = engine.start("C1", "C3", env_t4)
    engine.turn(c, "feeling unwell")
    no = engine.turn(c, "", [Answer(question="Any chest pain?", answer="No")])
    assert not no.paused
    yes = engine.turn(c, "", [Answer(question="Any chest pain?", answer="Yes")])
    assert yes.paused and yes.red_flags[0].rule_id == "RF-CHEST-PAIN"


def test_exam_results_are_still_read_for_vital_signs(demo_system, env_t4):
    engine = engine_with(demo_system)
    c = engine.start("C1", "C3", env_t4)
    engine.turn(c, "feeling unwell")
    exams = [ExamResult(request="Use the pulse oximeter to check for hypoxia.", result="85%")]
    turn = engine.turn(c, "", None, exams)
    assert turn.paused and turn.red_flags[0].rule_id == "VS-SPO2"
