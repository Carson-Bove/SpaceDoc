"""The canonical answer: the structured form every response takes before verification.

Separating content (this schema) from presentation (render/) is what lets the verifier
check each claim, number and action individually.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RiskTier = Literal["R0", "R1", "R2", "R3", "R4"]


class Claim(BaseModel):
    id: str = Field(description="C1, C2, ...")
    text: str = Field(description="One atomic factual statement")
    kind: Literal["sourced", "patient", "reasoning"] = Field(
        description="sourced: from passages (must cite). patient: from the record. "
        "reasoning: your own inference (no numbers allowed)."
    )
    citations: list[str] = Field(default=[], description="Passage IDs like S1, S2")


class DxItem(BaseModel):
    condition: str
    likelihood: Literal["high", "moderate", "low"]
    citations: list[str] = []


class Action(BaseModel):
    id: str = Field(description="A1, A2, ...")
    text: str
    kind: Literal["medication", "test", "procedure", "monitor", "advice", "escalate"]
    item: str | None = Field(default=None, description="Formulary item name for medications")
    equipment: list[str] = Field(default=[], description="Equipment the action needs")
    calc_ref: str | None = Field(default=None, description="calc_id of the calculator result used")
    risk_tier: RiskTier


class CalcRequest(BaseModel):
    calculator: str
    args: dict[str, Any] = {}


class DraftAnswer(BaseModel):
    summary: str = Field(description="One or two sentences, no numbers")
    claims: list[Claim] = []
    differential: list[DxItem] = []
    actions: list[Action] = []
    calc_requests: list[CalcRequest] = []
    uncertainty: Literal["low", "moderate", "high"]
    abstain: bool = False
    missing_info: list[str] = []


def draft_json_schema() -> dict[str, Any]:
    return DraftAnswer.model_json_schema()


# ---- Verification results -------------------------------------------------------------

ClaimStatus = Literal["supported", "unsupported", "contradicted", "reasoning", "removed"]
ActionStatus = Literal["ok", "requires_confirmation", "blocked"]


class ClaimVerdict(BaseModel):
    claim: Claim
    status: ClaimStatus
    shown: bool
    detail: str = ""
    checked_against: list[str] = []


class Finding(BaseModel):
    rule_id: str
    severity: Literal["block", "warn", "info"]
    target: str  # claim id, action id, passage id, or "answer"
    message: str


class ActionVerdict(BaseModel):
    action: Action
    status: ActionStatus
    reasons: list[str] = []
    calc_text: str | None = None


class Passage(BaseModel):
    cid: str  # S1, S2, ... (stable within one answer)
    chunk_id: str
    source_id: str
    title: str
    text: str
    page: int | None = None
    url: str | None = None
    tier: str = "C"
    score: float = 0.0


class VerifiedAnswer(BaseModel):
    question: str
    environment: str
    summary: str
    claims: list[ClaimVerdict]
    differential: list[DxItem]
    actions: list[ActionVerdict]
    calc_results: list[dict[str, Any]] = []
    findings: list[Finding]
    passages: list[Passage]
    uncertainty: str
    abstained: bool
    abstain_reason: str | None = None
    missing_info: list[str] = []
    draft: DraftAnswer | None = None
    audit_id: str | None = None
    timings: dict[str, float] = {}
    # True when the model produced thinking notes, which are kept in the audit log for
    # clinical review (never shown to the crew as part of the answer).
    reasoning_available: bool = False

    @property
    def shown_claims(self) -> list[ClaimVerdict]:
        return [c for c in self.claims if c.shown]
