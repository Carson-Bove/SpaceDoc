"""Consult mode: identification, question turns, red flags, timing, assessment, the CLI."""

import json

import pytest
from typer.testing import CliRunner

from spacedoc.cli import app
from spacedoc.config import REPO_ROOT
from spacedoc.consult.cli import quick_answers
from spacedoc.consult.engine import UNLISTED, _timing
from spacedoc.consult.redflags import RedFlags
from spacedoc.consult.render import record_markdown, render_turn, timing_line
from spacedoc.consult.roster import load_roster
from spacedoc.llm.client import ChatResult, FakeLLM, LLMError

DATA = REPO_ROOT / "data"
FLANK = "Sharp right flank pain that comes in waves"


def reply(**kw):
    base = {"working_ddx": [], "questions": [], "ready_to_assess": False}
    base.update(kw)
    return json.dumps(base)


def start(system, env, patient="C3", **kw):
    return system.consult.start("C1", patient, env, **kw)


# ---- roster and red flags ------------------------------------------------------------


def test_roster_is_synthetic_and_labelled():
    roster = load_roster(DATA)
    assert set(roster) == {"C1", "C2", "C3", "C4"}
    assert roster["C1"].is_clinical and not roster["C3"].is_clinical
    assert roster["C1"].label() == "C1 · Commander · CMO"
    assert "SYNTHETIC" in (DATA / "crew" / "roster.yaml").read_text()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("He has chest pain and feels sick", {"RF-CHEST-PAIN"}),
        ("No chest pain, no fever", set()),
        ("Denies chest pain but has trouble breathing", {"RF-BREATHING"}),
        ("I can't breathe", {"RF-BREATHING"}),
        ("She doesn't have any trouble breathing", set()),
        ("Feeling disoriented and having trouble focusing on close up objects", set()),
        ("He became suddenly disoriented an hour ago", {"RF-CONFUSION-ACUTE"}),
        ("Slurred speech and facial droop", {"RF-STROKE"}),
    ],
)
def test_red_flags_respect_negation(text, expected):
    hits = RedFlags.load(DATA).screen(text, "14 min")
    assert {h.rule_id for h in hits} == expected


def test_red_flag_steps_name_the_delay():
    hit = RedFlags.load(DATA).screen("crushing chest pain", "14 min")[0]
    assert any("one-way delay 14 min" in s for s in hit.steps)
    assert "DRAFT, UNREVIEWED" in (DATA / "rules" / "red_flags.yaml").read_text()


# ---- identification ----------------------------------------------------------------------


def test_identification_shapes_the_prompt(demo_system, env_t4):
    relay = start(demo_system, env_t4)
    system = relay.messages[0]["content"]
    assert "Ask C3 whether" in system and "Only C1 types" in system
    assert "Clinical terms are fine" in system  # C1 is the CMO

    own = demo_system.consult.start("C4", "self", env_t4)
    assert own.patient_is_user and "Address them directly" in own.messages[0]["content"]
    assert "plain language" in own.messages[0]["content"]  # C4 is not clinical

    nobody = start(demo_system, env_t4, patient=UNLISTED)
    assert nobody.patient is None and "not on the crew roster" in nobody.messages[0]["content"]

    with pytest.raises(ValueError, match="Unknown crew ID"):
        demo_system.consult.start("C9", "self", env_t4)


def test_practice_session_is_recorded(demo_system, env_t4):
    c = start(demo_system, env_t4, practice=True, scenario_id="SO-0104")
    entry = demo_system.orchestrator.audit.get(c.consult_id)
    assert entry["event"] == "consult_start"
    assert entry["payload"]["practice"] is True and entry["payload"]["scenario_id"] == "SO-0104"
    real = start(demo_system, env_t4, practice=False, scenario_id="SO-0104")
    assert real.scenario_id is None  # scenarios belong to practice sessions only


# ---- question turns -----------------------------------------------------------------------


