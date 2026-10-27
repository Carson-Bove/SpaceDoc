"""Index of IMM conditions and their Clinical Finding Forms (CLiFFs).

Built by scripts/build_cliff_index.py from NASA's IMM documentation page; re-run it to pick up
new CLiFF versions. The index uses the most recent list (the 2023 "CliFF 119" set); the older
100-condition CLiFF is linked as `legacy` where one clearly matches.

The course numbers are read automatically from each CLiFF's Table 4 and are marked unreviewed
until the physiologist checks them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from medsim_eval.models.common import Id, Strict, Versioned

Range = tuple[float, float]


class CliffDoc(Strict):
    label: str = Field(
        description="Link text on NASA's page (sometimes wrong; the url is authoritative)"
    )
    url: str
    list: Literal["cliff119_2023", "cliff100"]


class CaseCourse(Strict):
    """One row of a CLiFF's Table 4. TI = task impairment %; durations in hours."""

    probability_pct: Range | None = Field(None, description="Share of cases that take this course")
    cp1_ti_pct: float | None = Field(
        None, description="Clinical phase 1 (diagnosis): task impairment %"
    )
    cp1_hours: float | None = None
    cp2_ti_pct: float | None = Field(
        None, description="Clinical phase 2 (treatment): task impairment %"
    )
    cp2_hours: Range | None = None
    cp3_ti_pct: float | None = Field(
        None, description="Clinical phase 3 (end state): lasting task impairment %"
    )
    rtdc_pct: Range | None = Field(None, description="Removal to definitive care, %")
    locl_pct: Range | None = Field(None, description="Loss of crew life, %")


class Course(Strict):
    incidence_mean: float | None = Field(
        None, description="Units depend on the condition: see the CLiFF"
    )
    incidence_sd: float | None = None
    incidence_text: str | None = Field(
        None, description="The incidence as written, e.g. when it differs by sex"
    )
    treated_best: CaseCourse | None = None
    treated_worst: CaseCourse | None = None
    untreated_best: CaseCourse | None = None
    untreated_worst: CaseCourse | None = None
    extraction: Literal["automatic"] = "automatic"
    reviewed_by: str | None = Field(
        None, description="Set when the physiologist has checked these numbers"
    )


class Condition(Strict):
    cliff_id: Id = Field(description="Stable id from the condition name, e.g. appendicitis")
    icl: str = Field(description="NASA's condition code, e.g. ICL8")
    name: str
    category: str
    cliff: CliffDoc
    legacy: CliffDoc | None = Field(None, description="Matching 100-condition CLiFF, if any")
    peer_review: CliffDoc | None = None
    course: Course | None = None


class ConditionIndex(Versioned):
    source_url: str
    retrieved: str = Field(description="ISO date the page was read")
    conditions: list[Condition]
