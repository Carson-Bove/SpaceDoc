"""SQLite knowledge store: chunks, an FTS5 keyword index, and embedding vectors."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from spacedoc.kb.ingest import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    tier TEXT,
    environment_tags TEXT,
    topic_tags TEXT,
    url TEXT,
    license TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED, text, title, tokenize = 'porter unicode61'
);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    vector BLOB NOT NULL
);
"""


class KnowledgeStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._matrix: np.ndarray | None = None
        self._matrix_ids: list[str] = []

    # -- writing -------------------------------------------------------------------------
    def delete_source(self, source_id: str) -> None:
        ids = [
            r[0]
            for r in self.db.execute("SELECT chunk_id FROM chunks WHERE source_id=?", (source_id,))
        ]
        self.db.executemany("DELETE FROM chunks_fts WHERE chunk_id=?", [(i,) for i in ids])
        self.db.executemany("DELETE FROM embeddings WHERE chunk_id=?", [(i,) for i in ids])
        self.db.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        self.db.commit()
        self._matrix = None

    def add_chunks(self, chunks: list[Chunk], vectors: list[list[float]], model: str) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        for c, v in zip(chunks, vectors, strict=True):
            self.db.execute(
                "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    c.chunk_id,
                    c.source_id,
                    c.title,
                    c.text,
                    c.page,
                    c.tier,
                    json.dumps(c.environment_tags),
                    json.dumps(c.topic_tags),
                    c.url,
                    c.license,
                ),
            )
            self.db.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (c.chunk_id,))
            self.db.execute(
                "INSERT INTO chunks_fts (chunk_id, text, title) VALUES (?,?,?)",
                (c.chunk_id, c.text, c.title),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO embeddings VALUES (?,?,?)",
                (c.chunk_id, model, np.asarray(v, dtype=np.float32).tobytes()),
            )
        self.db.commit()
        self._matrix = None

    # -- reading -------------------------------------------------------------------------
    def get(self, chunk_id: str) -> Chunk | None:
        row = self.db.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["environment_tags"] = json.loads(d["environment_tags"] or "[]")
        d["topic_tags"] = json.loads(d["topic_tags"] or "[]")
        return Chunk(**d)

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def sources(self) -> list[tuple[str, str, int]]:
        return [
            (r[0], r[1], r[2])
            for r in self.db.execute(
                "SELECT source_id, title, COUNT(*) FROM chunks GROUP BY source_id ORDER BY source_id"
            )
        ]

    def keyword_search(self, fts_query: str, limit: int) -> list[tuple[str, float]]:
        """BM25 ranking from SQLite FTS5 (lower bm25() is better, so we negate it)."""
        if not fts_query:
            return []
        rows = self.db.execute(
            "SELECT chunk_id, bm25(chunks_fts) AS s FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY s LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return [(r[0], -r[1]) for r in rows]

    def _load_matrix(self) -> None:
        rows = self.db.execute("SELECT chunk_id, vector FROM embeddings").fetchall()
        self._matrix_ids = [r[0] for r in rows]
        if rows:
            m = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            self._matrix = m / np.where(norms == 0, 1, norms)
        else:
            self._matrix = np.zeros((0, 1), dtype=np.float32)

    def vector_search(self, query_vec: list[float], limit: int) -> list[tuple[str, float]]:
        """Brute-force cosine similarity; fine for tens of thousands of chunks."""
        if self._matrix is None:
            self._load_matrix()
        assert self._matrix is not None
        if self._matrix.shape[0] == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        sims = self._matrix @ q
        top = np.argsort(-sims)[:limit]
        return [(self._matrix_ids[i], float(sims[i])) for i in top]
