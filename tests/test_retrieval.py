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
