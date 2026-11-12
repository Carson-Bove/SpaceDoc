"""Design Reference Mission: the mission a scenario happens inside (docs/11 §4.1).

Fields follow the inputs NASA's Integrated Medical Model uses: mission length, crew size and
characteristics, and the EVA schedule. Phases are our addition; the IMM has no timeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from medsim_eval.models.common import Env, Id, Source, Strict, Versioned


class CrewMember(Strict):
    crew_id: Id
    sex: Literal["M", "F"]
    # The pre-existing history the IMM conditions on.
    cac: bool = Field(False, description="Coronary artery calcium present")
    crowns: bool = Field(False, description="Dental crowns")
    contacts: bool = Field(False, description="Wears contact lenses")
    prior_abd_surgery: bool = Field(False, description="History of abdominal surgery")
    eva: bool = Field(False, description="Assigned to EVAs in this DRM")
    role: str | None = Field(None, description="e.g. CMO, commander; optional")


class EvaPlan(Strict):
    crew: list[Id]
    count: int = Field(
        ge=0, description="EVAs per crewmember in this phase (or total four-person EVAs; see note)"
    )
    window_days: tuple[float, float] | None = Field(
        None, description="Mission days the EVAs fall in"
    )
    note: str | None = None


class Comms(Strict):
    one_way_delay_s: tuple[float, float] = Field(description="Minimum and maximum one-way delay")
    blackouts: list[str] = Field(
        default=[], description="Known blackout causes, e.g. solar conjunction"
    )
    note: str | None = None


class Phase(Strict):
    id: Id
    name: str
    env: Env
    days: float = Field(gt=0)
    habitats: list[Id] = Field(
        default=[], description="Habitat profile ids in use during this phase"
    )
    eva: EvaPlan | None = None
    comms: Comms | None = Field(None, description="Overrides the environment's default comms")
    assumption: bool = Field(False, description="True if the phase split is ours, not the source's")
    note: str | None = None


class Resources(Strict):
    state: Literal["fully_treated", "medcap", "untreated"] = Field(
        description="IMM resource state: continuous resupply, fixed kit, or none"
    )
    resupply: bool
    kit_mass_kg: float | None = None
    kit_volume_cm3: float | None = None
    note: str | None = None


class DRM(Versioned):
    drm_id: Id
    name: str
    source: Source
    duration_days: float = Field(gt=0)
    crew: list[CrewMember] = Field(min_length=1)
    phases: list[Phase] = Field(min_length=1)
    resources: Resources
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> DRM:
        ids = [c.crew_id for c in self.crew]
        if len(ids) != len(set(ids)):
            raise ValueError("crew_id values must be unique")
        pids = [p.id for p in self.phases]
        if len(pids) != len(set(pids)):
            raise ValueError("phase ids must be unique")
        total = sum(p.days for p in self.phases)
        if abs(total - self.duration_days) > 0.01:
            raise ValueError(
                f"phase days add up to {total:g}, but duration_days is {self.duration_days:g}"
            )
        for p in self.phases:
            if p.eva:
                unknown = set(p.eva.crew) - set(ids)
                if unknown:
                    raise ValueError(f"phase {p.id}: EVA crew not in DRM crew: {sorted(unknown)}")
        return self

    def phase_window(self, phase_id: str) -> tuple[float, float]:
        """Mission days [start, end) covered by a phase, counting from day 0."""
        start = 0.0
        for p in self.phases:
            if p.id == phase_id:
                return start, start + p.days
            start += p.days
        raise KeyError(phase_id)
