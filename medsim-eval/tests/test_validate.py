"""The validator: the shipped library is clean, and broken files are caught with useful messages."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from medsim_eval.cli import app, schema_documents
from medsim_eval.validate import DEFAULT_LIBRARY, validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCENARIO = json.loads((EXAMPLES / "MSE-0001.scenario.json").read_text())
RUBRIC = json.loads((EXAMPLES / "MSE-0001.rubric.json").read_text())


def write_pair(folder: Path, scenario: dict, rubric: dict) -> Path:
    (folder / "MSE-0001.scenario.json").write_text(json.dumps(scenario))
    (folder / "MSE-0001.rubric.json").write_text(json.dumps(rubric))
    return folder


def messages(issues, level=None):
    return [i.message for i in issues if level is None or i.level == level]


def check(tmp_path, change=None, rubric_change=None):
    sc, rb = copy.deepcopy(SCENARIO), copy.deepcopy(RUBRIC)
    if change:
        change(sc)
    if rubric_change:
        rubric_change(rb)
    return validate([write_pair(tmp_path, sc, rb)])


def test_library_and_examples_are_clean():
    issues = validate([DEFAULT_LIBRARY, EXAMPLES])
    assert messages(issues, "error") == [] and messages(issues, "warning") == [], issues
    # The lunar lander has no ultrasound, so the ultrasound item is noted as not applicable there.
    assert messages(issues, "info") == [
        "rubric item I4: not applicable in T3 (nothing it requires is aboard)"
    ]


def test_committed_schemas_are_current():
    for name, doc in schema_documents().items():
        committed = json.loads((ROOT / "schemas" / name).read_text())
        assert committed == doc, f"schemas/{name} is stale: run `medsim schema`"


def p0(sc):
    return sc["patients"][0]


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda s: p0(s).update(crew_id="C99"), "'C99' is not in the crew roster"),
        (lambda s: p0(s).update(condition="dragon-pox"), "unknown condition 'dragon-pox'"),
        (lambda s: s.update(symptoms=["R99.99"]), "'R99.99' is not in the ICD-10-CM symptom list"),
        (lambda s: p0(s).update(crew_id="C09"), "C09 has had an appendectomy"),
        (
            lambda s: s["review"].update(status="approved"),
            "approved scenarios need at least one reviewer",
        ),
        (
            lambda s: s.update(rubric="missing.rubric.json"),
            "rubric file 'missing.rubric.json' not found",
        ),
        (
            lambda s: s["speaker"].update(crew_id="C10"),
            "C10 is a patient; set the speaker's role to patient",
        ),
        (
            lambda s: s["speaker"].update(role="patient"),
            "the speaker is the patient, so speaker.crew_id must be a patient",
        ),
        (
            lambda s: s["speaker"].update(input_quality=1),
            "input quality 1 means clear input",
        ),
        (lambda s: s["speaker"].update(input_problems=["mumbles"]), "unknown input problems"),
        (
            lambda s: p0(s)["chart"].update(nkda=True),
            "marked NKDA but lists drug allergies: ['penicillin']",
        ),
        (lambda s: s.update(environments=["T1", "T1"]), "environments are listed twice"),
        (lambda s: s.update(schema_version="0.1"), "this is a v0.1 scenario"),
    ],
)
def test_scenario_errors(tmp_path, change, expected):
    issues = check(tmp_path, change)
    assert any(expected in m for m in messages(issues, "error")), messages(issues)


def test_sex_specific_condition(tmp_path):
    issues = check(tmp_path, lambda s: p0(s).update(condition="prostatitis-acute", crew_id="C02"))
    assert any("only occurs in M crewmembers" in m for m in messages(issues, "error"))


def test_environment_outside_the_cliff_is_a_warning(tmp_path):
    issues = check(tmp_path, lambda s: p0(s).update(condition="dust-exposure-lunar-surface-eva"))
    assert any("is not expected in T1, T2, T4, T5" in m for m in messages(issues, "warning"))


def test_time_critical_treatment_not_aboard(tmp_path):
    def change(s):
        p0(s)["time_critical"][0]["action"]["refs"] = ["ertapenem-1gm"]

    issues = check(tmp_path, change)
    assert any(
        "none of ['ertapenem-1gm'] is aboard in T3" in m for m in messages(issues, "warning")
    )


def test_typo_in_a_field_name_is_an_error(tmp_path):
    def change(s):
        s["complicator"] = s.pop("complicators")

    issues = check(tmp_path, change)
    assert any(
        "complicator: Extra inputs are not permitted" in m for m in messages(issues, "error")
    )


def test_bad_time_offset_is_an_error(tmp_path):
    issues = check(tmp_path, lambda s: s["injects"][0].update(t="4 hours in"))
    assert any("not a time offset" in m for m in messages(issues, "error"))


def test_unknown_state_variable_is_a_warning(tmp_path):
    issues = check(tmp_path, lambda s: p0(s)["timeline"][1]["state"].update(heartrate=90))
    assert messages(issues, "error") == []
    assert any(
        "'heartrate' is not a known state variable" in m for m in messages(issues, "warning")
    )


def test_rubric_checks(tmp_path):
    issues = check(tmp_path, rubric_change=lambda r: r.update(base="general@9.9"))
    assert any("unknown base rubric 'general@9.9'" in m for m in messages(issues, "error"))

    def change(r):
        r["items"][0]["domain"] = "D9"
        r["items"][1]["text"] = "Examines the abdomen appropriately"
        r["scenario_id"] = "MSE-0002"
        r["items"][2]["patient"] = "C01"

    issues = check(tmp_path, rubric_change=change)
    assert any("item I1: unknown domain 'D9'" in m for m in messages(issues, "error"))
    assert any("is for 'MSE-0002'" in m for m in messages(issues, "error"))
    assert any("'C01' is not a patient" in m for m in messages(issues, "error"))
    assert any("'appropriately' is a judgment call" in m for m in messages(issues, "warning"))


@pytest.mark.parametrize(
    "item, expected",
    [
        ({"weight": 0}, "weight must not be 0"),
        ({"type": "rating"}, "rating items need anchors"),
        ({"weight": 11}, "less than or equal to 10"),
    ],
)
def test_checklist_item_shape(tmp_path, item, expected):
    issues = check(tmp_path, rubric_change=lambda r: r["items"][0].update(item))
    assert any(expected in m for m in messages(issues, "error")), messages(issues)


def test_drm_phases_must_add_up(tmp_path):
    drm = json.loads((DEFAULT_LIBRARY / "drms" / "imm-mars-pod-860d.drm.json").read_text())
    drm["drm_id"] = "test-drm"
    drm["duration_days"] = 900
    (tmp_path / "test.drm.json").write_text(json.dumps(drm))
    issues = validate([tmp_path])
    assert any(
        "phase days add up to 860, but duration_days is 900" in m for m in messages(issues, "error")
    )


def test_habitat_items_need_a_source_or_assumption(tmp_path):
    hab = json.loads((DEFAULT_LIBRARY / "habitats" / "orion.habitat.json").read_text())
    hab["profile_id"] = "test-hab"
    del hab["equipment"][0]["source"]
    (tmp_path / "test.habitat.json").write_text(json.dumps(hab))
    issues = validate([tmp_path])
    assert any("give a source or set assumption: true" in m for m in messages(issues, "error"))


def test_crew_baseline_outside_normal_range(tmp_path):
    roster = json.loads((DEFAULT_LIBRARY / "crew" / "active-corps.crew.json").read_text())
    roster["crew"] = roster["crew"][:1]
    roster["crew"][0]["baseline"]["hr"] = 130
    (tmp_path / "test.crew.json").write_text(json.dumps(roster))
    issues = validate([tmp_path])
    assert any(
        "C01: baseline hr 130 is outside the normal range" in m for m in messages(issues, "warning")
    )


def test_migrate_v01(tmp_path):
    for f in (FIXTURES / "v01").iterdir():
        shutil.copy(f, tmp_path / f.name)
    result = CliRunner().invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "migrated" in result.output
    assert (tmp_path / "MSE-0001.scenario.json.v0.1.bak").exists()
    new = json.loads((tmp_path / "MSE-0001.scenario.json").read_text())
    assert new["schema_version"] == "0.2" and "drm" not in new
    assert new["patients"][0]["condition"] == "appendicitis"
    assert new["patients"][0]["time_critical"][0]["by"] == "T+8h"
    issues = validate([tmp_path])
    assert messages(issues, "error") == [], issues
    assert any("etiology still needs writing" in m for m in messages(issues, "warning"))


def test_cli_exit_codes(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(app, ["validate", str(EXAMPLES)])
    assert ok.exit_code == 0, ok.output
    sc = copy.deepcopy(SCENARIO)
    p0(sc)["condition"] = "dragon-pox"
    bad = runner.invoke(app, ["validate", str(write_pair(tmp_path, sc, RUBRIC))])
    assert bad.exit_code == 1
    assert "unknown condition" in bad.output


def test_committed_form_is_current():
    from medsim_eval.form import DEFAULT_OUT, render

    # Compare outside an assert: pytest's diff of two large files is very slow.
    if DEFAULT_OUT.read_text(encoding="utf-8") != render():
        pytest.fail("dist/scenario-builder.html is stale: run `medsim build-form`")


def test_form_bundle_has_the_library():
    from medsim_eval.form import bundle

    b = bundle()
    assert len(b["conditions"]) == 118
    assert len(b["crew"]) == 20
    assert b["base_rubrics"][-1]["ref"] == "general@0.2"
    assert "solar_particle_event" in b["enums"]["event_kinds"]
    assert any(s["code"] == "R10.31" for s in b["symptoms"])
    assert any(e["id"] == "drug-ertapenem" for e in b["encyclopedia"])
