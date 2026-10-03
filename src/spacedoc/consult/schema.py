"""What the model returns in each question turn. Kept short: every token costs time."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Urgent(BaseModel):
    flag: bool = False
    reason: str = ""


class Fact(BaseModel):
    item: str = Field(description="What the fact is about, e.g. 'onset' or 'headache'")
    value: str = Field(description="What the user said, in their words where possible")


class WorkingDx(BaseModel):
    condition: str
    likelihood: Literal["high", "moderate", "low", "must not miss"]
    why: str = Field(description="One short reason")


class Question(BaseModel):
    text: str
    why: str = Field(description="One short reason for asking")
    answer_type: Literal["yes_no", "choice", "free_text", "measurement"] = "free_text"
    choices: list[str] = []


class ExamRequest(BaseModel):
    text: str = Field(description="What to examine or measure, and how")
    equipment: list[str] = Field(default=[], description="Equipment IDs from the aboard list")
    why: str = ""


class TurnReply(BaseModel):
    urgent: Urgent = Urgent()
    facts: list[Fact] = Field(default=[], description="New facts from the latest message only")
    working_ddx: list[WorkingDx] = []
    questions: list[Question] = Field(default=[], description="At most two")
    exam_requests: list[ExamRequest] = []
    ready_to_assess: bool = False