def test_question_turn_checks_exam_equipment(demo_system, env_t4):
    c = start(demo_system, env_t4)
    turn = demo_system.consult.turn(c, FLANK)
    assert len(turn.reply.questions) == 2 and turn.reply.working_ddx
    ct = next(x for x in turn.exam_checks if "CT" in x.request.text)
    thermo = next(x for x in turn.exam_checks if "temperature" in x.request.text)
    assert ct.missing == ["ct_scanner"] and not ct.ok and thermo.ok
    assert "NOT ABOARD: ct_scanner" in render_turn(turn)
    assert [m["role"] for m in c.messages] == ["system", "user", "assistant"]
    logged = demo_system.orchestrator.audit.get(turn.audit_id)
    assert logged["event"] == "consult_turn" and logged["payload"]["reply"]["questions"]
    assert turn.thinking == ""  # thinking notes are kept only with deep log


def test_each_turn_extends_the_previous_prompt(demo_system, env_t4):
    """Ollama can reuse its cache only if each prompt starts with the previous one."""
    llm = FakeLLM([reply(questions=[{"text": "Fever?", "why": "x"}]), reply()])
    demo_system.consult.llm = llm
    c = start(demo_system, env_t4)
    demo_system.consult.turn(c, FLANK)
    demo_system.consult.turn(c, "No fever")
    first, second = llm.calls
    assert second[: len(first)] == first
    assert second[len(first)]["role"] == "assistant"
    assert llm.params[0].think is False


def test_questions_are_capped_at_two(demo_system, env_t4):
    qs = [{"text": f"Q{i}?", "why": "x"} for i in range(4)]
    demo_system.consult.llm = FakeLLM([reply(questions=qs)])
    turn = demo_system.consult.turn(start(demo_system, env_t4), FLANK)
    assert [q.text for q in turn.reply.questions] == ["Q0?", "Q1?"]


def test_bad_replies_and_failures_leave_the_consult_unchanged(demo_system, env_t4):
    engine = demo_system.consult
    c = start(demo_system, env_t4)
    engine.llm = FakeLLM(["not json", "still not json"])
    turn = engine.turn(c, FLANK)
    assert turn.reply is None and "valid reply" in turn.error
    assert c.turns == [] and len(c.messages) == 1  # the user can simply retry

    class Down(FakeLLM):
        def chat(self, messages, schema=None, params=None):
            raise LLMError("Cannot reach the model server")

    engine.llm = Down()
    turn = engine.turn(c, FLANK)
    assert "Cannot reach" in turn.error and c.turns == []


def test_red_flag_pauses_before_the_model(demo_system, env_t4):
    engine = demo_system.consult
    engine.llm = FakeLLM([reply(questions=[{"text": "When did it start?", "why": "x"}])])
    c = start(demo_system, env_t4)
    turn = engine.turn(c, "Crushing chest pain since this morning")
    assert turn.paused and not engine.llm.calls
    resumed = engine.resume(c)
    assert resumed is turn and turn.red_flags_dismissed and turn.reply.questions
    assert "vital-sign alerts during the consult: Chest pain" in engine.case_summary(c)
    assert "continued by the user" in record_markdown(c)


def test_assessment_point(demo_system, env_t4):
    engine = demo_system.consult
    c = start(demo_system, env_t4)
    engine.turn(c, FLANK)
    assert engine.should_assess(c) is None
    engine.turn(c, "Yes fever, no blood")
    assert engine.should_assess(c) == "SpaceDoc has enough information to assess."

    engine.llm = FakeLLM(lambda m, s: reply(questions=[{"text": "More?", "why": "x"}]))
    engine.max_rounds = 2
    c2 = start(demo_system, env_t4)
    engine.turn(c2, FLANK)
    engine.turn(c2, "answer")
    assert "2 rounds" in engine.should_assess(c2)


# ---- timing and deep log -------------------------------------------------------------------


