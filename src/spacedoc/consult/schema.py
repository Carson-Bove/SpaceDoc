"""What the model returns in each question turn.

Every token costs time on a laptop, so the schema caps lengths and counts (maxLength,
maxItems). Constrained decoding enforces these caps while the model writes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


def _cap(chars: int) -> Any:
    return Field(json_schema_extra={"maxLength": chars})


class Urgent(BaseModel):
    flag: bool = False
    reason: str = Field("", json_schema_extra={"maxLength": 160})


class WorkingDx(BaseModel):
    condition: str = _cap(70)
    likelihood: Literal["high", "moderate", "low", "must not miss"]
    why: str = Field(description="A few words", json_schema_extra={"maxLength": 90})


class Question(BaseModel):
    text: str = _cap(180)
    why: str = Field(description="A few words", json_schema_extra={"maxLength": 90})
    answer_type: Literal["yes_no", "choice", "free_text", "measurement"] = "free_text"
    choices: list[str] = Field(default=[], json_schema_extra={"maxItems": 5})


class ExamRequest(BaseModel):
    text: str = Field(
        description="What to examine or measure", json_schema_extra={"maxLength": 150}
    )
    equipment: list[str] = Field(default=[], description="Equipment IDs from the aboard list")
    why: str = Field("", json_schema_extra={"maxLength": 90})


class TurnReply(BaseModel):
    urgent: Urgent = Urgent()
    message: str = Field(
        "",
        description="1-3 short sentences to the user: acknowledge what they said and answer "
        "any question they asked",
        json_schema_extra={"maxLength": 360},
    )
    working_ddx: list[WorkingDx] = Field(default=[], json_schema_extra={"maxItems": 5})
    questions: list[Question] = Field(default=[], json_schema_extra={"maxItems": 2})
    exam_requests: list[ExamRequest] = Field(default=[], json_schema_extra={"maxItems": 2})
    ready_to_assess: bool = False
