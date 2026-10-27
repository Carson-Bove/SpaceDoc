"""The five mission environments as defaults for gravity and comms."""

from __future__ import annotations

from pydantic import Field

from medsim_eval.models.common import Env, Source, Strict, Versioned


class Environment(Strict):
    env: Env
    name: str
    gravity_g: float = Field(ge=0)
    one_way_delay_s: tuple[float, float]
    evacuation: str = Field(description="Rough time to definitive care, in words")
    hazards: list[str] = []
    sources: list[Source] = []
    note: str | None = None


class EnvironmentSet(Versioned):
    environments: list[Environment]
