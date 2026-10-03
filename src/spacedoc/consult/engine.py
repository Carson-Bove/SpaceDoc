"""The consult engine: identification, fast question turns, then a checked assessment.

Question turns use one short model call (thinking off unless deep log is on), no source
search and no grounding checker, so they stay fast. The assessment runs the full Phase 1
pipeline on a summary of the consult. See docs/consult-mode-design.md.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from spacedoc.agent.orchestrator import Orchestrator
from spacedoc.answer.schema import VerifiedAnswer
from spacedoc.audit.log import AuditLog
from spacedoc.consult import prompts
from spacedoc.consult.redflags import RedFlagHit, RedFlags, format_delay
from spacedoc.consult.roster import CrewMember
from spacedoc.consult.schema import ExamRequest, TurnReply
from spacedoc.env.context import EnvironmentContext
from spacedoc.llm.client import LLM, ChatResult, GenParams, LLMError
from spacedoc.verify.rules import FeasibilityRule, check_feasibility

SELF = "self"
UNLISTED = "unlisted"


@dataclass
class TurnTiming:
    total_s: float
    load_s: float | None = None  # loading the model (cold start)
    prompt_s: float | None = None  # reading the prompt
    gen_s: float | None = None  # writing the reply (thinking included)
    tokens: int | None = None
    deep_log: bool = False
    # Deep log only: estimated time had thinking been off (writing time minus the share of
    # the reply that was thinking notes). None when the server reports no durations.
    without_deep_log_s: float | None = None


@dataclass
class ExamCheck:
    request: ExamRequest
    missing: list[str] = field(default_factory=list)  # equipment not aboard
    findings: list[str] = field(default_factory=list)  # environment feasibility rules

    @property
    def ok(self) -> bool:
        return not self.missing and not self.findings


@dataclass
class Turn:
    n: int
    user_text: str
    red_flags: list[RedFlagHit] = field(default_factory=list)
    red_flags_dismissed: bool = False
    reply: TurnReply | None = None
    exam_checks: list[ExamCheck] = field(default_factory=list)
    timing: TurnTiming | None = None
    thinking: str = ""
    error: str | None = None
    audit_id: str | None = None

    @property
    def paused(self) -> bool:
        """Stopped by a red flag; the model has not seen this message yet."""
        return bool(self.red_flags) and not self.red_flags_dismissed and self.reply is None


@dataclass
class Consult:
    consult_id: str
    user: CrewMember
    patient: CrewMember | None  # None: not on the roster
    patient_is_user: bool
    env: EnvironmentContext
    practice: bool
    scenario_id: str | None
    deep_log: bool
    started_at: str
    messages: list[dict[str, str]]
    turns: list[Turn] = field(default_factory=list)
    assessments: list[VerifiedAnswer] = field(default_factory=list)

    @property
    def patient_label(self) -> str:
        if self.patient is None:
            return "a person not on the roster"
        return f"{self.patient.crew_id} ({self.patient.role})"

    @property
    def last_reply(self) -> TurnReply | None:
        return next((t.reply for t in reversed(self.turns) if t.reply), None)

    @property
    def rounds(self) -> int:
        return sum(1 for t in self.turns if t.reply)

    def delay(self) -> str:
        if not self.env.link_available:
            return "no link"
        return format_delay(self.env.one_way_delay_s)


class ConsultEngine:
    def __init__(
        self,
        llm: LLM,
        orchestrator: Orchestrator,
        audit: AuditLog | None,
        roster: dict[str, CrewMember],
        red_flags: RedFlags,
        feasibility: list[FeasibilityRule],
        params: GenParams,
        deep_params: GenParams,
        model_name: str,
        max_rounds: int = 8,
        max_questions: int = 2,
    ) -> None:
        self.llm = llm
        self.orchestrator = orchestrator
        self.audit = audit
        self.roster = roster
        self.red_flags = red_flags
        self.feasibility = feasibility
        self.params = params
        self.deep_params = deep_params
        self.model_name = model_name
        self.max_rounds = max_rounds
        self.max_questions = max_questions
        self.schema = TurnReply.model_json_schema()

    # ---- start -----------------------------------------------------------------------

    def member(self, crew_id: str) -> CrewMember:
        try:
            return self.roster[crew_id.upper()]
        except KeyError:
            known = ", ".join(self.roster)
            raise ValueError(f"Unknown crew ID {crew_id!r}; the roster has {known}") from None

    def start(
        self,
        user_id: str,
        patient_id: str,
        env: EnvironmentContext,
        practice: bool = False,
        scenario_id: str | None = None,
        deep_log: bool = False,
    ) -> Consult:
        """`patient_id` is a crew ID, "self", or "unlisted"."""
        user = self.member(user_id)
        if patient_id.lower() == SELF or patient_id.upper() == user.crew_id:
            patient, is_user = user, True
        elif patient_id.lower() == UNLISTED:
            patient, is_user = None, False
        else:
            patient, is_user = self.member(patient_id), False
        system = prompts.system_message(user, patient, is_user, env)
        payload = {
            "user": user.crew_id,
            "user_role": user.medical_role,
            "patient": patient.crew_id if patient else UNLISTED,
            "practice": practice,
            "scenario_id": scenario_id if practice else None,
            "deep_log": deep_log,
            "environment": env.model_dump(),
            "model": self.model_name,
            "prompt_version": prompts.CONSULT_PROMPT_VERSION,
        }
        consult_id = (
            self.audit.append("consult_start", payload)
            if self.audit
            else f"consult-{uuid.uuid4().hex[:8]}"
        )
        return Consult(
            consult_id=consult_id,
            user=user,
            patient=patient,
            patient_is_user=is_user,
            env=env,
            practice=practice,
            scenario_id=scenario_id if practice else None,
            deep_log=deep_log,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            messages=[{"role": "system", "content": system}],
        )

    # ---- question turns ----------------------------------------------------------------

    def turn(self, consult: Consult, text: str) -> Turn:
        """Screen the message for red flags, then (if none) ask the model for the next step."""
        turn = Turn(n=len(consult.turns) + 1, user_text=text.strip())
        turn.red_flags = self.red_flags.screen(turn.user_text, consult.delay())
        consult.turns.append(turn)
        if turn.paused:
            turn.timing = TurnTiming(total_s=0.0)
            self._log(consult, turn)
            return turn
        return self._ask_model(consult, turn)

    def resume(self, consult: Consult) -> Turn:
        """Continue after the user judged a red flag not to be an emergency."""
        turn = consult.turns[-1]
        if not turn.paused:
            raise ValueError("The last turn is not waiting on a red flag")
        turn.red_flags_dismissed = True
        return self._ask_model(consult, turn)

    def _ask_model(self, consult: Consult, turn: Turn) -> Turn:
        messages = consult.messages + [{"role": "user", "content": turn.user_text}]
        params = self.deep_params if consult.deep_log else self.params
        results: list[ChatResult] = []
        start = time.perf_counter()
        for attempt in range(2):
            p = params if attempt == 0 else replace(params, seed=(params.seed or 0) + 1)
            try:
                result = self.llm.chat(messages, schema=self.schema, params=p)
            except LLMError as e:
                turn.error = str(e)
                break
            results.append(result)
            try:
                turn.reply = TurnReply.model_validate_json(result.text)
                break
            except ValidationError:
                continue
        elapsed = time.perf_counter() - start
        if turn.reply is None and turn.error is None:
            turn.error = "The model did not return a valid reply (two attempts)."
        if turn.reply:
            turn.reply.questions = turn.reply.questions[: self.max_questions]
            turn.exam_checks = [self._check_exam(e, consult.env) for e in turn.reply.exam_requests]
            if consult.deep_log:
                turn.thinking = "\n\n".join(r.thinking for r in results if r.thinking)
            # Send back exactly what the model wrote, so Ollama can reuse its cache.
            consult.messages = messages + [{"role": "assistant", "content": results[-1].text}]
        else:
            consult.turns.remove(turn)  # the model never answered it; the user can retry
        turn.timing = _timing(results, elapsed, consult.deep_log)
        self._log(consult, turn)
        return turn

    def _check_exam(self, request: ExamRequest, env: EnvironmentContext) -> ExamCheck:
        aboard = {e.lower() for e in env.equipment}
        missing = [e for e in request.equipment if e.lower() not in aboard]
        findings = [
            f.message for f in check_feasibility("exam", request.text, env, self.feasibility, True)
        ]
        return ExamCheck(request=request, missing=missing, findings=findings)

    def should_assess(self, consult: Consult) -> str | None:
        """Why SpaceDoc should assess now, or None to keep asking."""
        reply = consult.last_reply
        if reply is None:
            return None
        if reply.ready_to_assess:
            return "SpaceDoc has enough information to assess."
        if consult.rounds >= self.max_rounds:
            return f"SpaceDoc has asked {self.max_rounds} rounds of questions."
        if not reply.questions and not reply.exam_requests:
            return "SpaceDoc has no further questions."
        return None

    # ---- assessment ----------------------------------------------------------------------

    def case_summary(self, consult: Consult) -> str:
        user = consult.user
        lines = [
            f"Consult about {consult.patient_label}, reported by {user.crew_id} ({user.role}).",
        ]
        if not consult.turns:
            return lines[0]
        lines.append(
            f'Presenting problem, in {user.crew_id}\'s words: "{consult.turns[0].user_text}"'
        )
        follow = []
        for prev, cur in zip(consult.turns, consult.turns[1:], strict=False):
            asked = []
            if prev.reply:
                asked += [q.text for q in prev.reply.questions]
                asked += [e.request.text for e in prev.exam_checks]
            if asked:
                follow.append(f'- SpaceDoc asked: {" / ".join(asked)}\n  Answer: "{cur.user_text}"')
            else:
                follow.append(f'- Added: "{cur.user_text}"')
        if follow:
            lines += ["Follow-up questions and answers:"] + follow
        flags = sorted({h.message for t in consult.turns for h in t.red_flags})
        if flags:
            lines.append("Urgent signs noted during the consult: " + "; ".join(flags) + ".")
        reply = consult.last_reply
        if reply and reply.working_ddx:
            items = "; ".join(f"{d.condition} ({d.likelihood})" for d in reply.working_ddx)
            lines.append(
                f"SpaceDoc's working list before assessment (not checked; re-evaluate): {items}."
            )
        lines.append("Give the assessment: ranked differential, feasible tests and treatment.")
        return "\n".join(lines)

    def assess(self, consult: Consult) -> VerifiedAnswer:
        """Run the full, checked pipeline on the consult so far."""
        summary = self.case_summary(consult)
        patient: dict[str, Any] = dict(consult.patient.record) if consult.patient else {}
        # Patient claims are checked against what the user actually said, not against the
        # model's extracted facts.
        patient["reported_in_consult"] = [t.user_text for t in consult.turns]
        v = self.orchestrator.ask(summary, consult.env, patient, consult.user.medical_role)
        consult.assessments.append(v)
        if self.audit:
            self.audit.append(
                "consult_assessment",
                {
                    "consult_id": consult.consult_id,
                    "ask_audit_id": v.audit_id,
                    "rounds": consult.rounds,
                    "case_summary": summary,
                },
            )
        return v

    # ---- audit -------------------------------------------------------------------------

    def _log(self, consult: Consult, turn: Turn) -> None:
        if not self.audit:
            return
        turn.audit_id = self.audit.append(
            "consult_turn",
            {
                "consult_id": consult.consult_id,
                "n": turn.n,
                "user_text": turn.user_text,
                "red_flags": [h.model_dump() for h in turn.red_flags],
                "red_flags_dismissed": turn.red_flags_dismissed,
                "reply": turn.reply.model_dump() if turn.reply else None,
                "exam_checks": [
                    {
                        "request": c.request.model_dump(),
                        "missing": c.missing,
                        "findings": c.findings,
                    }
                    for c in turn.exam_checks
                ],
                "timing": asdict(turn.timing) if turn.timing else None,
                "thinking": turn.thinking,
                "error": turn.error,
            },
        )


def _sum(values: list[float | None]) -> float | None:
    return None if not values or any(v is None for v in values) else sum(values)  # type: ignore[arg-type]


def _timing(results: list[ChatResult], elapsed: float, deep_log: bool) -> TurnTiming:
    timing = TurnTiming(
        total_s=elapsed,
        load_s=_sum([r.load_s for r in results]),
        prompt_s=_sum([r.prompt_s for r in results]),
        gen_s=_sum([r.gen_s for r in results]),
        tokens=_sum([r.completion_tokens for r in results]),  # type: ignore[arg-type]
        deep_log=deep_log,
    )
    if deep_log and results and timing.gen_s is not None:
        thinking_time = 0.0
        for r in results:
            chars = len(r.thinking) + len(r.text)
            if chars and r.gen_s:
                thinking_time += r.gen_s * len(r.thinking) / chars
        timing.without_deep_log_s = max(elapsed - thinking_time, 0.0)
    return timing
