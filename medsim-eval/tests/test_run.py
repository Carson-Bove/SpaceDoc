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
    LLMCrewmember,
    LLMExtractor,
    Persona,
    RuleCrewmember,
    RuleExtractor,
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
    assert tw.given[0].kit_id is None and tw.events[0]["kind"] == "not_aboard"


def test_rule_extractor_reads_directions_not_mentions():
    tw = twin()
    acts = RuleExtractor().extract(
        "Start ertapenem 1 g IV now. Do not give ceftriaxone. Recheck his vital signs in 4 hours.",
        tw.kit_items(),
    )
    assert [t.kit_id for t in acts.treatments] == ["ertapenem-1gm"]
    assert acts.measure_vitals and acts.recheck_minutes == 240


def test_llm_extractor_maps_kit_ids_and_falls_back():
    kit = twin().kit_items()
    llm = FakeLLM(
        lambda m, s: {
            "treatments": [
                {"kit_id": "made-up", "text": "x"},
                {"kit_id": "ertapenem-1gm", "text": "ertapenem"},
            ],
            "measure_vitals": False,
            "examine": True,
            "recheck_minutes": None,
        }
    )
    acts = LLMExtractor(llm).extract("...", kit)
    assert [t.kit_id for t in acts.treatments] == [None, "ertapenem-1gm"] and acts.examine
    broken = LLMExtractor(FakeLLM(lambda m, s: "not json")).extract("Give ertapenem now.", kit)
    assert [t.kit_id for t in broken.treatments] == ["ertapenem-1gm"]


def test_llm_crewmember_sees_only_current_facts():
    sc = scenario()
    seen = []
    llm = FakeLLM(lambda m, s: seen.append(m) or "It hurts around my belly button.")
    tw = twin()
    crew = LLMCrewmember(Persona(sc, LIB.crew["C14"], LIB.crew["C10"]), llm, "Low Earth orbit", 1)
    assert crew.opening() == sc.speaker.opening
    crew.reply("Where is the pain?", tw.observe(), RuleExtractor().extract("", []))
    system = seen[0][0]["content"]
    assert "Rachel Abernathy" in system and "penicillin" in system
    assert "right lower quadrant" not in system  # the T+6h symptom hasn't happened yet
    assert "about where it started: Around his belly button" in system


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
            "text": "This is likely appendicitis. Start ertapenem 1 g IV now. Recheck in 4 hours.",
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
    run = json.loads((batch / "MSE-0001" / "r01-T1-best" / "run.json").read_text())
    assert run["outcome"]["treatments"][0]["kit_id"] == "ertapenem-1gm"
    events = (batch / "MSE-0001" / "r01-T1-best" / "events.jsonl").read_text().splitlines()
    assert json.loads(events[1])["who"] == "crew" and "temperature 37.6" in events[4]
    assert "Recheck" in (batch / "MSE-0001" / "r01-T1-best" / "transcript.md").read_text()


def test_spacedoc_overlay_gives_spacedoc_the_scenario_patient(tmp_path):
    cfg = tmp_path / "spacedoc.toml"
    (tmp_path / "data" / "crew").mkdir(parents=True)
    (tmp_path / "data" / "formulary").mkdir()
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
    assert (tmp_path / "run" / "data" / "formulary").is_symlink()


def test_render_assessment():
    text = render_assessment({
        "summary": "Likely appendicitis.", "next_steps": ["Start antibiotics."],
        "differential": [{"condition": "Appendicitis", "likelihood": "high"}],
        "actions": [{"action": {"text": "Ertapenem 1 g IV"}, "status": "ok", "display_text": None}],
        "claims": [], "uncertainty": "moderate", "abstained": False,
    })  # fmt: skip
    assert "Likely appendicitis." in text and "- Ertapenem 1 g IV" in text


@pytest.mark.skipif(shutil.which("spacedoc") is None, reason="SpaceDoc is not installed")
def test_spacedoc_demo_end_to_end(tmp_path):
    batch = run_batch(
        [scenario()], LIB, SpaceDocAssistant(demo=True), lambda p, s: RuleCrewmember(p),
        RuleExtractor(), tmp_path, RunConfig(max_followups=1), only=1, progress=lambda *_: None,
    )  # fmt: skip
    run = json.loads((batch / "MSE-0001" / "r01-T1-best" / "run.json").read_text())
    assert run["errors"] == 0 and run["turns"] >= 2 and run["assistant"]["demo"] is True
