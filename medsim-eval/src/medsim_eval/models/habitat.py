"""Habitat profile: one vehicle or base element and what medicine is possible there (docs/11 §4.2).

Every equipment item, drug and capability carries a source or an explicit assumption flag, so a
reader can always tell which parts are NASA's and which are ours.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from medsim_eval.models.common import Env, Id, Source, Sourced, Strict, Versioned


class Item(Sourced):
    id: Id
    name: str
    category: Literal["drug", "fluid", "equipment", "intervention"] | None = None
    qty: float | None = None
    unit: str | None = None


class Capability(Sourced):
    id: Id
    name: str
    status: Literal["available", "adapted", "unavailable", "unknown"]


class Kit(Strict):
    mass_kg: float | None = None
    volume_cm3: float | None = None
    source: Source | None = None


class Habitat(Versioned):
    profile_id: Id
    name: str
    kind: Literal["vehicle", "station", "surface_habitat", "rover", "lander", "other"]
    envs: list[Env] = Field(
        min_length=1, description="Mission environments this element operates in"
    )
    gravity_g: float = Field(ge=0)
    crew_capacity: int | None = None
    status: Literal["operational", "in_development", "concept"]
    sources: list[Source] = []
    kit: Kit | None = None
    equipment: list[Item] = []
    formulary: list[Item] = []
    capabilities: list[Capability] = []
    notes: str | None = None

    @model_validator(mode="after")
    def _grounded(self) -> Habitat:
        for group in ("equipment", "formulary", "capabilities"):
            entries = getattr(self, group)
            ids = [e.id for e in entries]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{group}: ids must be unique")
            for e in entries:
                if not e.is_grounded():
                    raise ValueError(f"{group}.{e.id}: give a source or set assumption: true")
        return self
