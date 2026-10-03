"""Wire the components together from settings (real mode) or scripted stand-ins (demo mode)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spacedoc.agent.orchestrator import GenerationPlan, Orchestrator
from spacedoc.audit.log import AuditLog
from spacedoc.config import Settings
from spacedoc.env.context import EnvironmentContext, load_environment
from spacedoc.kb.ingest import chunk_source, load_manifest
from spacedoc.kb.retrieve import Retriever
from spacedoc.kb.store import KnowledgeStore
from spacedoc.llm.client import FakeLLM, GenParams, connect
from spacedoc.tools.formulary import Formulary
from spacedoc.verify.grounding import LexicalOverlapChecker, MiniCheckChecker
from spacedoc.verify.pipeline import Verifier
from spacedoc.verify.rules import load_feasibility_rules


@dataclass
class System:
    settings: Settings
    orchestrator: Orchestrator
    store: KnowledgeStore
    demo: bool

    def environment(self, tier: str | None = None, **overrides) -> EnvironmentContext:
        return load_environment(
            tier or self.settings.default_tier, self.settings.data_dir, **overrides
        )


def ingest_manifest(
    store: KnowledgeStore, embedder, manifest: Path, files_dir: Path, model: str
) -> int:
    total = 0
    for meta in load_manifest(manifest):
        chunks = chunk_source(meta, files_dir)
        store.delete_source(meta.id)
        vectors = []
        for i in range(0, len(chunks), 32):
            vectors += embedder.embed([c.text for c in chunks[i : i + 32]])
        store.add_chunks(chunks, vectors, model)
        total += len(chunks)
    return total


def generation_plan(settings: Settings) -> GenerationPlan:
    """Per-pass generation settings from spacedoc.toml (Qwen3's recommended sampling)."""

    def params(think: bool, max_tokens: int) -> GenParams:
        profile = settings.sampling_thinking if think else settings.sampling_plain
        return GenParams.from_profile(
            profile,
            seed=settings.seed,
            max_tokens=max_tokens,
            num_ctx=settings.chat_num_ctx,
            think=think,
        )

    return GenerationPlan(
        draft=params(settings.think_draft, settings.draft_max_tokens),
        finalize=params(settings.think_finalize, settings.finalize_max_tokens),
    )


def build_system(settings: Settings, demo: bool = False) -> System:
    formulary = Formulary.load("example-transit", settings.data_dir)
    feasibility = load_feasibility_rules(settings.data_dir)
    if demo:
        from spacedoc.demo import demo_responder

        llm = FakeLLM(demo_responder)
        store = KnowledgeStore(":memory:")
        demo_dir = settings.data_dir / "demo_corpus"
        ingest_manifest(store, llm, demo_dir / "manifest.yaml", demo_dir, "fake-hash-embed")
        checker = LexicalOverlapChecker()
        embedder = llm
        audit = AuditLog(settings.audit_path.parent / "demo-audit.jsonl")
        model_name = "demo (scripted, no model)"
    else:
        llm = connect(
            settings.llm_backend,
            settings.llm_base_url,
            settings.chat_model,
            settings.embed_model,
            settings.request_timeout_s,
        )
        checker = MiniCheckChecker(
            connect(
                settings.llm_backend,
                settings.llm_base_url,
                settings.checker_model,
                None,
                settings.request_timeout_s,
            ),
            num_ctx=settings.checker_num_ctx,
        )
        store = KnowledgeStore(settings.db_path)
        embedder = llm
        audit = AuditLog(settings.audit_path)
        model_name = settings.chat_model
    verifier = Verifier(checker, formulary, feasibility, settings.min_support_fraction)
    orch = Orchestrator(
        llm=llm,
        retriever=Retriever(store, embedder),
        verifier=verifier,
        formulary=formulary,
        audit=audit,
        top_k=settings.top_k,
        consistency_samples=settings.consistency_samples,
        model_name=model_name,
        generation=None if demo else generation_plan(settings),
    )
    return System(settings=settings, orchestrator=orch, store=store, demo=demo)
