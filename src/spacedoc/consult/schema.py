"""What the model returns in each question turn.

The person sees one thing: `message`, written in natural speech, with the questions and any
examination in it. The other fields describe that message for SpaceDoc's checks and the
record (short topics, reasons, equipment), so they stay short. Every token costs time on a
laptop; the schema caps lengths and counts, and constrained decoding enforces the caps.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


def _cap(chars: int, description: str | None = None) -> Any:
    return Field(description=description, json_schema_extra={"maxLength": chars})


class Urgent(BaseModel):
    flag: bool = False
    reason: str = Field("", json_schema_extra={"maxLength": 140})


class WorkingDx(BaseModel):
    condition: str = _cap(60)
    likelihood: Literal["high", "moderate", "low", "must not miss"]
    why: str = _cap(60, "A few words")


class Question(BaseModel):
    """One question asked in the message."""

    topic: str = _cap(50, "The question's subject in a few words, e.g. 'how the cut happened'")
    why: str = _cap(80, "Why you are asking, in a few words")
    answer_type: Literal["yes_no", "choice", "free_text", "measurement"] = "free_text"
    choices: list[str] = Field(default=[], json_schema_extra={"maxItems": 5})


class ExamRequest(BaseModel):
    """One examination or measurement asked for in the message."""

    what: str = _cap(60, "The examination in a few words")
    equipment: list[str] = Field(default=[], description="Equipment IDs from the aboard list")


class TurnReply(BaseModel):
    urgent: Urgent = Urgent()
    message: str = Field(
        "",
        description="Everything you say to the person, in natural speech, including your "
        "questions and any examination",
        json_schema_extra={"maxLength": 500},
    )
    questions: list[Question] = Field(default=[], json_schema_extra={"maxItems": 2})
    exam_requests: list[ExamRequest] = Field(default=[], json_schema_extra={"maxItems": 2})
    working_ddx: list[WorkingDx] = Field(default=[], json_schema_extra={"maxItems": 5})
    ready_to_assess: bool = False
