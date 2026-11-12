"""Normal physiology: adult reference ranges and how they shift in each mission environment.

The ranges check that every crewmember's baseline is normal. The adaptations are applied by
the digital twin on top of a crewmember's baseline. The physiologist owns this file.
"""

from __future__ import annotations

from pydantic import Field

from medsim_eval.models.common import Env, Sourced, Versioned


class Range(Sourced):
    var: str = Field(description="State variable, e.g. hr")
    low: float
    high: float
    unit: str
    sex: str | None = Field(None, description="M or F when the range differs by sex")


class Adaptation(Sourced):
    envs: list[Env]
    var: str = Field(description="State variable or physiological quantity")
    change: str = Field(
        description="As reported, e.g. '-10 mmHg (24-h mean)', 'no consistent change'"
    )
    after_days: float | None = Field(None, description="Time in that environment before it applies")


class Physiology(Versioned):
    ranges: list[Range]
    adaptations: list[Adaptation]
    reviewed_by: str | None = None
