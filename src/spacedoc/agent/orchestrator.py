"""The orchestrator (component C-02): retrieve -> draft -> calculators -> finalize -> verify.

Phase 1 uses a fixed two-pass loop with structured fields instead of free-form native tool
calling. It is less flexible, but every step is deterministic, logged and checkable.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from pydantic import ValidationError

from spacedoc.agent import prompts
from spacedoc.answer.schema import DraftAnswer, Finding, VerifiedAnswer, draft_json_schema
from spacedoc.audit.log import AuditLog
from spacedoc.env.context import EnvironmentContext
from spacedoc.kb.retrieve import Retriever
from spacedoc.llm.client import LLM
from spacedoc.tools.calculators import CalcError, CalcResult, describe_calculators, run_calculator
from spacedoc.tools.formulary import Formulary
from spacedoc.verify.pipeline import Verifier
from spacedoc.verify.rules import screen_passage


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
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self.verifier = verifier
        self.formulary = formulary
        self.audit = audit
        self.top_k = top_k
        self.consistency_samples = consistency_samples
        self.model_name = model_name
        self.schema = draft_json_schema()
        self._stats: dict[str, float] = {}

    def _draft(
        self, messages: list[dict[str, str]], temperature: float = 0.0
    ) -> DraftAnswer | None:
        """Ask for a DraftAnswer; on invalid JSON, retry once with the error message."""
        for attempt in range(2):
            result = self.llm.chat(messages, schema=self.schema, temperature=temperature)
            text = result.text
            self._stats["llm_calls"] += 1
            self._stats["llm_s"] += result.seconds
            self._stats["completion_tokens"] += result.completion_tokens or 0
            try:
                return DraftAnswer.model_validate_json(text)
            except ValidationError as e:
                self._stats["parse_failures"] += 1
                if attempt == 0:
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
        self._stats = {"llm_calls": 0, "llm_s": 0.0, "completion_tokens": 0, "parse_failures": 0}
        timings: dict[str, float] = {}
        extra: list[Finding] = []

        passages = self.retriever.search(question, env, self.top_k)
        clean = []
        for p in passages:
            if f := screen_passage(p):
                extra.append(f)
            else:
                clean.append(p)
        # Renumber so the model sees S1..Sn without gaps from excluded passages.
        passages = [p.model_copy(update={"cid": f"S{i + 1}"}) for i, p in enumerate(clean)]
        timings["retrieve_s"] = time.perf_counter() - t0

        messages = [
            {
                "role": "system",
                "content": prompts.system_message(
                    env, self.formulary.prompt_summary(), describe_calculators()
                ),
            },
            {"role": "user", "content": prompts.user_message(question, passages, patient)},
        ]
        t1 = time.perf_counter()
        draft = self._draft(messages)
        timings["draft_s"] = time.perf_counter() - t1

        if draft is None:
            draft = DraftAnswer(
                summary="SpaceDoc could not produce a well-formed answer.",
                uncertainty="high",
                abstain=True,
                missing_info=["The language model returned invalid output twice"],
            )

        calc_results: list[CalcResult] = []
        if draft.calc_requests and not draft.abstain:
            lines = []
            for req in draft.calc_requests:
                try:
                    r = run_calculator(req.calculator, req.args, self.formulary, patient)
                    calc_results.append(r)
                    warn = f" (warnings: {'; '.join(r.warnings)})" if r.warnings else ""
                    lines.append(f"- {r.calc_id}: {r.text}{warn}")
                except (CalcError, TypeError) as e:
                    lines.append(f"- {req.calculator} FAILED: {e}")
                    extra.append(
                        Finding(
                            rule_id="CALC-ERROR",
                            severity="warn",
                            target="answer",
                            message=f"{req.calculator}: {e}",
                        )
                    )
            t2 = time.perf_counter()
            final = self._draft(
                messages
                + [
                    {"role": "assistant", "content": draft.model_dump_json()},
                    {"role": "user", "content": prompts.FINALIZE.format(results="\n".join(lines))},
                ]
            )
            timings["finalize_s"] = time.perf_counter() - t2
            if final is not None:
                final.calc_requests = []
                draft = final

        if self.consistency_samples > 1 and not draft.abstain and draft.differential:
            extra += self._consistency(messages, draft)

        t3 = time.perf_counter()
        verified = self.verifier.verify(
            question, draft, passages, calc_results, env, patient, extra
        )
        timings["verify_s"] = time.perf_counter() - t3
        timings["total_s"] = time.perf_counter() - t0
        timings.update(self._stats)
        if self._stats["llm_s"] > 0 and self._stats["completion_tokens"]:
            timings["tokens_per_s"] = self._stats["completion_tokens"] / self._stats["llm_s"]
        verified.timings = {k: round(v, 3) for k, v in timings.items()}
        if any(f.rule_id == "CONSISTENCY-LOW" for f in extra):
            verified.uncertainty = "high"

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
                },
            )
        return verified

    def _consistency(self, messages, draft: DraftAnswer) -> list[Finding]:
        """Self-consistency (layer L5): resample and check the leading diagnosis agrees."""
        tops = [draft.differential[0].condition.strip().lower()]
        for _ in range(self.consistency_samples - 1):
            d = self._draft(messages, temperature=0.7)
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
