"""Spot checks that the library matches its NASA sources, and simulated-time parsing."""

from __future__ import annotations

import json

import pytest

from medsim_eval.models import DRM
from medsim_eval.simtime import format_offset, parse_duration, parse_offset
from medsim_eval.validate import DEFAULT_LIBRARY


def load(rel: str) -> dict:
    return json.loads((DEFAULT_LIBRARY / rel).read_text())


def test_appendicitis_course_matches_the_cliff():
    # Values read by hand from the 2023 appendicitis CLiFF, Table 4.
    idx = {c["cliff_id"]: c for c in load("conditions/imm.conditions.json")["conditions"]}
    c = idx["appendicitis"]
    assert c["icl"] == "ICL8"
    tbc, twc, utwc = (c["course"][k] for k in ("treated_best", "treated_worst", "untreated_worst"))
    assert tbc["probability_pct"] == [62.6, 77.5]
    assert twc["probability_pct"] == [22.5, 37.4]
    assert tbc["cp1_hours"] == 1.83
    assert twc["cp2_hours"] == [168, 240]
    assert twc["locl_pct"] == [0, 8.7]
    assert utwc["locl_pct"] == [0, 50]
    assert c["course"]["incidence_mean"] == pytest.approx(9.34e-4)


def test_condition_index_uses_the_2023_list():
    conditions = load("conditions/imm.conditions.json")["conditions"]
    assert len(conditions) == 118
    assert all(c["cliff"]["list"] == "cliff119_2023" for c in conditions)
    assert len({c["cliff_id"] for c in conditions}) == len(conditions)
    assert all(c["course"]["reviewed_by"] is None for c in conditions)


def test_condition_applicability_from_the_cliffs():
    idx = {c["cliff_id"]: c for c in load("conditions/imm.conditions.json")["conditions"]}
    assert idx["appendicitis"]["applicability"]["envs"] == ["T1", "T2", "T3", "T4", "T5"]
    assert idx["appendicitis"]["summary"].startswith("Appendicitis is acute inflammation")
    assert idx["dust-exposure-lunar-surface-eva"]["applicability"]["envs"] == ["T3"]
    assert idx["eva-related-decompression-sickness"]["applicability"]["eva"] is True
    sms = idx["space-adaptation-space-motion-sickness"]["applicability"]
    assert sms["timing"] == "early_flight" and sms["onset_hours"] == [1, 120]
    # SANS is in the space-adaptation segment but develops over weeks.
    assert (
        idx["space-flight-associated-neuro-ocular-syndrome-sans"]["applicability"]["timing"]
        == "any"
    )
    # Sex-specific only when every incidence row names the same sex.
    assert idx["prostatitis-acute"]["applicability"]["sex"] == "M"
    assert idx["anaphylaxis"]["applicability"]["sex"] == "any"


def test_roster_matches_the_corps_shape():
    crew = load("crew/active-corps.crew.json")["crew"]
    assert len(crew) == 20
    assert sum(c["sex"] == "F" for c in crew) == 8
    assert sum(c["medical_training"]["level"] == "physician" for c in crew) == 3
    for trait in ("cac", "crowns", "contacts", "prior_abd_surgery"):
        assert sum(c["imm"][trait] for c in crew) == 5, trait
    assert all(c["synthetic"] for c in crew)


def test_every_environment_has_a_run_context():
    envs = load("environments/missions.environments.json")["environments"]
    assert all(e["representative"] for e in envs)
    assert [e["env"] for e in envs if e["default_run"]] == ["T1", "T4", "T5"]


def test_symptom_list_is_icd10cm_symptoms():
    symptoms = load("symptoms/icd10cm.symptoms.json")["symptoms"]
    codes = {s["code"] for s in symptoms}
    assert {"R10.31", "R11.0", "R50.9", "M25.571", "H57.11"} <= codes
    assert all(s["code"][0] in "RMH" for s in symptoms)


def test_encyclopedia_drug_labels():
    entries = {e["id"]: e for e in load("encyclopedia/reference.encyclopedia.json")["entries"]}
    assert "dailymed" in entries["drug-ertapenem"]["source"]["url"]
    assert "ranitidine" in entries["drug-famotidine"]["text"]  # the substitution is explained
    assert any(e["kind"] == "term" for e in entries.values())


def test_mars_point_of_departure_segments():
    drm = DRM.model_validate(load("drms/imm-mars-pod-860d.drm.json"))
    assert [p.days for p in drm.phases] == [90, 305, 50, 375, 40]
    assert drm.phase_window("loiter") == (395, 445)
    loiter = next(p for p in drm.phases if p.id == "loiter")
    assert loiter.eva.crew == ["C2", "C4"] and loiter.eva.window_days == (405, 429)


def test_orion_kit_is_much_smaller_than_iss():
    iss = load("habitats/iss.habitat.json")
    orion = load("habitats/orion.habitat.json")
    caps = {c["id"]: c["status"] for c in orion["capabilities"]}
    assert caps["ultrasound"] == "unavailable" and caps["defibrillation"] == "unavailable"
    assert {c["id"]: c["status"] for c in iss["capabilities"]}["ultrasound"] == "available"
    assert len(orion["formulary"]) < len(iss["formulary"])
    tylenol = next(i for i in orion["formulary"] if i["id"] == "tylenol-acetaminophen-325-mg")
    assert tylenol["qty"] == 96


@pytest.mark.parametrize(
    "text, seconds",
    [
        ("T+0", 0),
        ("T+30m", 1800),
        ("T+8h", 28800),
        ("T+1d6h", 108000),
        ("T+1.5h", 5400),
        ("T + 2d", 172800),
    ],
)
def test_offsets(text, seconds):
    assert parse_offset(text) == seconds


@pytest.mark.parametrize("bad", ["8h", "T+", "T+8x", "T-2h", "soon"])
def test_bad_offsets(bad):
    with pytest.raises(ValueError):
        parse_offset(bad)


def test_round_trip():
    for s in (0, 59, 3600, 108000, 90061):
        assert parse_offset(format_offset(s)) == s
    assert parse_duration("10h") == 36000
