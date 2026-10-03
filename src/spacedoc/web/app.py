"""Local GUI (FastAPI + one static page). Runs offline; binds to localhost by default."""

from __future__ import annotations

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


def create_app(system: System) -> FastAPI:
    app = FastAPI(title="SpaceDoc", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        orch = system.orchestrator
        return {
            "demo": system.demo,
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

    @app.get("/api/chunk/{chunk_id:path}")
    def chunk(chunk_id: str) -> dict[str, Any]:
        c = system.store.get(chunk_id)
        if c is None:
            raise HTTPException(404, "Unknown source passage")
        return c.model_dump()

    return app
