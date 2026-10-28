"""Reference lists for the authoring form: standardized symptoms and the encyclopedia."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from medsim_eval.models.common import Id, Source, Strict, Versioned


class Symptom(Strict):
    code: str = Field(description="ICD-10-CM code with its dot, e.g. R10.31")
    name: str
    group: str = Field(
        description="The three-character category, e.g. R10 Abdominal and pelvic pain"
    )


class SymptomList(Versioned):
    source: Source
    symptoms: list[Symptom]


class Entry(Strict):
    id: Id
    kind: Literal["drug", "equipment", "term"]
    title: str
    text: str = Field(description="Short reference text")
    source: Source
    see_also: list[str] = []


class Encyclopedia(Versioned):
    note: str
    entries: list[Entry]
