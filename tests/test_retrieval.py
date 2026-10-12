from spacedoc.kb.ingest import chunk_words, load_manifest
from spacedoc.kb.retrieve import Retriever, fts_query
from spacedoc.kb.store import KnowledgeStore
from spacedoc.llm.client import FakeLLM
from spacedoc.system import ingest_manifest

from .conftest import DATA


def _store():
    llm = FakeLLM()
    store = KnowledgeStore(":memory:")
    d = DATA / "demo_corpus"
    ingest_manifest(store, llm, d / "manifest.yaml", d, "fake")
    return store, llm


def test_chunking_overlaps():
    words = " ".join(str(i) for i in range(1000))
    chunks = chunk_words(words, size=350, overlap=60)
    assert len(chunks) == 4
    assert chunks[0].split()[-60:] == chunks[1].split()[:60]


def test_manifest_loads():
    ids = {m.id for m in load_manifest(DATA / "demo_corpus" / "manifest.yaml")}
    assert ids == {"demo-renal", "demo-eye", "demo-injection"}


def test_fts_query_is_safe():
    q = fts_query('What "is" kidney-stone risk? DROP TABLE;')
    assert q == '"kidney" OR "stone" OR "risk" OR "drop" OR "table"'


def test_hybrid_retrieval_ranks_relevant_source_first(env_t4):
    store, llm = _store()
    hits = Retriever(store, llm).search("colicky flank pain and kidney stones", env_t4, k=3)
    assert hits[0].source_id == "demo-renal"
    assert [h.cid for h in hits] == ["S1", "S2", "S3"][: len(hits)]
    hits = Retriever(store, llm).search("fluorescein corneal abrasion eye", env_t4, k=3)
    assert hits[0].source_id == "demo-eye"


def test_reingest_replaces_source():
    store, llm = _store()
    n = store.count()
    d = DATA / "demo_corpus"
    ingest_manifest(store, llm, d / "manifest.yaml", d, "fake")
    assert store.count() == n


def test_query_gets_the_embedding_instruction_but_documents_do_not():
    from spacedoc.kb.retrieve import query_text

    store, llm = _store()
    seen = []

    class Recorder(FakeLLM):
        def embed(self, texts):
            seen.extend(texts)
            return llm.embed(texts)

    r = Retriever(store, Recorder(), query_instruction="Retrieve passages that answer it")
    r.search("kidney stone pain")
    assert seen == ["Instruct: Retrieve passages that answer it\nQuery:kidney stone pain"]
    assert query_text("q", "") == "q"  # no instruction configured: query unchanged


def test_changed_or_missing_files_are_skipped_not_fatal(tmp_path):
    import shutil

    import pytest

    d = DATA / "demo_corpus"
    for f in d.iterdir():
        shutil.copy(f, tmp_path / f.name)
    manifest = (tmp_path / "manifest.yaml").read_text()
    renal = next(m for m in load_manifest(tmp_path / "manifest.yaml") if m.id == "demo-renal")
    eye = next(m for m in load_manifest(tmp_path / "manifest.yaml") if m.id == "demo-eye")
    (tmp_path / "manifest.yaml").write_text(
        manifest.replace(f"file: {renal.file}", f"file: {renal.file}\n    sha256: {'a' * 64}")
    )
    (tmp_path / eye.file).unlink()

    store, llm = KnowledgeStore(":memory:"), FakeLLM()
    with pytest.raises(ValueError, match="sha256 mismatch"):
        ingest_manifest(store, llm, tmp_path / "manifest.yaml", tmp_path, "fake")

    skipped = []
    ingest_manifest(store, llm, tmp_path / "manifest.yaml", tmp_path, "fake", skipped)
    assert {s for s, _, _ in store.sources()} == {"demo-injection"}
    assert len(skipped) == 2
    assert any("demo-renal" in s and "sha256 mismatch" in s for s in skipped)
    assert any("demo-eye" in s and "not found" in s for s in skipped)
