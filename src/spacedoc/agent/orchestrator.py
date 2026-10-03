"""The orchestrator (component C-02): retrieve -> draft -> calculators -> verify.

Phase 1 uses one model pass with structured fields instead of free-form native tool calling;
calculators run in code and their results are linked to the actions. It is less flexible, but
every step is deterministic, logged and checkable.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from pydantic import ValidationError

from spacedoc.agent import prompts
from spacedoc.answer.schema import (
    DraftAnswer,
    Finding,
    Passage,
    VerifiedAnswer,
    draft_json_schema,
)
from spacedoc.audit.log import AuditLog
from spacedoc.env.context import EnvironmentContext
from spacedoc.kb.retrieve import Retriever
from spacedoc.llm.client import LLM, GenParams, LLMError, estimate_tokens
from spacedoc.tools.calculators import CalcError, CalcResult, describe_calculators, run_calculator
from spacedoc.tools.formulary import Formulary
from spacedoc.verify.pipeline import Verifier
from spacedoc.verify.rules import screen_passage

# Summaries SpaceDoc writes itself when it cannot answer. They are not model output, so the
# verifier does not check them against the answer.
NO_SEARCH = "SpaceDoc could not search its sources, so it cannot answer."
NO_MODEL = "SpaceDoc could not get an answer from the language model."
NO_ANSWER = "SpaceDoc could not produce a well-formed answer."
SYSTEM_SUMMARIES = {NO_SEARCH, NO_MODEL, NO_ANSWER}


@dataclass(frozen=True)
class GenerationPlan:
    """Generation settings for each pass. Built from spacedoc.toml in system.py.

    The defaults (temperature 0, no context limit) suit the scripted FakeLLM in tests.
    """

    draft: GenParams = field(default_factory=GenParams)


class Orchestrator:
    def __init__(
        self,
        llm: LLM,
        retriever: Retriever,
        verifier: Verifier,
        formulary: Formulary,
        audit: AuditLog | None = None,
        top_k: int = 6,
        consistency_samples: int = 1,
        model_name: str = "unknown",
        generation: GenerationPlan | None = None,
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self.verifier = verifier
        self.formulary = formulary
        self.audit = audit
        self.top_k = top_k
        self.consistency_samples = consistency_samples
        self.model_name = model_name
        self.generation = generation or GenerationPlan()
        self.schema = draft_json_schema()
        self._stats: dict[str, float] = {}
        self._findings: list[Finding] = []
        self._traces: list[dict[str, Any]] = []

    def _messages(
        self,
        question: str,
        env: EnvironmentContext,
        patient: dict[str, Any] | None,
        passages: list[Passage],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": prompts.system_message(
                    env, self.formulary.prompt_summary(), describe_calculators()
                ),
            },
            {"role": "user", "content": prompts.user_message(question, passages, patient)},
        ]

    def _fit_context(
        self,
        question: str,
        env: EnvironmentContext,
        patient: dict[str, Any] | None,
        passages: list[Passage],
    ) -> tuple[list[dict[str, str]], list[Passage]]:
        """Drop the lowest-ranked passages until the prompt fits the context window.

        Without this the server would cut the prompt silently, losing the system rules or the
        sources. Dropping whole passages keeps what the model sees and what is verified equal.
        """
        p = self.generation.draft
        messages = self._messages(question, env, patient, passages)
        if not p.num_ctx:
            return messages, passages
        dropped: list[Passage] = []
        while passages and estimate_tokens(messages) + (p.max_tokens or 0) > p.num_ctx:
            dropped.append(passages[-1])
            passages = passages[:-1]
            messages = self._messages(question, env, patient, passages)
        if dropped:
            self._findings.append(
                Finding(
                    rule_id="CONTEXT-TRIM",
                    severity="warn",
                    target="answer",
                    message=f"Left out {len(dropped)} lower-ranked source passage(s) to fit the "
                    f"model's context window ({p.num_ctx} tokens)",
                )
            )
        return messages, passages

    def _draft(
        self, messages: list[dict[str, str]], params: GenParams, label: str
    ) -> DraftAnswer | None:
        """Ask for a DraftAnswer; on invalid JSON, retry once with the error message.

        Raises LLMError if the model server fails; ask() turns that into an abstention.
        """
        for attempt in range(2):
            result = self.llm.chat(messages, schema=self.schema, params=params)
            text = result.text
            self._stats["llm_calls"] += 1
            self._stats["llm_s"] += result.seconds
            self._stats["completion_tokens"] += result.completion_tokens or 0
            self._stats["prompt_tokens"] += result.prompt_tokens or 0
            if result.thinking:
                self._traces.append(
                    {"pass": label, "attempt": attempt + 1, "thinking": result.thinking}
                )
            cut_off = result.done_reason == "length"
            if cut_off:
                self._findings.append(
                    Finding(
                        rule_id="OUTPUT-LIMIT",
                        severity="warn",
                        target="answer",
                        message=f"The {label} reply reached its length limit "
                        f"({params.max_tokens} tokens) and was cut off",
                    )
                )
            try:
                return DraftAnswer.model_validate_json(text)
            except ValidationError as e:
                self._stats["parse_failures"] += 1
                if attempt == 0:
                    if cut_off:
                        # Don't send the truncated text back; it only uses up the window.
                        retry = (
                            "Your previous reply was cut off at the length limit. Reply again "
                            "with shorter valid JSON: fewer and shorter claims."
                        )
                        messages = messages + [{"role": "user", "content": retry}]
                    else:
                        messages = messages + [
                            {"role": "assistant", "content": text},
                            {
                                "role": "user",
                                "content": f"That was not valid JSON for the schema: {e}. "
                                "Reply again with valid JSON only.",
                            },
                        ]
        return None

    def ask(
        self,
        question: str,
        env: EnvironmentContext,
        patient: dict[str, Any] | None = None,
        role: str = "cmo",
    ) -> VerifiedAnswer:
        t0 = time.perf_counter()
        self._stats = {
            "llm_calls": 0,
            "llm_s": 0.0,
            "completion_tokens": 0,
            "prompt_tokens": 0,
            "parse_failures": 0,
        }
        self._findings = []
        self._traces = []
        timings: dict[str, float] = {}
        extra = self._findings
        calc_results: list[CalcResult] = []

        try:
            passages = self.retriever.search(question, env, self.top_k)
        except LLMError as e:
            passages = None
            extra.append(
                Finding(
                    rule_id="RETRIEVAL-ERROR",
                    severity="block",
                    target="answer",
                    message=f"Source search failed: {e}",
                )
            )
        timings["retrieve_s"] = time.perf_counter() - t0

        if passages is None:
            passages = []
            draft = DraftAnswer(
                summary=NO_SEARCH,
                uncertainty="high",
                abstain=True,
                missing_info=["The knowledge-base search failed (see findings)"],
            )
        else:
            clean = []
            for p in passages:
                if f := screen_passage(p):
                    extra.append(f)
                else:
                    clean.append(p)
            # Renumber so the model sees S1..Sn without gaps from excluded passages.
            passages = [p.model_copy(update={"cid": f"S{i + 1}"}) for i, p in enumerate(clean)]
            messages, passages = self._fit_context(question, env, patient, passages)
            try:
                draft, calc_results = self._model_passes(messages, patient, timings)
            except LLMError as e:
                calc_results = []
                extra.append(
                    Finding(
                        rule_id="MODEL-ERROR",
                        severity="block",
                        target="answer",
                        message=str(e),
                    )
                )
                draft = DraftAnswer(
                    summary=NO_MODEL,
                    uncertainty="high",
                    abstain=True,
                    missing_info=["The language model failed (see findings)"],
                )

        t3 = time.perf_counter()
        verified = self.verifier.verify(
            question,
            draft,
            passages,
            calc_results,
            env,
            patient,
            extra,
            check_summary=draft.summary not in SYSTEM_SUMMARIES,
        )
        timings["verify_s"] = time.perf_counter() - t3
        timings["total_s"] = time.perf_counter() - t0
        timings.update(self._stats)
        if self._stats["llm_s"] > 0 and self._stats["completion_tokens"]:
            timings["tokens_per_s"] = self._stats["completion_tokens"] / self._stats["llm_s"]
        verified.timings = {k: round(v, 3) for k, v in timings.items()}
        if any(f.rule_id == "CONSISTENCY-LOW" for f in extra):
            verified.uncertainty = "high"
        verified.reasoning_available = bool(self._traces) and self.audit is not None

        if self.audit:
            verified.audit_id = self.audit.append(
                "ask",
                {
                    "question": question,
                    "role": role,
                    "environment": env.model_dump(),
                    "model": self.model_name,
                    "checker": getattr(self.verifier.checker, "name", "?"),
                    "prompt_version": prompts.PROMPT_VERSION,
                    "generation": {"draft": asdict(self.generation.draft)},
                    "passages": [p.chunk_id for p in passages],
                    "draft": draft.model_dump(),
                    "calc_results": [c.model_dump() for c in calc_results],
                    "verdicts": [
                        {"claim": v.claim.id, "status": v.status, "shown": v.shown}
                        for v in verified.claims
                    ],
                    "actions": [
                        {"action": a.action.id, "status": a.status} for a in verified.actions
                    ],
                    "findings": [f.model_dump() for f in verified.findings],
                    "abstained": verified.abstained,
                    "timings": verified.timings,
                    # The model's private notes, kept for clinical review. Unverified.
                    "thinking": self._traces,
                },
            )
        return verified

    def _model_passes(
        self,
        messages: list[dict[str, str]],
        patient: dict[str, Any] | None,
        timings: dict[str, float],
    ) -> tuple[DraftAnswer, list[CalcResult]]:
        """Draft, run calculators in code, and (optionally) resample.

        There is no second model pass: doses are linked to calculator results in code, which is
        faster and keeps every number out of the model's hands.
        """
        extra = self._findings
        t1 = time.perf_counter()
        draft = self._draft(messages, self.generation.draft, "draft")
        timings["draft_s"] = time.perf_counter() - t1

        if draft is None:
            draft = DraftAnswer(
                summary=NO_ANSWER,
                uncertainty="high",
                abstain=True,
                missing_info=["The language model returned invalid output twice"],
            )

        calc_results: list[CalcResult] = []
        if not draft.abstain:
            for req in draft.calc_requests:
                self._run_calc(req.calculator, req.args, patient, calc_results)
            self._link_doses(draft, patient, calc_results)

        if self.consistency_samples > 1 and not draft.abstain and draft.differential:
            extra += self._consistency(messages, draft)
        return draft, calc_results

    def _run_calc(
        self,
        name: str,
        args: dict[str, Any],
        patient: dict[str, Any] | None,
        results: list[CalcResult],
    ) -> CalcResult | None:
        try:
            r = run_calculator(name, args, self.formulary, patient)
        except (CalcError, TypeError) as e:
            what = f"a dose of {args['drug']}" if "drug" in args else name.replace("_", " ")
            self._findings.append(
                Finding(
                    rule_id="CALC-ERROR",
                    severity="warn",
                    target="answer",
                    message=f"SpaceDoc could not calculate {what}: {e}",
                )
            )
            return None
        if r.calc_id not in {c.calc_id for c in results}:
            results.append(r)
        return r

    def _link_doses(
        self, draft: DraftAnswer, patient: dict[str, Any] | None, results: list[CalcResult]
    ) -> None:
        """Give every dosed action a calculator result (weight always from the record).

        A medication action naming a formulary item with dosing data gets the weight-based
        dose; a maintenance-fluid action gets the maintenance-fluid rate. The verifier then
        checks every number in the action against the linked result.
        """
        known = {c.calc_id for c in results}
        for action in draft.actions:
            if action.calc_ref in known:
                continue
            action.calc_ref = None
            if "maintenance fluid" in action.text.lower():
                calc = next(
                    (c for c in results if c.calculator == "maintenance_fluids_421"), None
                ) or self._run_calc("maintenance_fluids_421", {}, patient, results)
            elif action.kind == "medication" and action.item:
                item = self.formulary.find(action.item)
                if item is None or item.dosing is None:
                    continue
                calc = next(
                    (
                        c
                        for c in results
                        if c.calculator == "weight_based_dose" and c.inputs.get("drug") == item.id
                    ),
                    None,
                ) or self._run_calc("weight_based_dose", {"drug": item.id}, patient, results)
            else:
                continue
            if calc:
                action.calc_ref = calc.calc_id
                known.add(calc.calc_id)

    def _consistency(self, messages, draft: DraftAnswer) -> list[Finding]:
        """Self-consistency (layer L5): resample and check the leading diagnosis agrees."""
        base = self.generation.draft
        tops = [draft.differential[0].condition.strip().lower()]
        for i in range(self.consistency_samples - 1):
            # A different seed per sample; a fixed seed would repeat the same answer.
            params = replace(
                base,
                temperature=base.temperature or 0.7,
                seed=(base.seed or 0) + i + 1,
            )
            d = self._draft(messages, params, f"consistency sample {i + 1}")
            if d and d.differential:
                tops.append(d.differential[0].condition.strip().lower())
        agree = Counter(tops)[tops[0]] / len(tops)
        if agree < 0.6:
            return [
                Finding(
                    rule_id="CONSISTENCY-LOW",
                    severity="warn",
                    target="answer",
                    message=f"Leading diagnosis agreed in only {agree:.0%} of {len(tops)} samples",
                )
            ]
        return [
            Finding(
                rule_id="CONSISTENCY",
                severity="info",
                target="answer",
                message=f"Leading diagnosis agreed in {agree:.0%} of {len(tops)} samples",
            )
        ]
