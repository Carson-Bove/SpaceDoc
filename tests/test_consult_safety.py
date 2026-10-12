"""Consult safety nets, replaying a real practice consult: acute radiation syndrome that the
model never considered, and critical vital signs that did not stop routine questions."""

import json

from spacedoc.config import Settings
from spacedoc.consult.engine import Answer, ExamResult
from spacedoc.consult.render import record_markdown, render_turn
from spacedoc.llm.client import FakeLLM
from spacedoc.system import build_system
from tests.conftest import exposure

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
    "questions": [{"topic": "recent travel", "why": "infection source"}],
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


def test_exposure_card_comes_after_the_first_message(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C1", "C3", env_t4)
    first = engine.turn(c, "flank pain in waves")
    assert first.exposure_asked and [i.id for i in first.screen][0] == "EXP-EVA"
    assert first.reply.message.endswith(engine.screen.lead)
    second = engine.turn(c, "no fever", exposure(engine))
    assert not second.screen and engine.screen.lead not in second.reply.message
    # The model is told what SpaceDoc asked on its behalf.
    assert "SpaceDoc's last message also asked: One more thing" in second.notes


def test_unanswered_exposure_card_is_shown_once_more(demo_system, env_t4):
    engine = engine_with(demo_system, {**HEMORRHAGIC, "urgent": {"flag": False, "reason": ""}})
    c = engine.start("C1", "C3", env_t4)
    engine.turn(c, "feeling unwell")
    again = engine.turn(c, "since this morning")
    assert again.screen and "Please also answer the exposure check" in again.reply.message
    third = engine.turn(c, "still the same")
    assert not third.screen
    assert "Exposure check: not answered." in engine.case_summary(c)


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
    assert turn.reply.message.startswith("Pain that comes in waves")
    assert render_turn(turn).startswith("SpaceDoc: Pain that comes in waves")
    record = record_markdown(c)
    assert "**Patient record used:** C1 · 46 F · 64 kg" in record
    assert "_(not checked)_" in record


def test_conversation_reply_answers_how_to_questions(demo_system, env_t4):
    engine = demo_system.consult
    c = engine.start("C3", "C1", env_t4)
    engine.turn(c, "flank pain in waves")
    turn = engine.turn(c, "how do I use this urine dipstick")
    assert "no reviewed guide" in turn.reply.message


def test_consult_prompt_is_spaceflight_aware_and_plain():
    from spacedoc.consult.prompts import SYSTEM

    assert "Never ask about travel" in SYSTEM and "radiation exposure" in SYSTEM
    assert "Never give step-by-step equipment instructions" in SYSTEM
    assert 'never say "I\'m concerned"' in SYSTEM  # no claimed feelings (NASA-STD-3001 Vol 2)
    assert "only for a threat to life, limb or eyesight" in SYSTEM
    assert "ask first how, where and with what it happened" in SYSTEM


def test_consult_model_can_differ_from_the_main_model(tmp_path):
    s = Settings(
        db_path=tmp_path / "kb.db", audit_path=tmp_path / "a.jsonl", consult_model="qwen3:4b"
    )
    system = build_system(s)
    assert system.consult.model_name == "qwen3:4b"
    assert system.consult.llm.chat_model == "qwen3:4b"
    assert system.orchestrator.llm.chat_model == "qwen3:8b"
    assert system.orchestrator.verifier.checker.llm.keep_alive == "1m"


def test_spacedocs_own_wording_is_never_screened(demo_system, env_t4):
    """Replays a practice turn where SpaceDoc's own exposure question (which mentioned smoke)
    raised a fire alarm. Only the user's words are checked."""
    engine = engine_with(demo_system)
    c = engine.start("C2", "C4", env_t4)
    first = engine.turn(c, "Crew member sliced the webbing between two fingers on a panel edge")
    assert first.exposure_asked and not first.red_flags
    answers = [Answer(question="numbness or tingling in the fingers", answer="Yes")]
    text = "Spacewalk 3 days ago for maintenance, no alarms or smells, nothing else"
    turn = engine.turn(c, text, answers)
    assert not turn.paused and turn.red_flags == []
    # A spacewalk plus numbness and tingling does call for decompression sickness.
    assert "MNM-DCS" in c.must_not_miss
    assert "MNM-TOXIC" not in c.must_not_miss


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
