"""Phase B: the run plan, the simple twin, the crewmember and a whole run with a stand-in."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from medsim_eval.models import Scenario
from medsim_eval.run.adapters import ScriptedAssistant
from medsim_eval.run.adapters.spacedoc import SpaceDocAssistant, render_assessment
from medsim_eval.run.crewmember import (
    FactCrewmember,
    Persona,
    RuleCrewmember,
    RuleExtractor,
    match_kit,
)
from medsim_eval.run.llm import FakeLLM
from medsim_eval.run.plan import plan_runs
from medsim_eval.run.runner import RunConfig, run_batch
from medsim_eval.run.twin import SimpleTwin
from medsim_eval.simtime import parse_offset
from medsim_eval.validate import DEFAULT_LIBRARY, load_library

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LIB, _ = load_library(DEFAULT_LIBRARY)
RAW = json.loads((EXAMPLES / "MSE-0001.scenario.json").read_text())


def scenario(change=None) -> Scenario:
    raw = json.loads(json.dumps(RAW))
    if change:
        change(raw)
    return Scenario.model_validate(raw)


def twin(course="best", change=None) -> SimpleTwin:
    sc = scenario(change)
    spec = next(r for r in plan_runs(sc, LIB) if r.course == course)
    return SimpleTwin(sc, spec, LIB)


def test_plan_covers_every_environment_where_the_condition_occurs():
    runs = plan_runs(scenario(), LIB)
    assert len(runs) == 12
    assert {r.env for r in runs} == {"T1", "T2", "T3", "T4", "T5"}
    assert [r.course for r in runs].count("cliff") == 2
    assert len({r.seed for r in runs}) == 12  # every run has its own seed
    assert plan_runs(scenario(), LIB) == runs  # and the plan is reproducible


def test_plan_for_a_lunar_only_condition():
    def lunar(s):
        s["patients"][0]["condition"] = "dust-exposure-lunar-surface-eva"

    runs = plan_runs(scenario(lunar), LIB)
    assert [(r.env, r.course) for r in runs] == [
        ("T3", "best"), ("T3", "worst"), ("T3", "cliff"), ("T3", "cliff"),
    ]  # fmt: skip


def test_untreated_patient_worsens_and_perforates():
    tw = twin()
    tw.advance_to(parse_offset("T+12h"))
    assert tw.observe()["vitals"]["temp_c"] == 38.2  # the untreated keyframe applies
    tw.advance_to(parse_offset("T+1d12h"))
    assert tw.onsets == {"X1": parse_offset("T+36h")}
    facts = tw.observe()
    assert any("rigidity" in f["text"] for f in facts["exam_findings"])
    assert tw.outcome()["course_reached"] == "untreated_best"


def test_timely_antibiotics_prevent_the_complication():
    tw = twin("worst")
    tw.advance_to(parse_offset("T+2h"))
    tw.give("ertapenem-1gm", "ertapenem 1 g IV")
    tw.advance_to(parse_offset("T+2d"))
    assert tw.onsets == {}
    assert tw.observe()["vitals"]["temp_c"] == 37.4  # the treated keyframe at T+48h
    out = tw.outcome()
    assert (
        out["course_reached"] == "treated_worst" and out["first_time_critical_treatment"] == "T+2h"
    )
    assert out["resources_used"] == {"ertapenem-1gm": 1}


def test_action_triggered_complication_follows_its_roll():
    for roll, expected in [(True, {"X2": parse_offset("T+1h30m")}), (False, {})]:
        tw = twin()
        tw.rolls["X2"] = roll
        tw.advance_to(parse_offset("T+1h"))
        tw.give("amoxicillin-500-mg-capsule", "amoxicillin 500 mg")
        tw.advance_to(parse_offset("T+3h"))
        assert {k: v for k, v in tw.onsets.items() if k == "X2"} == expected


def test_items_not_aboard_are_not_given():
    def no_kit(s):
        s["environments"] = ["T3"]

    tw = twin(change=no_kit)
    tw.give("ertapenem-1gm", "ertapenem")  # not carried on the lunar lander
    tw.give(None, "Monitor for fever")  # not a kit item at all
    assert tw.given == [] and [e["kind"] for e in tw.events] == ["not_aboard", "not_aboard"]


def test_rule_extractor_reads_directions_not_mentions():
    kit = twin().kit_items()
    acts = RuleExtractor().extract(
        "Start ertapenem 1 g IV now. Do not give ceftriaxone. Recheck his vital signs in 4 hours.",
        kit,
    )
    assert [t.kit_id for t in acts.treatments] == ["ertapenem-1gm"]
    assert acts.measure_vitals and acts.recheck_minutes == 240
    # A message that only asks questions directs nothing (a real run "gave" a drug here).
    asks = RuleExtractor().extract("Where is the pain? Let's check the exposure factors.", kit)
    assert asks.treatments == [] and not asks.examine and not asks.measure_vitals


def test_one_kit_item_per_drug_named():
    hits = match_kit("Give acetaminophen 1000 mg by mouth for pain", twin().kit_items())
    assert len(hits) == 1 and "acetaminophen" in hits[0].name.lower()


def test_free_fluid_on_a_scan_is_not_iv_fluid():
    kit = twin().kit_items()
    assert match_kit("Perform abdominal ultrasound to assess for free fluid", kit) == []
    assert [k.id for k in match_kit("Start IV fluids now", kit)] == ["iv-fluid-1l-1000ml"]


def asks_about(*topics):
    """A stand-in for the model: says yes when the topic is one of these."""

    def respond(messages, schema):
        topic = messages[-1]["content"].split("TOPIC: ")[-1]
        return {"asks": "yes" if topic in topics else "no"}

    return FakeLLM(respond)


def test_fact_crewmember_uses_the_clerks_words_and_exact_numbers():
    sc = scenario()
    tw = twin()
    crew = FactCrewmember(Persona(sc, LIB.crew["C14"], LIB.crew["C10"]), asks_about("vomiting"))
    assert crew.opening() == sc.speaker.opening
    msg = "Has he been sick? Any radiation alarm or ammonia smell? Please take his temperature."
    reply = crew.reply(msg, tw.observe(), RuleExtractor().extract(msg, tw.kit_items()))
    assert "Vomiting: Once, this morning." in reply
    assert "heart rate 92/min" in reply and "temperature 37.6" in reply  # as the twin has them
    assert reply.endswith("Nothing else that I've noticed.")
    assert "ammonia" not in reply and "radiation" not in reply  # nothing echoed or invented
    assert "right lower quadrant" not in reply  # the T+6h symptom hasn't happened yet


def test_fact_crewmember_reports_findings_only_when_asked_to_examine():
    sc = scenario()
    tw = twin()
    crew = FactCrewmember(Persona(sc, LIB.crew["C14"], LIB.crew["C10"]), asks_about())
    finding = "Mild tenderness around the umbilicus; abdomen soft, no guarding or rebound"
    msg = "Press gently on his belly. Is it tender?"
    crew.llm = asks_about(finding)
    assert finding in crew.reply(msg, tw.observe(), RuleExtractor().extract(msg, tw.kit_items()))
    crew.llm = asks_about()
    assert crew.reply("How old is he?", tw.observe(), RuleExtractor().extract("", [])) == (
        "Nothing else that I've noticed."
    )


def test_follow_up_report_says_what_changed_and_what_was_done():
    sc = scenario()
    tw = twin()
    crew = FactCrewmember(Persona(sc, LIB.crew["C14"], LIB.crew["C10"]), asks_about())
    before = tw.observe()
    tw.advance_to(parse_offset("T+6h"))
    text = crew.update(tw.observe(), before, ["ertapenem 1gm at T+12m"])
    assert text.startswith("Update, 6 hours after my first message.")
    assert "Pain migrates to the right lower quadrant" in text and "rebound and guarding" in text
    assert "Done since we last spoke: ertapenem 1gm at T+12m." in text


def test_rule_crewmember_answers_from_the_facts():
    sc = scenario()
    crew = RuleCrewmember(Persona(sc, LIB.crew["C14"], LIB.crew["C10"]))
    tw = twin()
    acts = RuleExtractor().extract("What is his temperature and heart rate?", tw.kit_items())
    assert "temperature 37.6" in crew.reply("What is his temperature?", tw.observe(), acts)


def test_a_whole_run_with_a_scripted_assistant(tmp_path):
    script = [
        "When did it start, and what are his temperature and heart rate?",
        {
            "text": "This is likely appendicitis. Start ertapenem 1 g IV now. Recheck in 30 minutes.",
            "final": True,
        },
    ]
    batch = run_batch(
        [scenario()], LIB, ScriptedAssistant(script), lambda p, s: RuleCrewmember(p),
        RuleExtractor(), tmp_path, RunConfig(), only=2, progress=lambda *_: None,
    )  # fmt: skip
    runs = json.loads((batch / "batch.json").read_text())["runs"]
    assert [r["course_reached"] for r in runs] == ["treated_best", "treated_best"]
    assert all(r["complications"] == {} for r in runs)
    folder = batch / "MSE-0001" / "r01-T1-best"
    run = json.loads((folder / "run.json").read_text())
    assert run["outcome"]["treatments"][0]["kit_id"] == "ertapenem-1gm"
    events = [json.loads(e) for e in (folder / "events.jsonl").read_text().splitlines()]
    crew = [e for e in events if e["who"] == "crew"]
    assert "temperature 37.6" in crew[1]["text"]
    # Follow-ups go to the scenario's own time points, not the 30-minute re-check.
    assert [e["t"] for e in crew[2:]] == ["T+6h", "T+2d"]
    assert "Done since we last spoke: ertapenem 1gm at T+3m" in crew[2]["text"]


def test_assistant_listed_actions_are_used_instead_of_the_text(tmp_path):
    class Listing(ScriptedAssistant):
        def send(self, text):
            r = super().send(text)
            # The text names amoxicillin, but only as something its checks blocked.
            r.directed, r.notes = ["Ertapenem 1 g IV now"], ["cards answered"]
            return r

    script = [{"text": "Give amoxicillin 500 mg now (blocked).", "final": True}]
    batch = run_batch(
        [scenario()], LIB, Listing(script), lambda p, s: RuleCrewmember(p),
        RuleExtractor(), tmp_path, RunConfig(max_followups=0), only=1, progress=lambda *_: None,
    )  # fmt: skip
    folder = batch / "MSE-0001" / "r01-T1-best"
    run = json.loads((folder / "run.json").read_text())
    assert [x["kit_id"] for x in run["outcome"]["treatments"]] == ["ertapenem-1gm"]
    assert "harness: cards answered" in (folder / "transcript.md").read_text()


def test_spacedoc_overlay_gives_spacedoc_the_scenario_patient(tmp_path):
    cfg = tmp_path / "spacedoc.toml"
    (tmp_path / "data" / "crew").mkdir(parents=True)
    (tmp_path / "data" / "rules").mkdir()
    cfg.write_text(
        'db_path = "spacedoc.db"\nchat_model = "qwen3:8b"\nsampling = { temperature = 0.6 }\n'
    )
    a = SpaceDocAssistant(config=cfg)
    out = a._overlay(scenario(), LIB, tmp_path / "run")
    text = out.read_text()
    assert f'db_path = "{tmp_path / "spacedoc.db"}"' in text and "temperature = 0.6" in text
    roster = json.loads((tmp_path / "run" / "data" / "crew" / "roster.yaml").read_text())["crew"]
    by_id = {c["crew_id"]: c for c in roster}
    assert by_id["C10"]["record"]["allergies"] == ["penicillin (rash as a child)"]
    assert by_id["C14"]["medical_role"] == "cmo"
    # SpaceDoc gets the kit for each environment, with usual adult doses marked unvalidated.
    iss = json.loads((tmp_path / "run" / "data" / "formulary" / "medsim-T1.yaml").read_text())
    by_id = {i["id"]: i for i in iss["items"]}
    assert len(by_id) == 84 and by_id["ertapenem-1gm"]["dosing"]["max_mg"] == 1000
    assert "ertapenem" in by_id["ertapenem-1gm"]["aliases"]
    assert by_id["amoxicillin-500-mg-capsule"]["allergy_classes"] == ["penicillin", "penicillins"]
    assert all(i["validation_status"] == "unvalidated" for i in iss["items"])
    lander = json.loads((tmp_path / "run" / "data" / "formulary" / "medsim-T3.yaml").read_text())
    assert "ertapenem-1gm" not in {i["id"] for i in lander["items"]}


def test_render_assessment_sets_blocked_actions_apart():
    text = render_assessment({
        "summary": "Likely appendicitis.", "next_steps": ["Start antibiotics."],
        "differential": [{"condition": "Appendicitis", "likelihood": "high"}],
        "actions": [
            {"action": {"text": "Ertapenem 1 g IV"}, "status": "ok", "display_text": None},
            {"action": {"text": "Ondansetron"}, "status": "blocked", "reasons": ["not aboard"]},
        ],
        "claims": [], "uncertainty": "moderate", "abstained": False,
    })  # fmt: skip
    assert "Actions:\n- Ertapenem 1 g IV" in text
    assert "Blocked by SpaceDoc's checks (not to be done):\n- Ondansetron (not aboard)" in text


class FakeSpaceDoc(SpaceDocAssistant):
    """SpaceDoc's API, canned: an exposure card, then an urgent card, then a normal turn."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.turns = iter([
            {"reply": {"message": "Where is the pain?", "questions": [], "exam_requests": []},
             "screen": [{"id": "EXP-EVA", "question": "Any EVA?", "label": "EVA"},
                        {"id": "EXP-RAD", "question": "Any radiation alert?", "label": "radiation"}]},
            {"paused": True, "red_flags": [{"message": "Rigid abdomen", "steps": ["Call ground"]}]},
            {"reply": {"message": "How is he now?", "questions": [], "exam_requests": []}},
        ])  # fmt: skip

    def _post(self, path, body=None):
        self.calls.append((path.rsplit("/", 1)[-1], body or {}))
        kind = self.calls[-1][0]
        data = (
            next(self.turns)
            if kind == "turn"
            else {
                "summary": "Emergency.",
                "actions": [
                    {"action": {"text": "Ertapenem 1 g IV"}, "status": "requires_confirmation"},
                    {"action": {"text": "Morphine"}, "status": "blocked", "reasons": ["x"]},
                ],
            }
        )

        class R:
            status_code = 200

            def json(self):
                return data

            def raise_for_status(self):
                pass

        return R()


