"""A "No" never raises an alarm. Replays the practice consults where SpaceDoc's own question
about smoke, answered No, raised the fire card, and checks every other way a No reaches the
checks, the model and the assessment."""

import json

import pytest

from spacedoc.config import REPO_ROOT
from spacedoc.consult.cli import exposure_answers
from spacedoc.consult.engine import Answer, ExamResult
from spacedoc.consult.redflags import RedFlags
from spacedoc.llm.client import FakeLLM
from tests.conftest import exposure

RULES = RedFlags.load(REPO_ROOT / "data")


def says(**kw):
    reply = {
        "urgent": {"flag": False, "reason": ""},
        "message": "Thanks. Where is the pain?",
        "questions": [{"topic": "where the pain is", "why": "x", "answer_type": "free_text"}],
        "exam_requests": [],
        "working_ddx": [{"condition": "Not yet clear", "likelihood": "moderate", "why": "x"}],
        "ready_to_assess": False,
    }
    reply.update(kw)
    return json.dumps(reply)


def consult(demo_system, env_t4, reply=None):
    engine = demo_system.consult
    engine.llm = FakeLLM(lambda m, s: reply or says())
    c = engine.start("C1", "C3", env_t4)
    engine.turn(c, "Feeling unwell since this morning")
    return engine, c


def test_none_of_these_raises_nothing(demo_system, env_t4):
    engine, c = consult(demo_system, env_t4)
    turn = engine.turn(c, "", exposure(engine))
    assert not turn.paused and turn.red_flags == []
    assert c.must_not_miss == []
    assert c.exposure["EXP-ATMOS"] == "No"
    # The model reads each No spelled out, and is told to treat it as absent.
    sent = engine.llm.calls[-1][-1]["content"]
    assert "no cabin air alarm or unusual smell" in sent
    assert "treat each No as absent" in sent
    assert "smoke" not in sent.lower()
    # The assessment is not told about smoke at all.
    summary = engine.case_summary(c)
    assert "No to all 6 spaceflight exposures asked about" in summary
    assert "smoke" not in summary.lower() and "smell" not in summary.lower()


def test_a_yes_on_the_exposure_card_counts(demo_system, env_t4):
    engine, c = consult(demo_system, env_t4)
    turn = engine.turn(c, "I have a cough", exposure(engine, EXP_ATMOS="Yes"))
    assert not turn.paused  # a past alarm is history, not an emergency card
    assert "MNM-TOXIC" in c.must_not_miss  # cabin air plus cough
    assert "YES: cabin air alarm or unusual smell" in turn.exposure_text
    assert "Yes: cabin air alarm or unusual smell. No to the other 5" in engine.case_summary(c)
    assert "**Exposure check answers:**" in __import__(
        "spacedoc.consult.render", fromlist=["record_markdown"]
    ).record_markdown(c)


def test_not_sure_keeps_the_condition_open(demo_system, env_t4):
    engine, c = consult(demo_system, env_t4)
    engine.turn(c, "nausea since this morning", exposure(engine, EXP_RAD="Not sure"))
    assert "MNM-ARS" in c.must_not_miss  # possible radiation alert plus nausea


@pytest.mark.parametrize("answer, paused", [("No", False), ("Not sure", False), ("Yes", True)])
def test_question_card_buttons(demo_system, env_t4, answer, paused):
    engine, c = consult(demo_system, env_t4)
    card = Answer(question="smoke or fire in the module", answer=answer)
    turn = engine.turn(c, "", [card])
    assert turn.paused is paused
    assert ("smoke" in turn.check_text) is paused


def test_a_typed_card_answer_is_the_users_words(demo_system, env_t4):
    engine, c = consult(demo_system, env_t4)
    card = Answer(question="where it happened", answer="in the node, there was smoke")
    turn = engine.turn(c, "", [card])
    assert turn.paused and turn.red_flags[0].rule_id == "RF-ATMOSPHERE"


def test_an_exam_result_box_is_read_with_its_device(demo_system, env_t4):
    ox = {"what": "Check oxygen saturation", "equipment": ["pulse_oximeter"]}
    engine, c = consult(demo_system, env_t4, says(exam_requests=[ox]))
    turn = engine.turn(c, "", None, [ExamResult(request="Check oxygen saturation", result="88%")])
    assert turn.paused and turn.red_flags[0].rule_id == "VS-SPO2"
    fine = engine.turn(c, "", None, [ExamResult(request="Check oxygen saturation", result="97%")])
    assert not fine.paused


@pytest.mark.parametrize(
    "text",
    [
        "No alarms, smoke or fire",
        "No spacewalk, radiation alert, cabin alarm, smoke or smell, payloads, new meds or others sick",
        "There hasn't been any smoke or fire",
        "Haven't noticed any smoke, fumes or unusual smell",
        "Negative for smoke and fire",
        "no smoke or fire alarms but there was a funny smell",
        "No smoke/fire",
        "Denies fever, chills, chest pain",
        "No fever, cough or chest pain",
    ],
)
def test_typed_negatives_raise_nothing(text):
    assert RULES.screen(text) == []


@pytest.mark.parametrize(
    "text, rule",
    [
        ("We had a smoke alarm this morning", "RF-ATMOSPHERE"),
        ("no fire, but smoke in the node", "RF-ATMOSPHERE"),
        ("There was no fire. There was smoke in the node.", "RF-ATMOSPHERE"),
        ("Not that I know of, the CO2 alarm went off yesterday though", "RF-ATMOSPHERE"),
        ("No spacewalk, no radiation, the CO2 alarm went off", "RF-ATMOSPHERE"),
        # A "no" earlier in the sentence must not hide a symptom that is present.
        ("No fever, I have chest pain", "RF-CHEST-PAIN"),
        ("No fever, chest pain", "RF-CHEST-PAIN"),
        ("No fever and chest pain since this morning", "RF-CHEST-PAIN"),
        ("Denies fever, I have chest pain", "RF-CHEST-PAIN"),
        ("No nausea\nchest pain since 3 am", "RF-CHEST-PAIN"),
    ],
)
def test_typed_positives_still_raise_the_alarm(text, rule):
    assert rule in {h.rule_id for h in RULES.screen(text)}


def test_terminal_exposure_answers():
    from spacedoc.consult.safety import ExposureScreen

    items = ExposureScreen.load(REPO_ROOT / "data").items
    none = exposure_answers("none", items)
    assert [a.answer for a in none] == ["No"] * 6
    some = {a.screen_id: a.answer for a in exposure_answers("3 5?", items)}
    assert some["EXP-ATMOS"] == "Yes" and some["EXP-MEDS"] == "Not sure"
    assert some["EXP-EVA"] == "No"
    assert exposure_answers("9", items) is None and exposure_answers("smoke", items) is None
