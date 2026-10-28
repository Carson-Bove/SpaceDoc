"""The five mission environments as defaults for gravity and comms."""

from __future__ import annotations

from pydantic import Field

from medsim_eval.models.common import Env, Id, Source, Strict, Versioned


class RunContext(Strict):
    """Where the runner places a case in this environment."""

    drm: Id
    phase: Id
    note: str | None = None


class Environment(Strict):
    env: Env
    name: str
    gravity_g: float = Field(ge=0)
    one_way_delay_s: tuple[float, float]
    evacuation: str = Field(description="Rough time to definitive care, in words")
    hazards: list[str] = []
    sources: list[Source] = []
    representative: RunContext | None = Field(
        None, description="The DRM and phase used when a case runs in this environment"
    )
    default_run: bool = Field(False, description="Included in a default batch")
    note: str | None = None


class EnvironmentSet(Versioned):
    environments: list[Environment]
