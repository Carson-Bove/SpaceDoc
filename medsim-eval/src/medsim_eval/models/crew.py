"""The crew roster: fictional crewmembers modelled on the active NASA astronaut corps.

Each entry is a digital twin of one astronaut: who they are, their training, their chart and
their normal physiology. The AI that plays a crewmember in a run works from this entry.
None of them is a real person; histories are synthetic and reviewed by the physiologist.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from medsim_eval.models.chart import Chart
from medsim_eval.models.common import Id, Source, Strict, Versioned

Background = Literal[
    "military_test_pilot",
    "military_aviator",
    "military_other",
    "physician",
    "scientist",
    "engineer",
]


class MedicalTraining(Strict):
    level: Literal["physician", "cmo", "basic"] = Field(
        description="physician; cmo: non-physician with standard CMO training; basic: first aid and CPR"
    )
    hours: float | None = Field(None, description="Premission medical training hours, if known")
    description: str


class Familiarity(Strict):
    """1 = none, 5 = expert."""

    medicine: int = Field(ge=1, le=5)
    equipment: int = Field(ge=1, le=5, description="The onboard medical equipment")
    assistant: int = Field(ge=1, le=5, description="Digital medical assistants")


class ImmTraits(Strict):
    """The crew characteristics NASA's Integrated Medical Model conditions on."""

    cac: bool = Field(description="Coronary artery calcium present")
    crowns: bool = Field(description="Dental crowns")
    contacts: bool = Field(description="Wears contact lenses")
    prior_abd_surgery: bool = Field(description="History of abdominal surgery")


class Baseline(Strict):
    """Normal preflight values. In-flight changes come from the physiology library."""

    hr: float
    sbp: float
    dbp: float
    rr: float
    spo2: float
    temp_c: float
    hgb_g_dl: float
    wbc_10e9_l: float
    glucose_mmol_l: float


class CrewTwin(Strict):
    crew_id: Id
    name: str = Field(description="Fictional full name")
    sex: Literal["M", "F"]
    age: int = Field(ge=25, le=70)
    height_cm: float
    weight_kg: float
    background: Background
    occupation: str = Field(description="In plain words, e.g. Navy test pilot, emergency physician")
    education: Literal["bachelor", "master", "doctorate", "md"]
    selection_year: int
    flights: int = Field(ge=0)
    days_in_space: int = Field(ge=0)
    eva_qualified: bool
    medical_role: Literal["cmo", "backup_cmo", "crew"] = Field(
        description="Default role on a mission; a scenario can still choose anyone"
    )
    medical_training: MedicalTraining
    familiarity: Familiarity
    communication_style: str = Field(description="For the AI that plays them")
    imm: ImmTraits
    chart: Chart
    baseline: Baseline
    synthetic: Literal[True] = True


class CrewRoster(Versioned):
    sources: list[Source] = []
    method: str = Field(description="How the roster was built, in plain words")
    crew: list[CrewTwin] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> CrewRoster:
        for key in ("crew_id", "name"):
            vals = [getattr(c, key) for c in self.crew]
            if len(vals) != len(set(vals)):
                raise ValueError(f"{key} values must be unique")
        return self
