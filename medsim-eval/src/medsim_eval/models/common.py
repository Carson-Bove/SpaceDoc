"""Shared pieces of the file formats."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from medsim_eval import SCHEMA_VERSION
from medsim_eval.simtime import parse_duration, parse_offset

# The five mission environments (docs/00): LEO, cislunar, lunar surface, deep-space / Mars
# transit, Mars surface.
Env = Literal["T1", "T2", "T3", "T4", "T5"]

Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=80)]

Offset = Annotated[
    str, Field(description="Simulated time from scenario start, e.g. T+0, T+30m, T+1d6h")
]
Duration = Annotated[str, Field(description="Simulated duration, e.g. 30m, 10h, 2d")]


class Strict(BaseModel):
    """Unknown keys are errors, so a typo in a hand-edited file is caught instead of ignored."""

    model_config = ConfigDict(extra="forbid")


class Versioned(Strict):
    schema_version: str = SCHEMA_VERSION


class Source(Strict):
    """Where a value came from. `doc` is a short citation; `url` is where to read it."""

    doc: str
    url: str | None = None
    locator: str | None = Field(None, description="Table, page or section within the document")


class Sourced(Strict):
    """A value that must carry either a source or an explicit assumption flag."""

    source: Source | None = None
    assumption: bool = False
    note: str | None = None

    def is_grounded(self) -> bool:
        return self.source is not None or self.assumption


def check_offset(value: str) -> str:
    parse_offset(value)
    return value


def check_duration(value: str) -> str:
    parse_duration(value)
    return value


class Timed(Strict):
    """Mixin for models with a `t` offset."""

    t: Offset

    @field_validator("t")
    @classmethod
    def _t(cls, v: str) -> str:
        return check_offset(v)
