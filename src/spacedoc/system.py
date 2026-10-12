"""Wire the components together from settings (real mode) or scripted stand-ins (demo mode)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spacedoc.agent.orchestrator import GenerationPlan, Orchestrator
from spacedoc.audit.log import AuditLog
from spacedoc.config import Settings
from spacedoc.consult.engine import ConsultEngine
from spacedoc.consult.redflags import RedFlags
from spacedoc.consult.roster import load_roster
from spacedoc.consult.safety import ExposureScreen, MustAsk, MustNotMiss, VitalRules
from spacedoc.env.context import EnvironmentContext, load_environment
from spacedoc.kb.ingest import chunk_source, load_manifest
from spacedoc.kb.retrieve import Retriever
from spacedoc.kb.store import KnowledgeStore
from spacedoc.llm.client import FakeLLM, GenParams, connect
from spacedoc.review.summary import ReasoningReviewer
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
    reviewer: ReasoningReviewer | None = None
    consult: ConsultEngine | None = None

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


@dataclass
class ModelCheck:
    reachable: bool
    missing: list[str]
    error: str | None = None

    def problems(self) -> list[str]:
        """Plain-language lines for the user; empty when everything is in place."""
        if not self.reachable:
            return [f"Cannot reach the model server: {self.error}"]
        return [f"Model {m} is not installed. Run: ollama pull {m}" for m in self.missing]


def check_models(settings: Settings) -> ModelCheck:
    """Are the configured models installed on the model server? (Cheap; no model loads.)"""
    from spacedoc.llm.client import LLMError

    client = connect(settings.llm_backend, settings.llm_base_url, settings.chat_model, None, 10.0)
    try:
        installed = set(client.installed_models())
    except LLMError as e:
        return ModelCheck(reachable=False, missing=[], error=str(e))
    wanted = [settings.chat_model, settings.embed_model, settings.checker_model]
    if settings.consult_model:
        wanted.append(settings.consult_model)

    def have(name: str) -> bool:
        return name in installed or (":" not in name and f"{name}:latest" in installed)

    return ModelCheck(reachable=True, missing=[m for m in dict.fromkeys(wanted) if not have(m)])


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

    return GenerationPlan(draft=params(settings.think_draft, settings.draft_max_tokens))


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
            settings.keep_alive,
        )
        checker = MiniCheckChecker(
            connect(
                settings.llm_backend,
                settings.llm_base_url,
                settings.checker_model,
                None,
                settings.request_timeout_s,
                settings.checker_keep_alive,
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
        retriever=Retriever(store, embedder, "" if demo else settings.embed_query_instruction),
        verifier=verifier,
        formulary=formulary,
        audit=audit,
        top_k=settings.top_k,
        consistency_samples=settings.consistency_samples,
        model_name=model_name,
        generation=None if demo else generation_plan(settings),
    )
    reviewer = ReasoningReviewer(
        llm,
        audit,
        GenParams()
        if demo
        else GenParams.from_profile(
            settings.sampling_plain,
            seed=settings.seed,
            max_tokens=settings.review_max_tokens,
            num_ctx=settings.chat_num_ctx,
            think=False,
        ),
        model_name,
    )
    consult_llm, consult_name = llm, model_name
    if not demo and settings.consult_model and settings.consult_model != settings.chat_model:
        consult_llm = connect(
            settings.llm_backend,
            settings.llm_base_url,
            settings.consult_model,
            None,
            settings.request_timeout_s,
            settings.keep_alive,
        )
        consult_name = settings.consult_model
    consult = ConsultEngine(
        llm=consult_llm,
        orchestrator=orch,
        audit=audit,
        roster=load_roster(settings.data_dir),
        red_flags=RedFlags.load(settings.data_dir),
        feasibility=feasibility,
        params=consult_params(settings, deep=False, demo=demo),
        deep_params=consult_params(settings, deep=True, demo=demo),
        model_name=consult_name,
        max_rounds=settings.consult_max_rounds,
        vitals=VitalRules.load(settings.data_dir),
        must_not_miss=MustNotMiss.load(settings.data_dir),
        screen=ExposureScreen.load(settings.data_dir),
        must_ask=MustAsk.load(settings.data_dir),
    )
    return System(
        settings=settings,
        orchestrator=orch,
        store=store,
        demo=demo,
        reviewer=reviewer,
        consult=consult,
    )


def consult_params(settings: Settings, deep: bool, demo: bool = False) -> GenParams:
    """Question turns: thinking off and a short reply; deep log turns thinking on."""
    if demo:
        return GenParams(think=deep)
    return GenParams.from_profile(
        settings.sampling_thinking if deep else settings.sampling_plain,
        seed=settings.seed,
        max_tokens=settings.consult_deep_max_tokens if deep else settings.consult_max_tokens,
        num_ctx=settings.chat_num_ctx,
        think=deep,
    )