def test_deep_log_turns_on_thinking_and_keeps_the_notes(demo_system, env_t4):
    engine = demo_system.consult
    c = start(demo_system, env_t4, deep_log=True)
    turn = engine.turn(c, FLANK)
    assert engine.llm.params[-1].think is True
    assert "SCRIPTED DEMO NOTES" in turn.thinking
    assert "Thinking notes (deep log, unverified)" in record_markdown(c)
    assert "SCRIPTED DEMO NOTES" not in c.messages[-1]["content"]  # notes never go back in


def test_time_without_deep_log_is_estimated():
    result = ChatResult(
        text="x" * 100,
        thinking="t" * 300,
        seconds=10.0,
        load_s=0.0,
        prompt_s=1.0,
        gen_s=8.0,
        completion_tokens=400,
    )
    timing = _timing([result], elapsed=10.0, deep_log=True)
    assert timing.without_deep_log_s == pytest.approx(4.0)  # 3/4 of the writing was thinking
    line = timing_line(timing)
    assert "10.0 s" in line and "about 4.0 s without deep log (estimated)" in line
    assert _timing([result], elapsed=10.0, deep_log=False).without_deep_log_s is None


def test_estimate_is_unavailable_without_server_durations():
    timing = _timing([ChatResult(text="{}", seconds=1.0, thinking="t")], 1.0, deep_log=True)
    assert timing.without_deep_log_s is None
    assert "not available" in timing_line(timing)


# ---- assessment -----------------------------------------------------------------------------


def test_assessment_uses_the_whole_consult(demo_system, env_t4):
    engine = demo_system.consult
    c = start(demo_system, env_t4)
    engine.turn(c, FLANK)
    engine.turn(c, "1. Any fever or chills? Yes. 2. Any blood in the urine? No.")
    summary = engine.case_summary(c)
    assert f'in C1\'s words: "{FLANK}"' in summary
    assert "SpaceDoc asked: Any fever or chills? / Any blood in the urine?" in summary
    assert "not checked; re-evaluate" in summary

    v = engine.assess(c)
    assert v.audit_id and c.assessments == [v]
    ask_entry = demo_system.orchestrator.audit.get(v.audit_id)
    assert ask_entry["payload"]["question"] == summary
    # The scripted claim "pain started 6 hours ago" was never said in this consult.
    patient = next(x for x in v.claims if x.claim.kind == "patient")
    assert not patient.shown
    log = [
        e for e in demo_system.orchestrator.audit.entries() if e["event"] == "consult_assessment"
    ]
    assert log[-1]["payload"]["ask_audit_id"] == v.audit_id


# ---- terminal ---------------------------------------------------------------------------------


def test_quick_replies_become_button_answers(demo_system, env_t4):
    turn = demo_system.consult.turn(start(demo_system, env_t4), FLANK)
    answers = quick_answers("y n", turn)
    assert [(a.question, a.answer) for a in answers] == [
        ("Any fever or chills?", "Yes"),
        ("Any blood in the urine?", "No"),
    ]
    assert quick_answers("y", turn) is None  # two questions, one answer: left as typed
    assert quick_answers("No fever", turn) is None


def test_cli_consult_runs_end_to_end(tmp_path):
    config = tmp_path / "spacedoc.toml"
    config.write_text(f'db_path = "{tmp_path}/kb.db"\naudit_path = "{tmp_path}/audit/a.jsonl"\n')
    result = CliRunner().invoke(
        app,
        ["consult", "--demo", "--config", str(config), "--tier", "T4"],
        input="1\n3\np\nSO-0001\n" + FLANK + "\ny n\n/quit\n",
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "PRACTICE consult" in out and "C1 · Commander · CMO" in out
    assert "NOT ABOARD: ct_scanner" in out
    assert "SpaceDoc has enough information to assess." in out
    assert "Full answer saved in the audit log" in out
    records = list((tmp_path / "audit" / "consults").glob("*.md"))
    assert len(records) == 1 and "## Assessment 1" in records[0].read_text()
