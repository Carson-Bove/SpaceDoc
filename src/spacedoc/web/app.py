"""Local GUI (FastAPI + one static page). Runs offline; binds to localhost by default."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from spacedoc.env.context import list_tiers
from spacedoc.system import System

STATIC = Path(__file__).parent / "static"


class AskRequest(BaseModel):
    question: str
    tier: str | None = None
    role: str = "cmo"
    patient: dict[str, Any] | None = None


class ConsultStart(BaseModel):
    user: str
    patient: str  # a crew ID, "self" or "unlisted"
    tier: str | None = None
    practice: bool = False
    scenario_id: str | None = None
    deep_log: bool = False


class ConsultMessage(BaseModel):
    text: str


def create_app(system: System) -> FastAPI:
    app = FastAPI(title="SpaceDoc", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        from spacedoc.system import check_models

        orch = system.orchestrator
        problems = [] if system.demo else check_models(system.settings).problems()
        return {
            "demo": system.demo,
            "model_problems": problems,
            "consult_model": system.consult.model_name if system.consult else None,
            "model": orch.model_name,
            "checker": getattr(orch.verifier.checker, "name", "?"),
            "chunks": system.store.count(),
            "sources": [{"id": s, "title": t, "chunks": n} for s, t, n in system.store.sources()],
            "default_tier": system.settings.default_tier,
        }

    @app.get("/api/env")
    def env() -> list[dict[str, Any]]:
        return [
            {**e.model_dump(), "summary": e.summary()} for e in list_tiers(system.settings.data_dir)
        ]

    @app.get("/api/demo-patient")
    def demo_patient() -> dict[str, Any]:
        from spacedoc.demo import DEMO_PATIENT

        return DEMO_PATIENT

    @app.post("/api/ask")
    def ask(req: AskRequest) -> dict[str, Any]:
        if not req.question.strip():
            raise HTTPException(400, "Type a question first.")
        try:
            env = system.environment(req.tier)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from e
        v = system.orchestrator.ask(req.question, env, req.patient, req.role)
        return v.model_dump(mode="json")

    @app.get("/api/review/{audit_id}")
    def review(audit_id: str) -> dict[str, Any]:
        """The saved reasoning summary for an answer (null if not made yet)."""
        from spacedoc.review.summary import LABEL, NoReasoning

        reviewer = _reviewer()
        try:
            notes = reviewer.notes(audit_id)
        except NoReasoning as e:
            raise HTTPException(404, str(e)) from e
        saved = reviewer.get(audit_id)
        return {
            "label": LABEL,
            "passes": [t["pass"] for t in notes],
            "summary": saved.model_dump() if saved else None,
        }

    @app.post("/api/review/{audit_id}/summarize")
    def summarize(audit_id: str) -> dict[str, Any]:
        """Create (or return the saved) reasoning summary. Runs the model; may take a while."""
        from spacedoc.llm.client import LLMError
        from spacedoc.review.summary import NoReasoning

        try:
            return _reviewer().summarize(audit_id).model_dump()
        except NoReasoning as e:
            raise HTTPException(404, str(e)) from e
        except LLMError as e:
            raise HTTPException(503, f"The model could not summarize the notes: {e}") from e

    @app.get("/api/review/{audit_id}/notes")
    def notes(audit_id: str) -> dict[str, Any]:
        """The full thinking notes, for reviewers who want the original."""
        from spacedoc.review.summary import LABEL, NoReasoning

        try:
            return {"label": LABEL, "notes": _reviewer().notes(audit_id)}
        except NoReasoning as e:
            raise HTTPException(404, str(e)) from e

    def _reviewer():
        if system.reviewer is None:
            raise HTTPException(404, "Reasoning review is not available")
        return system.reviewer

    # ---- consult mode (docs/consult-mode-design.md) ------------------------------------
    # Open consults live in this server's memory; every turn is also in the audit log.
    consults: dict[str, Any] = {}

    def _engine():
        if system.consult is None:
            raise HTTPException(404, "Consult mode is not available")
        return system.consult

    def _consult(consult_id: str):
        c = consults.get(consult_id)
        if c is None:
            raise HTTPException(
                404, "This consult is not open (the server may have restarted). Start a new one."
            )
        return c

    def _turn_json(consult, turn) -> dict[str, Any]:
        from spacedoc.consult.render import timing_line

        engine = _engine()
        reply = turn.reply
        return {
            "n": turn.n,
            "user_text": turn.user_text,
            "paused": turn.paused,
            "red_flags": [h.model_dump() for h in turn.red_flags],
            "red_flags_dismissed": turn.red_flags_dismissed,
            "reply": reply.model_dump() if reply else None,
            "exam_checks": [
                {
                    "request": c.request.model_dump(),
                    "missing": c.missing,
                    "findings": c.findings,
                    "ok": c.ok,
                }
                for c in turn.exam_checks
            ],
            "timing": asdict(turn.timing) if turn.timing else None,
            "timing_line": timing_line(turn.timing),
            "thinking": turn.thinking,
            "error": turn.error,
            "urgent_steps": engine.red_flags.steps(delay=consult.delay())
            if reply and reply.urgent.flag
            else [],
            "assess_reason": engine.should_assess(consult) if reply else None,
            "screen": [i.model_dump() for i in turn.screen],
            "must_not_miss_added": turn.must_not_miss_added,
        }

    @app.get("/api/roster")
    def roster() -> list[dict[str, Any]]:
        return [
            {
                "crew_id": m.crew_id,
                "role": m.role,
                "medical_role": m.medical_role,
                "label": m.label(),
            }
            for m in _engine().roster.values()
        ]

    @app.post("/api/consult")
    def consult_start(req: ConsultStart) -> dict[str, Any]:
        try:
            env = system.environment(req.tier)
            c = _engine().start(
                req.user, req.patient, env, req.practice, req.scenario_id, req.deep_log
            )
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, str(e)) from e
        consults[c.consult_id] = c
        return {
            "consult_id": c.consult_id,
            "patient_summary": c.patient_summary,
            "user": c.user.label(),
            "patient": "the user" if c.patient_is_user else c.patient_label,
            "patient_is_user": c.patient_is_user,
            "practice": c.practice,
            "scenario_id": c.scenario_id,
            "deep_log": c.deep_log,
            "environment": env.summary(),
        }

    @app.post("/api/consult/{consult_id}/turn")
    def consult_turn(consult_id: str, msg: ConsultMessage) -> dict[str, Any]:
        c = _consult(consult_id)
        if not msg.text.strip():
            raise HTTPException(400, "Type something first.")
        if c.turns and c.turns[-1].paused:
            raise HTTPException(409, "Answer the urgent-sign card first.")
        return _turn_json(c, _engine().turn(c, msg.text))

    @app.post("/api/consult/{consult_id}/resume")
    def consult_resume(consult_id: str) -> dict[str, Any]:
        c = _consult(consult_id)
        try:
            return _turn_json(c, _engine().resume(c))
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/consult/{consult_id}/assess")
    def consult_assess(consult_id: str) -> dict[str, Any]:
        c = _consult(consult_id)
        if not c.turns:
            raise HTTPException(400, "Describe the problem first.")
        return _engine().assess(c).model_dump(mode="json")

    @app.get("/api/consult/{consult_id}/record")
    def consult_record(consult_id: str) -> dict[str, Any]:
        from spacedoc.consult.render import record_markdown, timing_summary

        c = _consult(consult_id)
        return {"markdown": record_markdown(c), "timing": timing_summary(c)}

    @app.post("/api/consult/{consult_id}/end")
    def consult_end(consult_id: str) -> dict[str, Any]:
        from spacedoc.consult.render import record_markdown, save_record, timing_summary

        c = _consult(consult_id)
        path = save_record(c, system.settings.audit_path.parent / "consults")
        return {"path": str(path), "timing": timing_summary(c), "markdown": record_markdown(c)}

    @app.get("/api/chunk/{chunk_id:path}")
    def chunk(chunk_id: str) -> dict[str, Any]:
        c = system.store.get(chunk_id)
        if c is None:
            raise HTTPException(404, "Unknown source passage")
        return c.model_dump()

    return app