def test_spacedoc_cards_and_urgent_flow():
    a = FakeSpaceDoc()
    a.consult_id, a.exposure = "c1", {"EXP-EVA": "Yes"}
    first = a.send("He has belly pain.")
    assert first.text == "Where is the pain?" and "exposure check card" in first.notes[0]
    second = a.send("Around the belly button.")
    # The exposure check went back through the cards, not as typed text.
    answers = a.calls[1][1]["answers"]
    assert [(x["screen_id"], x["answer"]) for x in answers] == [
        ("EXP-EVA", "Yes"),
        ("EXP-RAD", "No"),
    ]
    assert second.final and second.text.startswith("URGENT: Rigid abdomen")
    assert second.directed == ["Ertapenem 1 g IV"]  # the blocked action is not carried out
    third = a.send("Update.")
    # One assessment for the urgent card, then the card is dismissed and the consult goes on.
    assert [c[0] for c in a.calls] == ["turn", "turn", "assess", "resume", "turn"]
    assert third.text == "How is he now?" and not third.final


@pytest.mark.skipif(shutil.which("spacedoc") is None, reason="SpaceDoc is not installed")
def test_spacedoc_demo_end_to_end(tmp_path):
    batch = run_batch(
        [scenario()], LIB, SpaceDocAssistant(demo=True), lambda p, s: RuleCrewmember(p),
        RuleExtractor(), tmp_path, RunConfig(max_followups=1), only=1, progress=lambda *_: None,
    )  # fmt: skip
    run = json.loads((batch / "MSE-0001" / "r01-T1-best" / "run.json").read_text())
    assert run["errors"] == 0 and run["turns"] >= 2 and run["assistant"]["demo"] is True


