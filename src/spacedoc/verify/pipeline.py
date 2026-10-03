"""The verification pipeline (component C-11): turns a draft into a verified answer.

Order: citation validity -> numbers (L3/L6) -> grounding (L4) -> formulary, equipment and
environment rules (L6) -> risk gating (L7) -> abstention decision -> summary check.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from spacedoc.answer.schema import (
    Action,
    ActionVerdict,
    Claim,
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

# Shown in place of a model summary that failed its check.
SUMMARY_REMOVED = (
    "The model's summary is not shown: the checker could not confirm it against the answer "
    'below (details under "Why this answer").'
)
SUMMARY_ABSTAINED = "SpaceDoc cannot answer this reliably."


def _verdict_note(label: str, v: GroundingVerdict) -> str:
    if v.raw == "could not be checked":
        return f"{label} could not be checked"
    return f"{label} {'supports' if v.supported else 'does not support'} this (checker: {v.raw})"


def _check_error_message(e: Exception) -> str:
    msg = f"The source checker could not run ({e}), so statements that needed checking are hidden."
    if m := re.search(r"model '([^']+)' not found", str(e)):
        msg += f" The checker model is not installed. Install it with: ollama pull {m.group(1)}"
    return msg


def _next_steps(
    env: EnvironmentContext,
    abstained: bool,
    reason: str | None,
    draft: DraftAnswer,
    actions: list[ActionVerdict],
) -> list[str]:
    """What to do now. Built by code from checked content, so it is present even when SpaceDoc
    cannot give a full answer."""
    steps = []
    if abstained:
        steps.append(
            f"SpaceDoc could not give a full, checked answer ({reason}). Treat what is shown as "
            "incomplete and rely on the CMO's judgement and onboard procedures."
        )
    if env.link_available and (
        abstained or any(a.action.risk_tier in {"R3", "R4"} for a in actions)
    ):
        steps.append(f"Contact the ground medical team (one-way delay {env.delay_text()}).")
    ready = [a for a in actions if a.status != "blocked"]
    if ready:
        steps.append(
            "Actions that passed SpaceDoc's checks are listed under Actions; those marked CONFIRM "
            "need the CMO's confirmation first."
        )
    if draft.missing_info:
        steps.append("Find out: " + "; ".join(draft.missing_info) + ".")
    steps.append("Recheck vital signs and symptoms, and ask SpaceDoc again if anything changes.")
    return steps


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
                        message=_check_error_message(e),
                    )
                )
            return GroundingVerdict(False, "could not be checked")

    def _as_patient_claim(
        self, claim: Claim, ptext: str, precord: str, findings: list[Finding]
    ) -> ClaimVerdict | None:
        if not rules.numbers_in(claim.text) <= rules.numbers_in(ptext):
            return None
        supported, detail = self._ground(claim.text, {"record": precord}, findings)
        if not supported:
            return None
        return ClaimVerdict(
            claim=claim.model_copy(update={"kind": "patient", "citations": []}),
            status="supported",
            shown=True,
            detail="This describes the patient, not a source: the model filed it as sourced, "
            f"but the patient record and what was reported support it ({detail}).",
        )

    def _check_dose(self, action: Action, calcs: dict[str, CalcResult]) -> list[Finding]:
        """A medication must carry a checked dose: a calculator result for a dosed formulary
        item, or a clinician's dose for items the formulary has no dosing data for."""
        if action.kind != "medication" or not action.item or action.calc_ref in calcs:
            return []
        item = self.formulary.find(action.item)
        if item is None:
            return []  # FORM-UNLINKED covers it
        why = (
            "SpaceDoc could not calculate a dose (see the CALC-ERROR note)"
            if item.dosing
            else f"the formulary has no dosing data for {item.name}"
        )
        return [
            Finding(
                rule_id="NO-DOSE",
                severity="block",
                target=action.id,
                message=f"No checked dose: {why}. Not ready to give until a clinician sets "
                "the dose.",
            )
        ]

    def _ground(
        self, claim: str, docs: dict[str, str], findings: list[Finding]
    ) -> tuple[bool, str]:
        """Is every sentence of the claim supported by one of `docs` (label -> text)?

        MiniCheck checks one sentence at a time, so multi-sentence claims are split. Each
        sentence is checked against each document; if none supports it alone and there are
        several, it is checked against up to three of them together (a claim may combine facts
        from two passages).
        """
        notes = []
        for sentence in split_sentences(claim) or [claim]:
            ok = False
            for label, doc in docs.items():
                v = self._check(sentence, doc, label, findings)
                notes.append(_verdict_note(label, v))
                if v.supported:
                    ok = True
                    break
            if not ok and len(docs) >= 2:
                group = list(docs)[:3]
                label = "+".join(group)
                v = self._check(sentence, "\n\n".join(docs[g] for g in group), label, findings)
                notes.append(_verdict_note(f"{label} together", v))
                ok = v.supported
            if not ok:
                return False, "; ".join(notes)
        return True, "; ".join(notes)

    def _check_summary(
        self,
        summary: str,
        evidence: str,
        abstained: bool,
        findings: list[Finding],
    ) -> str:
        """The summary is read first, so it must not say more than the checked answer below it.

        Each sentence needs its numbers in `evidence` and must be supported by it. Unsupported
        sentences are dropped; if none remain, a neutral sentence replaces the summary.
        """
        allowed = rules.numbers_in(evidence)
        kept, dropped = [], []
        for sentence in split_sentences(summary) or [summary]:
            untraced = rules.numbers_in(sentence) - allowed
            if untraced:
                dropped.append(f'"{sentence}" (number(s) {", ".join(sorted(untraced))} untraced)')
            elif not evidence.strip():
                dropped.append(f'"{sentence}" (nothing checked to support it)')
            elif self._check(sentence, evidence, "summary", findings).supported:
                kept.append(sentence)
            else:
                dropped.append(f'"{sentence}" (not supported by the checked answer)')
        if not dropped:
            return summary
        if kept:
            findings.append(
                Finding(
                    rule_id="SUMMARY-TRIMMED",
                    severity="warn",
                    target="answer",
                    message="Removed from the summary: " + "; ".join(dropped),
                )
            )
            return " ".join(kept)
        findings.append(
            Finding(
                rule_id="SUMMARY-REPLACED",
                severity="warn",
                target="answer",
                message="The model's summary was not shown: " + "; ".join(dropped),
            )
        )
        return SUMMARY_ABSTAINED if abstained else SUMMARY_REMOVED

    def verify(
        self,
        question: str,
        draft: DraftAnswer,
        passages: list[Passage],
        calc_results: list[CalcResult],
        env: EnvironmentContext,
        patient: dict[str, Any] | None = None,
        extra_findings: list[Finding] | None = None,
        check_summary: bool = True,
    ) -> VerifiedAnswer:
        """`check_summary=False` is for summaries SpaceDoc writes itself (failure messages)."""
        by_cid = {p.cid: p for p in passages}
        calcs = {c.calc_id: c for c in calc_results}
        ptext = rules.patient_text(patient)
        precord = rules.patient_document(patient)
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
            verdict: ClaimVerdict | None = None
            if num and claim.kind != "sourced":
                findings.append(num)
                verdicts.append(
                    ClaimVerdict(claim=claim, status="removed", shown=False, detail=num.message)
                )
                continue

            if claim.kind == "reasoning":
                verdict = ClaimVerdict(
                    claim=claim,
                    status="reasoning",
                    shown=True,
                    detail="Model reasoning, not taken from a source",
                )
            elif claim.kind == "patient":
                if patient:
                    supported, detail = self._ground(claim.text, {"record": precord}, findings)
                    detail = f"Checked against the patient record and what was reported: {detail}"
                else:
                    supported, detail = False, "No patient record was provided"
                verdict = ClaimVerdict(
                    claim=claim,
                    status="supported" if supported else "unsupported",
                    shown=supported,
                    detail=detail,
                )
            elif num:
                verdict = ClaimVerdict(
                    claim=claim, status="removed", shown=False, detail=num.message
                )
            elif not valid_cites:
                verdict = ClaimVerdict(
                    claim=claim,
                    status="unsupported",
                    shown=False,
                    detail="The model did not name a source for this statement, so it is "
                    "not shown. SpaceDoc only shows statements it can check against a source.",
                )
            else:
                docs = {cid: by_cid[cid].text for cid in valid_cites}
                supported, detail = self._ground(claim.text, docs, findings)
                verdict = ClaimVerdict(
                    claim=claim,
                    status="supported" if supported else "unsupported",
                    shown=supported,
                    detail=detail,
                    checked_against=valid_cites,
                )
            if claim.kind == "sourced" and not verdict.shown and patient:
                # Models often file what the user reported ("the cut is 1/2 inch deep") as a
                # sourced fact. If the record or the report supports it, show it as a patient
                # statement instead of counting it against the sources.
                verdict = self._as_patient_claim(claim, ptext, precord, findings) or verdict
            if verdict.status == "removed" and num:
                findings.append(num)
            verdicts.append(verdict)

            for f in rules.check_feasibility(
                claim.id, claim.text, env, self.feasibility, is_action=False
            ):
                findings.append(f)

        action_verdicts: list[ActionVerdict] = []
        for action in draft.actions:
            act_findings: list[Finding] = []
            if n := rules.check_action_numbers(action, calcs, self.formulary, patient):
                act_findings.append(n)
            act_findings += self._check_dose(action, calcs)
            act_findings += rules.check_allergies(action, self.formulary, patient)
            if action.calc_ref and action.calc_ref not in calcs:
                act_findings.append(
                    Finding(
                        rule_id="CALC-MISSING",
                        severity="block",
                        target=action.id,
                        message=f"This action refers to a calculator result "
                        f"({action.calc_ref}) that does not exist, so its numbers cannot be "
                        "trusted.",
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
                    display_text=rules.action_display_text(action, calcs, self.formulary, patient),
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
        check_error = next((f for f in findings if f.rule_id == "CHECK-ERROR"), None)
        if abstained and check_error and sourced and not supported:
            reason = "SpaceDoc's source checker could not run, so no statement could be confirmed"

        summary = draft.summary
        if check_summary:
            # What the crew sees below the summary: shown claims, the differential (hidden when
            # abstaining), actions that are not blocked, and the patient record.
            evidence = [v.claim.text for v in verdicts if v.shown]
            if not abstained:
                evidence += [
                    f"{d.condition}: {d.likelihood} likelihood." for d in draft.differential
                ]
            evidence += [a.action.text for a in action_verdicts if a.status != "blocked"]
            if patient:
                evidence.append(f"Patient record:\n{precord}")
            summary = self._check_summary(summary, "\n".join(evidence), abstained, findings)

        next_steps = _next_steps(env, abstained, reason, draft, action_verdicts)
        return VerifiedAnswer(
            question=question,
            environment=env.summary(),
            summary=summary,
            claims=verdicts,
            differential=draft.differential,
            actions=action_verdicts,
            calc_results=[c.model_dump() for c in calc_results],
            findings=findings,
            passages=passages,
            # An answer SpaceDoc could not give reliably is never "low" uncertainty.
            uncertainty="high" if abstained else draft.uncertainty,
            abstained=abstained,
            abstain_reason=reason,
            missing_info=draft.missing_info,
            draft=draft,
            next_steps=next_steps,
            patient_summary=rules.record_summary(patient),
        )
