"""Hybrid retrieval (component C-03): keyword + vector search, fused and environment-boosted."""

from __future__ import annotations

import re

from spacedoc.answer.schema import Passage
from spacedoc.env.context import EnvironmentContext
from spacedoc.kb.store import KnowledgeStore
from spacedoc.llm.client import LLM

_STOP = set(
    "a an and are as at be by for from has have how i in is it my of on or should the this to "
    "was what when where which who why with do does can could would there their they you your".split()
)
RRF_K = 60  # standard reciprocal-rank-fusion constant


def fts_query(text: str) -> str:
    """Build a safe FTS5 query: quoted content words joined with OR."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def query_text(query: str, instruction: str) -> str:
    """Qwen3-Embedding's query format. Documents are embedded without an instruction."""
    return f"Instruct: {instruction}\nQuery:{query}" if instruction else query


class Retriever:
    def __init__(self, store: KnowledgeStore, embedder: LLM, query_instruction: str = "") -> None:
        self.store = store
        self.embedder = embedder
        self.query_instruction = query_instruction

    def search(
        self, query: str, env: EnvironmentContext | None = None, k: int = 6
    ) -> list[Passage]:
        pool = max(k * 4, 20)
        keyword = self.store.keyword_search(fts_query(query), pool)
        query_vec = self.embedder.embed([query_text(query, self.query_instruction)])[0]
        vector = self.store.vector_search(query_vec, pool)

        # Reciprocal rank fusion: each list votes 1/(K + rank). Robust to the two
        # scorers having incomparable scales (BM25 vs cosine).
        fused: dict[str, float] = {}
        for ranking in (keyword, vector):
            for rank, (chunk_id, _) in enumerate(ranking):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)

        env_tags = env.tags if env else set()
        scored = []
        for chunk_id, score in fused.items():
            chunk = self.store.get(chunk_id)
            if chunk is None:
                continue
            boost = 1.0 + 0.15 * len(env_tags & set(chunk.environment_tags))
            if chunk.tier == "A":
                boost *= 1.25
            elif chunk.tier == "B":
                boost *= 1.1
            scored.append((score * boost, chunk))
        scored.sort(key=lambda t: -t[0])

        return [
            Passage(
                cid=f"S{i + 1}",
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                title=c.title,
                text=c.text,
                page=c.page,
                url=c.url,
                tier=c.tier,
                score=round(s, 5),
            )
            for i, (s, c) in enumerate(scored[:k])
        ]