def test_scorer_checks_evidence_deadlines_and_applicability(tmp_path):
    from medsim_eval.models import ScenarioRubric
    from medsim_eval.score import Scorer, score_markdown

    script = [
        "What are his temperature and heart rate?",
        {"text": "Leading diagnosis: appendicitis. Start ertapenem 1 g IV now.", "final": True},
    ]
    batch = run_batch(
        [scenario()], LIB, ScriptedAssistant(script), lambda p, s: RuleCrewmember(p),
        RuleExtractor(), tmp_path, RunConfig(max_followups=0), only=1, progress=lambda *_: None,
    )  # fmt: skip
    run_dir = batch / "MSE-0001" / "r01-T1-best"
    rubric = ScenarioRubric.model_validate(
        json.loads((EXAMPLES / "MSE-0001.rubric.json").read_text())
    )
    lines = [json.loads(x) for x in (run_dir / "events.jsonl").read_text().splitlines()]
    final = next(e["n"] for e in lines if e["who"] == "assistant" and e.get("final"))
    crew_line = next(e["n"] for e in lines if e["who"] == "crew")

    def respond(messages, schema):
        q = messages[-1]["content"].split("QUESTION\n")[-1]
        if "rating" in schema["properties"]:
            return {"closest_lines": [final], "reason": "ok", "rating": 4}
        if "IMM diagnosis" in q or "antibiotic regimen" in q:
            return {"closest_lines": [final], "reason": "said so", "verdict": "yes"}
        if "temperature and heart rate" in q:
            return {
                "closest_lines": [crew_line],
                "reason": "asked",
                "verdict": "yes",
            }  # not its own line
        if "operate" in q:
            return "not json"
        return {"closest_lines": [], "reason": "not seen", "verdict": "no"}

    s = Scorer(FakeLLM(respond)).score(
        run_dir, scenario(), rubric, LIB.base_rubrics[rubric.base], LIB
    )
    items = {r["id"]: r for r in s["items"]}
    assert items["SDX"]["verdict"] == "met" and s["outcome"]["time_to_leading_diagnosis"] == "T+3m"
    assert items["SET"]["verdict"] == "not_met"
    assert items["I7"]["verdict"] == "met" and items["I7"]["deadline"] == "T+8h"
    assert items["I3"]["verdict"] == "cannot_tell"  # a yes that cites only the crew's line
    assert items["N1"]["verdict"] == "cannot_tell" and "N1" in s["review"]  # unreadable answer
    assert items["I15"]["verdict"] == "na" and items["SCR:X1"]["verdict"] == "na"  # no complication
    assert items["G1"]["verdict"] == "clear" and s["ratings"]["D1"] == 4
    # SDX 6 + I7 8 met, of every applicable expected weight; nothing negative.
    c = s["checklist"]
    assert (
        c["expected_met"] == 14
        and c["errors"] == 0
        and c["score"] == round(14 / c["expected_total"], 3)
    )
    assert "| I7 |" in score_markdown(s)
