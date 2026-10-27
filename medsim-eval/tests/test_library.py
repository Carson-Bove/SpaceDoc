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
