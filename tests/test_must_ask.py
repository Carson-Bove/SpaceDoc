"""Must-ask questions: replays a practice consult about a cut hand, where SpaceDoc never asked
how or where it happened, and so never learned about possible contamination."""

import json

from spacedoc.config import REPO_ROOT
from spacedoc.consult.cli import answer_prompt, quick_answers
from spacedoc.consult.render import record_markdown, render_turn
from spacedoc.consult.safety import MustAsk
from spacedoc.llm.client import FakeLLM

CUT = "Crew member cut their hand and it is bleeding a little"


def says(message="Keep pressure on it.", **kw):
    reply = {
        "urgent": {"flag": False, "reason": ""},
        "message": message,
        "questions": [],
        "exam_requests": [],
        "working_ddx": [{"condition": "Laceration", "likelihood": "high", "why": "cut"}],
        "ready_to_assess": False,
    }
    reply.update(kw)
    return json.dumps(reply)


def engine_saying(demo_system, *replies):
    engine = demo_system.consult
    engine.llm = FakeLLM([*replies] if len(replies) > 1 else lambda m, s: replies[0])
    return engine


def pending_ids(engine, consult):
    return [item.id for _, item in engine.pending_must_ask(consult)]


def test_a_cut_starts_the_injury_list():
    lists = MustAsk.load(REPO_ROOT / "data")
    assert [x.id for x in lists.match(CUT)] == ["MA-INJURY"]
    assert lists.match("No cuts or injuries, just a headache")[0].id == "MA-NEURO"
    assert "DRAFT, UNREVIEWED" in (REPO_ROOT / "data" / "rules" / "must_ask.yaml").read_text()


def test_spacedoc_asks_how_it_happened_when_the_model_does_not(demo_system, env_t4):
    engine = engine_saying(demo_system, says(ready_to_assess=True))
    c = engine.start("C2", "C4", env_t4)
    turn = engine.turn(c, CUT)
    assert c.must_ask == ["MA-INJURY"]
    assert turn.must_ask_added == ["MA-INJ-HOW"]
    # The model said it was ready, so the added question says why it comes first.
    assert "Before the assessment: How and where did it happen" in turn.reply.message
    # It gets its own answer card, and the exposure check still comes last.
    added = turn.reply.questions[-1]
    assert added.topic == "how and where it happened" and "must-ask" in added.why
    assert turn.reply.message.endswith(engine.screen.lead)
    # Questions are still owed, so SpaceDoc does not offer to assess yet.
    assert not turn.reply.ready_to_assess and engine.should_assess(c) is None
    assert "SpaceDoc added a must-ask question" in render_turn(turn)
    assert "MA-INJ-HOW" in record_markdown(c)
    logged = demo_system.orchestrator.audit.get(turn.audit_id)
    assert logged["payload"]["must_ask_added"] == ["MA-INJ-HOW"]


def test_the_model_is_told_what_is_still_owed(demo_system, env_t4):
    engine = engine_saying(demo_system, says())
    c = engine.start("C2", "C4", env_t4)
    engine.turn(c, CUT)
    sent = engine.llm.calls[0][-1]["content"]
    assert "Must ask (injury): How and where did it happen" in sent


def test_nothing_is_added_when_the_model_asks_one(demo_system, env_t4):
    engine = engine_saying(demo_system, says("Press on it firmly. How did it happen?"))
    c = engine.start("C2", "C4", env_t4)
    turn = engine.turn(c, CUT)
    assert turn.must_ask_added == []
    assert "MA-INJ-HOW" not in pending_ids(engine, c)


def test_no_quick_replies_when_spacedoc_added_a_question(demo_system, env_t4):
    yes_no = [{"topic": "still bleeding", "why": "x", "answer_type": "yes_no"}]
    engine = engine_saying(demo_system, says("Is it still bleeding?", questions=yes_no))
    c = engine.start("C2", "C4", env_t4)
    turn = engine.turn(c, CUT)
    assert turn.appended  # the must-ask question and the exposure check
    # "n" could answer the wrong question, so it is sent as typed.
    assert quick_answers("n", turn) is None and answer_prompt(turn) == "Answer"
    turn.appended, turn.reply.questions = [], turn.reply.questions[:1]
    assert quick_answers("n", turn)[0].answer == "No" and "y/n/?" in answer_prompt(turn)


def test_what_the_user_already_said_counts(demo_system, env_t4):
    engine = engine_saying(demo_system, says())
    c = engine.start("C2", "C4", env_t4)
    turn = engine.turn(
        c, "Cut my hand on a panel edge while I was working in the lab 10 minutes ago"
    )
    # How, what and when are answered; contamination is next.
    assert turn.must_ask_added == ["MA-INJ-CONTAM"]
    assert pending_ids(engine, c) == ["MA-INJ-TETANUS"]


def test_tetanus_is_skipped_when_the_record_has_it(demo_system, env_t4):
    engine = engine_saying(demo_system, says())
    with_record = engine.start("C2", "C3", env_t4)  # C3: booster 2023
    engine.turn(with_record, CUT)
    assert "MA-INJ-TETANUS" not in pending_ids(engine, with_record)
    without = engine.start("C2", "C4", env_t4)  # C4: not in the record
    engine.turn(without, CUT)
    assert "MA-INJ-TETANUS" in pending_ids(engine, without)


def test_assessment_waits_until_the_list_is_done(demo_system, env_t4):
    engine = engine_saying(demo_system, says(ready_to_assess=True))
    c = engine.start("C2", "C3", env_t4)
    engine.turn(c, CUT)
    answers = [
        "On a rack edge while I was stowing gear, about 10 minutes ago",
        "No contamination, it has been washed",
    ]
    for text in answers:
        turn = engine.turn(c, text)
    assert pending_ids(engine, c) == []
    assert turn.reply.ready_to_assess
    assert engine.should_assess(c) == "SpaceDoc has enough information to assess."


def test_a_bare_reading_after_a_device_request_is_read_as_that_measurement(demo_system, env_t4):
    oximeter = {"what": "Check oxygen saturation", "equipment": ["pulse_oximeter"]}
    engine = engine_saying(
        demo_system, says("Please check their oxygen.", exam_requests=[oximeter]), says()
    )
    c = engine.start("C1", "C3", env_t4)
    engine.turn(c, "feeling tired and a bit dizzy")
    turn = engine.turn(c, "88%")
    assert turn.paused and turn.red_flags[0].rule_id == "VS-SPO2"
