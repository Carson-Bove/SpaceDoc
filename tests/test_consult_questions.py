"""Answer cards carry the question they answer, repeats are dropped, and a trailing "no" is a
no. These come from a practice consult (audit-000066) where two questions shared one topic,
"Yes" answers lost their question, and the head-injury question was asked twice."""

from __future__ import annotations

import json
from pathlib import Path

from spacedoc.config import REPO_ROOT
from spacedoc.consult.engine import Answer, compose
from spacedoc.consult.questions import clean, question_sentences, similar
from spacedoc.consult.redflags import RedFlags
from spacedoc.consult.schema import TurnReply
from spacedoc.llm.client import FakeLLM
from tests.conftest import exposure

DATA = Path(REPO_ROOT) / "data"


def q(ask="", topic="t", answer_type="free_text"):
    return {"ask": ask, "topic": topic, "why": "x", "answer_type": answer_type}


def reply(message="", questions=(), **kw):
    base = {"message": message, "questions": list(questions), "working_ddx": []}
    base.update(kw)
    return json.dumps(base)


# ---- what the model is sent ---------------------------------------------------------------


def test_each_answer_is_paired_with_its_question():
    text = compose(
        "",
        [
            Answer(question="Have you hit your head recently?", answer="Yes"),
            Answer(question="Did it come on suddenly or gradually?", answer="gradually"),
        ],
        [],
    )
    assert text == (
        'Answer to "Have you hit your head recently?": Yes\n'
        'Answer to "Did it come on suddenly or gradually?": gradually'
    )


# ---- cleaning a reply ------------------------------------------------------------------------


def test_same_question_twice_in_one_reply_is_dropped():
    r = TurnReply.model_validate_json(
        reply(
            "Any weakness or numbness? Have you hit your head?",
            [
                q("Any weakness or numbness?", "headache or neurological symptoms"),
                q("Have you hit your head?", "headache or neurological symptoms"),
            ],
        )
    )
    clean(r, [])
    assert [x.ask for x in r.questions] == ["Any weakness or numbness?"]


def test_already_answered_question_is_dropped_with_its_sentence():
    r = TurnReply.model_validate_json(
        reply(
            "Thanks. Have you hit your head recently? How is your vision?",
            [q("Have you hit your head recently?", "head injury"), q("How is your vision?", "v")],
        )
    )
    dropped = clean(r, ["Has the patient hit their head recently?"])
    assert dropped == ["Have you hit your head recently?"]
    assert [x.ask for x in r.questions] == ["How is your vision?"]
    assert r.message == "Thanks. How is your vision?"


def test_question_missing_from_the_message_is_added_to_it():
    r = TurnReply.model_validate_json(
        reply(
            "Tell me how it started.",
            [q("Did you hit your head before it started?", "head strike")],
        )
    )
    clean(r, [])
    assert r.message == "Tell me how it started.\n\nDid you hit your head before it started?"


def test_question_without_ask_shows_its_topic():
    r = TurnReply.model_validate_json(reply("Any fever?", [q("", "fever or chills")]))
    clean(r, [])
    assert r.questions[0].ask == "Fever or chills"
    assert r.message == "Any fever?"  # a topic is a label, not added to the message


def test_similar_questions():
    assert similar("Has the patient hit their head recently?", "Have you hit your head?")
    assert similar(
        "Any weakness or numbness on one side, trouble speaking?",
        "Are you having any weakness, numbness, or difficulty speaking?",
    )
    assert not similar("Did it come on suddenly?", "Have you hit your head?")
    assert not similar("Any fever?", "Any nausea?")


def test_statements_are_not_questions():
    assert question_sentences("Let me check for any recent head injury. Any nausea?") == [
        "Any nausea?"
    ]


# ---- in a consult --------------------------------------------------------------------------


def test_consult_does_not_ask_an_answered_question_again(demo_system, env_t4):
    head = q("Have you hit your head recently?", "head injury", "yes_no")
    demo_system.consult.llm = FakeLLM(
        [
            reply("Did it start suddenly? Have you hit your head recently?", [head]),
            reply("Thanks. Have you hit your head recently? Any nausea?", [head, q("Any nausea?")]),
        ]
    )
    c = demo_system.consult.start("C1", "self", env_t4)
    first = demo_system.consult.turn(c, "I have a headache")
    asked = first.reply.questions[0].ask
    answers = [Answer(question=asked, answer="No"), *exposure(demo_system.consult)]
    second = demo_system.consult.turn(c, "", answers)
    assert second.repeats_dropped == ["Have you hit your head recently?"]
    assert [x.ask for x in second.reply.questions][0] == "Any nausea?"
    assert "hit your head" not in second.reply.message
    # The model saw which question the "No" answered.
    sent = demo_system.consult.llm.calls[-1][-1]["content"]
    assert 'Answer to "Have you hit your head recently?": No' in sent


def test_a_statement_does_not_count_as_asking_a_must_ask_question(demo_system, env_t4):
    demo_system.consult.llm = FakeLLM(
        [reply("Let me check for any recent head injury. Did it start suddenly?", [])]
    )
    c = demo_system.consult.start("C1", "self", env_t4)
    demo_system.consult.turn(c, "I have a headache")
    pending = [i.id for _, i in demo_system.consult.pending_must_ask(c)]
    assert "MA-NE-HEAD" in pending


# ---- red flags -------------------------------------------------------------------------------


def test_a_no_after_the_sign_is_a_no():
    rf = RedFlags.load(DATA)
    for text in [
        "chest pain: no",
        "Chest pain? No.",
        "trouble breathing no",
        "weakness on one side: No",
        "smoke or fire: no",
        "chest pain? not really",
        "Chest pain? No, but my arm hurts",
    ]:
        assert rf.screen(text) == [], text
    for text in ["chest pain, no fever", "chest pain no fever", "chest pain: yes"]:
        assert rf.screen(text), text
