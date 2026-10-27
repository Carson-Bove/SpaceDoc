"""The validator: the shipped library is clean, and broken files are caught with useful messages."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from medsim_eval.cli import app, schema_documents
from medsim_eval.validate import DEFAULT_LIBRARY, validate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SCENARIO = json.loads((EXAMPLES / "MSE-0001.scenario.json").read_text())
RUBRIC = json.loads((EXAMPLES / "MSE-0001.rubric.json").read_text())


def write_pair(folder: Path, scenario: dict, rubric: dict) -> Path:
    (folder / "MSE-0001.scenario.json").write_text(json.dumps(scenario))
    (folder / "MSE-0001.rubric.json").write_text(json.dumps(rubric))
    return folder


def messages(issues, level=None):
    return [i.message for i in issues if level is None or i.level == level]


def test_library_and_examples_are_clean():
    assert validate([DEFAULT_LIBRARY, EXAMPLES]) == []


def test_committed_schemas_are_current():
    for name, doc in schema_documents().items():
        committed = json.loads((ROOT / "schemas" / name).read_text())
        assert committed == doc, f"schemas/{name} is stale: run `medsim schema`"


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda s: s.update(drm="imm-nope"), "unknown DRM 'imm-nope'"),
        (lambda s: s.update(phase="loiter-x"), "has no phase 'loiter-x'"),
        (
            lambda s: s.update(mission_day=500),
            "mission_day 500 is outside phase outbound (days 90 to 395)",
        ),
        (lambda s: s.update(crewmember="C9"), "crewmember 'C9' is not in DRM"),
        (lambda s: s["condition"].update(cliff_id="dragon-pox"), "unknown condition 'dragon-pox'"),
        (lambda s: s.update(status="approved"), "approved scenarios need at least one reviewer"),
        (
            lambda s: s.update(rubric="missing.rubric.json"),
            "rubric file 'missing.rubric.json' not found",
        ),
    ],
)
def test_scenario_cross_references(tmp_path, change, expected):
    sc = copy.deepcopy(SCENARIO)
    change(sc)
    issues = validate([write_pair(tmp_path, sc, RUBRIC)])
    assert any(expected in m for m in messages(issues, "error")), messages(issues)


def test_typo_in_a_field_name_is_an_error(tmp_path):
    sc = copy.deepcopy(SCENARIO)
    sc["complicator"] = sc.pop("complicators")
    issues = validate([write_pair(tmp_path, sc, RUBRIC)])
    assert any(
        "complicator: Extra inputs are not permitted" in m for m in messages(issues, "error")
    )


def test_bad_time_offset_is_an_error(tmp_path):
    sc = copy.deepcopy(SCENARIO)
    sc["events"][0]["t"] = "4 hours in"
    issues = validate([write_pair(tmp_path, sc, RUBRIC)])
    assert any("not a time offset" in m for m in messages(issues, "error"))


def test_unknown_state_variable_is_a_warning(tmp_path):
    sc = copy.deepcopy(SCENARIO)
    sc["timeline"][1]["state"]["heartrate"] = 90
    issues = validate([write_pair(tmp_path, sc, RUBRIC)])
    assert messages(issues, "error") == []
    assert any(
        "'heartrate' is not a known state variable" in m for m in messages(issues, "warning")
    )


def test_rubric_checks(tmp_path):
    rb = copy.deepcopy(RUBRIC)
    rb["base"] = "general@9.9"
    issues = validate([write_pair(tmp_path, SCENARIO, rb)])
    assert any("unknown base rubric 'general@9.9'" in m for m in messages(issues, "error"))

    rb = copy.deepcopy(RUBRIC)
    rb["items"][0]["domain"] = "D9"
    rb["items"][1]["text"] = "Examines the abdomen appropriately"
    rb["scenario_id"] = "MSE-0002"
    issues = validate([write_pair(tmp_path, SCENARIO, rb)])
    assert any("item I1: unknown domain 'D9'" in m for m in messages(issues, "error"))
    assert any("is for 'MSE-0002'" in m for m in messages(issues, "error"))
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
    rb = copy.deepcopy(RUBRIC)
    rb["items"][0].update(item)
    issues = validate([write_pair(tmp_path, SCENARIO, rb)])
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


def test_cli_exit_codes(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(app, ["validate", str(EXAMPLES)])
    assert ok.exit_code == 0, ok.output
    sc = copy.deepcopy(SCENARIO)
    sc["drm"] = "imm-nope"
    bad = runner.invoke(app, ["validate", str(write_pair(tmp_path, sc, RUBRIC))])
    assert bad.exit_code == 1
    assert "unknown DRM" in bad.output


def test_committed_form_is_current():
    from medsim_eval.form import DEFAULT_OUT, render

    assert DEFAULT_OUT.read_text(encoding="utf-8") == render(), (
        "dist/scenario-builder.html is stale: run `medsim build-form`"
    )


def test_form_bundle_has_the_library():
    from medsim_eval.form import bundle

    b = bundle()
    assert len(b["conditions"]) == 118
    assert {d["drm_id"] for d in b["drms"]} >= {"imm-mars-pod-860d", "imm-artemis-7.5d"}
    assert b["base_rubrics"][-1]["ref"] == "general@0.1"
    assert "solar_particle_event" in b["enums"]["event_kinds"]
