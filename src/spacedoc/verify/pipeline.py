"""The verification pipeline (component C-11): turns a draft into a verified answer.

Order: citation validity -> grounding (L4) -> numbers (L3/L6) -> formulary, equipment and
environment rules (L6) -> risk gating (L7) -> abstention decision.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from spacedoc.answer.schema import (
    ActionVerdict,
    ClaimVerdict,
    DraftAnswer,
    Finding,
    Passage,
    VerifiedAnswer,
)
from spacedoc.env.context import EnvironmentContext
from spacedoc.llm.client import LLMError
from spacedoc.tools.calculators import CalcResult
from spacedoc.tools.formulary import Formulary
from spacedoc.verify import rules
from spacedoc.verify.grounding import GroundingChecker, GroundingVerdict, split_sentences


class Verifier:
    def __init__(
        self,
        checker: GroundingChecker,
        formulary: Formulary,
        feasibility: list[rules.FeasibilityRule],
        min_support_fraction: float = 0.5,
        today: date | None = None,
    ) -> None:
        self.checker = checker
        self.formulary = formulary
        self.feasibility = feasibility
        self.min_support_fraction = min_support_fraction
        self.today = today

    def _check(self, text: str, doc: str, label: str, findings: list[Finding]) -> GroundingVerdict:
        """One grounding check; a failed call counts as unsupported (never shown)."""
        try:
            return self.checker.check(text, doc)
        except LLMError as e:
            if not any(f.rule_id == "CHECK-ERROR" for f in findings):
                findings.append(
                    Finding(
                        rule_id="CHECK-ERROR",
                        severity="warn",
                        target="answer",
                        message=f"Grounding check failed, so affected claims are hidden: {e}",
                    )
                )
            return GroundingVerdict(False, f"{label}: check failed")

    def _ground(
        self,
        claim: str,
        cites: list[str],
        by_cid: dict[str, Passage],
        findings: list[Finding],
    ) -> tuple[bool, str]:
        """Is every sentence of the claim supported by its cited passages?

        MiniCheck checks one sentence at a time, so multi-sentence claims are split. Each
        sentence is checked against each cited passage; if none supports it alone and the claim
        cites several passages, it is checked against up to three of them together (a claim may
        combine facts from two passages).
        """
        notes = []
        for sentence in split_sentences(claim) or [claim]:
            ok = False
            for cid in cites:
                v = self._check(sentence, by_cid[cid].text, cid, findings)
                notes.append(f"{cid}: {v.raw}")
                if v.supported:
                    ok = True
                    break
            if not ok and len(cites) >= 2:
                group = cites[:3]
                doc = "\n\n".join(by_cid[c].text for c in group)
                label = "+".join(group)
                v = self._check(sentence, doc, label, findings)
                notes.append(f"{label} together: {v.raw}")
                ok = v.supported
            if not ok:
                return False, "; ".join(notes)
        return True, "; ".join(notes)

    def verify(
        self,
        question: str,
        draft: DraftAnswer,
        passages: list[Passage],
        calc_results: list[CalcResult],
        env: EnvironmentContext,
        patient: dict[str, Any] | None = None,
        extra_findings: list[Finding] | None = None,
    ) -> VerifiedAnswer:
        by_cid = {p.cid: p for p in passages}
        calcs = {c.calc_id: c for c in calc_results}
        ptext = rules.patient_text(patient)
        findings: list[Finding] = list(extra_findings or [])
        verdicts: list[ClaimVerdict] = []

        for claim in draft.claims:
            bad_cites = [c for c in claim.citations if c not in by_cid]
            for c in bad_cites:
                findings.append(
                    Finding(
                        rule_id="CITE-INVALID",
                        severity="block",
                        target=claim.id,
                        message=f"Cited passage {c} does not exist",
                    )
                )
            valid_cites = [c for c in claim.citations if c in by_cid]

            num = rules.check_claim_numbers(claim, by_cid, ptext)
            if num:
                findings.append(num)
                verdicts.append(
                    ClaimVerdict(claim=claim, status="removed", shown=False, detail=num.message)
                )
                continue

            if claim.kind == "reasoning":
                verdicts.append(
                    ClaimVerdict(
                        claim=claim,
                        status="reasoning",
                        shown=True,
                        detail="Model reasoning, not taken from a source",
                    )
                )
            elif claim.kind == "patient":
                verdicts.append(
                    ClaimVerdict(
                        claim=claim,
                        status="supported",
                        shown=True,
                        detail="From the patient record (numbers checked)",
                    )
                )
            elif not valid_cites:
                verdicts.append(
                    ClaimVerdict(
                        claim=claim,
                        status="unsupported",
                        shown=False,
                        detail="No valid citation (cite-or-drop)",
                    )
                )
            else:
                supported, detail = self._ground(claim.text, valid_cites, by_cid, findings)
                verdicts.append(
                    ClaimVerdict(
                        claim=claim,
                        status="supported" if supported else "unsupported",
                        shown=supported,
                        detail=detail,
                        checked_against=valid_cites,
                    )
                )

            for f in rules.check_feasibility(
                claim.id, claim.text, env, self.feasibility, is_action=False
            ):
                findings.append(f)

        action_verdicts: list[ActionVerdict] = []
        for action in draft.actions:
            act_findings: list[Finding] = []
            if n := rules.check_action_numbers(action, calcs, self.formulary):
                act_findings.append(n)
            if action.calc_ref and action.calc_ref not in calcs:
                act_findings.append(
                    Finding(
                        rule_id="CALC-MISSING",
                        severity="block",
                        target=action.id,
                        message=f"Referenced calculator result {action.calc_ref} does not exist",
                    )
                )
            act_findings += rules.check_formulary(action, self.formulary, self.today)
            act_findings += rules.check_equipment(action, env)
            act_findings += rules.check_feasibility(
                action.id, action.text, env, self.feasibility, True
            )
            findings += act_findings

            blocks = [f.message for f in act_findings if f.severity == "block"]
            if action.risk_tier == "R4":
                blocks.append(
                    "Emergency actions run only through the deterministic protocol engine"
                )
            if blocks:
                status = "blocked"
                reasons = blocks
            elif action.risk_tier in {"R2", "R3"}:
                status = "requires_confirmation"
                reasons = [
                    "Requires CMO confirmation"
                    + (" and a second-crew read-back" if action.risk_tier == "R3" else "")
                ]
            else:
                status, reasons = "ok", []
            reasons += [f.message for f in act_findings if f.severity == "warn"]
            calc = calcs.get(action.calc_ref or "")
            if calc:
                has_form_flag = any(f.rule_id == "FORM-UNVALIDATED" for f in act_findings)
                reasons += [
                    w
                    for w in calc.warnings
                    if not (has_form_flag and "clinician-validated" in w.lower())
                ]
            action_verdicts.append(
                ActionVerdict(
                    action=action,
                    status=status,
                    reasons=reasons,
                    calc_text=calc.text if calc else None,
                )
            )

        sourced = [v for v in verdicts if v.claim.kind == "sourced"]
        supported = [v for v in sourced if v.status == "supported"]
        abstained, reason = (
            draft.abstain,
            "The model judged the sources insufficient" if draft.abstain else None,
        )
        if not abstained and sourced and len(supported) / len(sourced) < self.min_support_fraction:
            abstained = True
            reason = (
                f"Only {len(supported)} of {len(sourced)} sourced claims were supported by their "
                "sources, below the reliability threshold"
            )
        if not abstained and not passages:
            abstained, reason = True, "No relevant sources were found in the knowledge base"
        # A failed model or search call is reported as such, not as a judgement on the sources.
        failure = next(
            (f for f in findings if f.rule_id in {"MODEL-ERROR", "RETRIEVAL-ERROR"}), None
        )
        if failure:
            abstained, reason = True, failure.message

        return VerifiedAnswer(
            question=question,
            environment=env.summary(),
            summary=draft.summary,
            claims=verdicts,
            differential=draft.differential,
            actions=action_verdicts,
            calc_results=[c.model_dump() for c in calc_results],
            findings=findings,
            passages=passages,
            uncertainty=draft.uncertainty,
            abstained=abstained,
            abstain_reason=reason,
            missing_info=draft.missing_info,
            draft=draft,
        )
