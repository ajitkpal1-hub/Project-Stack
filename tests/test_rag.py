"""Phase 4: RAG knowledge assistant. No network: hash embeddings, in-memory store, fake generators.

The fixture document is TEST DATA ONLY and is never loaded into the real knowledge base.
"""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from reloop.config import Settings
from reloop.models.knowledge import AnswerMode, AnswerSegment, DocumentMeta
from reloop.rag.answer import ClaudeGenerator, GenerationError, KnowledgeAssistant, get_generator
from reloop.rag.chunking import chunk_pages, clean_text, extract_pages
from reloop.rag.embeddings import DIMENSIONS, EmbeddingError, HashEmbedder, VoyageEmbedder, get_embedder
from reloop.rag.store import InMemoryStore, StoreError, SupabaseStore, get_store, sha256_of
from reloop.routes import assistant as assistant_route
from reloop.web import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"
SETTINGS = Settings(rag_top_k=4, rag_min_similarity=0.15)


def loaded_store() -> InMemoryStore:
    store = InMemoryStore()
    path = FIXTURES / "test-guidance.md"
    chunks = chunk_pages(extract_pages(path))
    store.upsert_document(DocumentMeta(file_name=path.name, title="Test Guidance (fixture)"), sha256_of(path.read_bytes()),
                          chunks, HashEmbedder().embed([c.content for c in chunks], "document"))
    return store


class CitingGenerator:
    """Pretends to be Claude: cites passage 2 only (to exercise renumbering)."""

    def generate(self, question, passages):
        return [AnswerSegment(text="Keep used batteries out of the bins.", source_numbers=[min(2, len(passages))])]


class UncitedGenerator:
    def generate(self, question, passages):
        return [AnswerSegment(text="Batteries are fine in any bin.", source_numbers=[])]


class NotInSourcesGenerator:
    def generate(self, question, passages):
        return None


class FailingGenerator:
    def generate(self, question, passages):
        raise GenerationError("The assistant had a problem.")


# ---------- ingestion pieces ----------

def test_clean_text_joins_hyphenation_and_collapses_space():
    assert clean_text("recy-\ncling   bins\n\n\n\nnext") == "recycling bins\n\nnext"


def test_chunking_keeps_headings_and_sizes():
    chunks = chunk_pages(extract_pages(FIXTURES / "test-guidance.md"))
    assert chunks and all(len(c.content) <= 1600 for c in chunks)
    assert any(c.heading for c in chunks)


def test_chunking_long_text_overlaps_and_tracks_pages():
    para = ("Plastic bottles should be rinsed and dried before they go to dry waste collection. " * 12).strip()
    chunks = chunk_pages([para + "\n\n" + para, para])
    assert len(chunks) >= 3
    assert chunks[0].page_from == 1 and chunks[-1].page_from in (1, 2)
    assert all(c.index == i for i, c in enumerate(chunks))


def test_rejects_unsupported_file(tmp_path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="Unsupported"):
        extract_pages(f)


def test_manifest_rejects_non_http_links():
    with pytest.raises(ValueError):
        DocumentMeta(file_name="a.pdf", title="A", source_url="javascript:alert(1)")


def test_hash_embedder_dimensions_and_similarity():
    e = HashEmbedder()
    a, b, c = e.embed(["used batteries collection", "batteries collection point", "vegetable peels compost"], "document")
    assert len(a) == DIMENSIONS
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))  # noqa: E731
    assert dot(a, b) > dot(a, c)


# ---------- answering ----------

def test_grounded_answer_renumbers_sources():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS).answer("How do I dispose of used batteries?")
    assert a.mode == AnswerMode.GROUNDED
    assert len(a.sources) == 1 and a.segments[0].source_numbers == [1]


def test_irrelevant_question_has_no_source():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), Settings(rag_min_similarity=0.5)).answer("cricket score yesterday")
    assert a.mode == AnswerMode.NO_SOURCE
    assert "won't guess" in a.message


def test_empty_store_has_no_source():
    a = KnowledgeAssistant(InMemoryStore(), HashEmbedder(), CitingGenerator(), SETTINGS).answer("batteries?")
    assert a.mode == AnswerMode.NO_SOURCE


def test_uncited_generation_is_not_presented_as_answer():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), UncitedGenerator(), SETTINGS).answer("used batteries disposal")
    assert a.mode == AnswerMode.NO_SOURCE
    assert not a.segments


def test_model_saying_not_in_sources_is_respected():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), NotInSourcesGenerator(), SETTINGS).answer("used batteries disposal")
    assert a.mode == AnswerMode.NO_SOURCE


def test_without_llm_shows_verbatim_passages():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), None, SETTINGS).answer("expired medicines strips")
    assert a.mode == AnswerMode.PASSAGES
    assert any("medicines" in s.content.lower() for s in a.sources)


def test_generation_failure_falls_back_to_passages():
    a = KnowledgeAssistant(loaded_store(), HashEmbedder(), FailingGenerator(), SETTINGS).answer("used batteries disposal")
    assert a.mode == AnswerMode.PASSAGES and a.sources


def test_store_failure_is_unavailable():
    class Broken(InMemoryStore):
        def search(self, *a, **k):
            raise StoreError("We couldn't reach the knowledge base. Please try again shortly.")

    a = KnowledgeAssistant(Broken(), HashEmbedder(), CitingGenerator(), SETTINGS).answer("batteries")
    assert a.mode == AnswerMode.UNAVAILABLE and "couldn't reach" in a.message


def test_claude_generator_maps_citations():
    g = ClaudeGenerator(api_key="test")
    cit = SimpleNamespace(document_index=1)
    resp = SimpleNamespace(
        stop_reason="end_turn", model="claude-opus-5-5", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="Keep batteries out of bins.", citations=[cit]),
                 SimpleNamespace(type="text", text=" ", citations=None)],
    )

    def create(**kw):
        docs = [b for b in kw["messages"][0]["content"] if b["type"] == "document"]
        assert docs and all(d["citations"] == {"enabled": True} for d in docs)
        return resp

    g._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    from reloop.models.knowledge import RetrievedChunk

    p = [RetrievedChunk(content="a", similarity=0.9, title="T1"), RetrievedChunk(content="b", similarity=0.8, title="T2")]
    segs = g.generate("q", p)
    assert segs[0].source_numbers == [2] and segs[1].source_numbers == []


def test_claude_generator_not_in_sources():
    g = ClaudeGenerator(api_key="test")
    resp = SimpleNamespace(stop_reason="end_turn", model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                           content=[SimpleNamespace(type="text", text="NOT_IN_SOURCES", citations=None)])
    g._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp)))
    from reloop.models.knowledge import RetrievedChunk

    assert g.generate("q", [RetrievedChunk(content="a", similarity=0.9, title="T")]) is None


# ---------- configuration ----------

def test_provider_selection():
    assert get_embedder(Settings()) is None
    assert get_embedder(Settings(embedding_provider="voyage")) is None  # no key
    assert isinstance(get_embedder(Settings(embedding_provider="voyage", embedding_api_key="k")), VoyageEmbedder)
    assert isinstance(get_embedder(Settings(embedding_provider="hash")), HashEmbedder)
    assert get_store(Settings()) is None
    assert get_generator(Settings(llm_provider="mock")) is None  # demo mode never generates


def test_voyage_request_shape(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, auth=headers["Authorization"])
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = VoyageEmbedder("key-123").embed(["a", "b"], "query")
    assert out == [[1.0], [2.0]]  # reordered by index
    assert seen["json"] == {"input": ["a", "b"], "model": "voyage-4", "input_type": "query", "output_dimension": 1024}
    assert seen["auth"] == "Bearer key-123"


def test_voyage_bulk_waits_out_rate_limit(monkeypatch):
    calls, waits = [], []

    def fake_post(url, json, headers, timeout):
        calls.append(json["input"])
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "5"})
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(i)]} for i in range(len(json["input"]))]})

    monkeypatch.setattr(httpx, "post", fake_post)
    emb = VoyageEmbedder("k", max_retries=3, max_batch_chars=10, sleep=waits.append)
    out = emb.embed(["aaaaaa", "bbbbbb", "cc"], "document")
    assert out == [[0.0], [0.0], [1.0]]
    assert calls == [["aaaaaa"], ["aaaaaa"], ["bbbbbb", "cc"]]  # split by size, first batch retried
    assert waits == [20.0]  # at least 20s even if Retry-After is shorter


def test_voyage_live_rate_limit_fails_fast(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429))
    waits = []
    with pytest.raises(EmbeddingError, match="rate limit"):
        VoyageEmbedder("k", sleep=waits.append).embed(["a"], "query")
    assert waits == []


def test_voyage_bulk_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429))
    waits = []
    with pytest.raises(EmbeddingError):
        VoyageEmbedder("k", max_retries=2, sleep=waits.append).embed(["a"], "document")
    assert len(waits) == 2


def test_supabase_search_uses_rpc_and_maps_rows(monkeypatch):
    calls = []

    def fake_request(method, url, headers, timeout, **kw):
        calls.append((method, url, kw.get("json")))
        return httpx.Response(200, json=[{"content": "x", "similarity": 0.8, "title": "T", "publisher": None, "source_url": None,
                                          "published_on": None, "heading": None, "page_from": None, "chunk_index": 0}])

    monkeypatch.setattr(httpx, "request", fake_request)
    rows = SupabaseStore("https://abc.supabase.co", "service-key").search([0.1, 0.2], k=3, min_similarity=0.4)
    assert rows[0].title == "T"
    method, url, body = calls[0]
    assert method == "POST" and url.endswith("/rest/v1/rpc/match_knowledge_chunks")
    assert body["query_embedding"].startswith("[") and body["match_count"] == 3


def test_supabase_errors_become_store_errors(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(500, text="boom"))
    with pytest.raises(StoreError):
        SupabaseStore("https://abc.supabase.co", "k").document_count()


# ---------- ingestion script ----------

def test_ingest_dry_run(capsys):
    from scripts import ingest

    assert ingest.main(["--dir", str(FIXTURES), "--dry-run"]) == 0
    assert "test-guidance.md" in capsys.readouterr().out


def test_ingest_requires_manifest_entry(tmp_path, capsys):
    from scripts import ingest

    (tmp_path / "orphan.txt").write_text("Some guidance text that is long enough to make one chunk of content. " * 3)
    assert ingest.main(["--dir", str(tmp_path), "--dry-run"]) == 1
    assert "orphan.txt" in capsys.readouterr().out


def test_drop_mostly_devanagari_keeps_english_and_renumbers():
    from reloop.models.knowledge import Chunk
    from reloop.rag.chunking import drop_mostly_devanagari

    chunks = [Chunk(index=0, content="ऄसाधारण भाग खण्ड रजजस्ट्री"), Chunk(index=1, content="Every producer shall register on the portal."),
              Chunk(index=2, content="Bulk generators (थोक) must segregate waste at source.")]
    kept = drop_mostly_devanagari(chunks)
    assert [c.content[:5] for c in kept] == ["Every", "Bulk "]
    assert [c.index for c in kept] == [0, 1]


def test_ingest_english_only_flag_is_not_stored_as_metadata(tmp_path, capsys):
    from scripts import ingest

    (tmp_path / "gazette.txt").write_text(
        "असाधारण भाग खण्ड रजिस्ट्री संख्या प्रकाशित अधिसूचना नियम " * 30 + "\n\n" +
        "Every producer of electrical equipment shall register on the portal and file returns. " * 3, encoding="utf-8")
    (tmp_path / "manifest.toml").write_text('[[document]]\nfile_name = "gazette.txt"\ntitle = "Gazette"\nenglish_only = true\n', encoding="utf-8")
    manifest, english_only = ingest.load_manifest(tmp_path / "manifest.toml")
    assert english_only == {"gazette.txt"}
    assert "english_only" not in manifest["gazette.txt"].model_dump()
    assert ingest.main(["--dir", str(tmp_path), "--dry-run"]) == 0
    assert "skipped 1 Hindi chunks" in capsys.readouterr().out


# ---------- routes ----------

@pytest.fixture
def client():
    yield TestClient(create_app())
    assistant_route._assistant_override = None


def test_assistant_page_honest_when_unconfigured(client):
    html = client.get("/assistant").text
    assert "hasn&#39;t been filled" in html or "hasn't been filled" in html
    r = client.post("/assistant", data={"question": "batteries?"})
    assert "isn&#39;t ready" in r.text or "isn't ready" in r.text


def test_assistant_grounded_answer_renders_citations(client):
    assistant_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    html = client.post("/assistant", data={"question": "How do I dispose of used batteries?"}).text
    assert "Answered from 1 source" in html
    assert 'href="#src-1"' in html and 'id="src-1"' in html
    assert "Test Guidance (fixture)" in html and "no link recorded" in html


def test_assistant_rejects_empty_and_long_questions(client):
    assert client.post("/assistant", data={"question": "  "}).status_code == 422
    assert client.post("/assistant", data={"question": "x" * 600}).status_code == 422


def test_assistant_escapes_question(client):
    assistant_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), None, SETTINGS)
    html = client.post("/assistant", data={"question": "<script>alert(1)</script> batteries"}).text
    assert "<script>alert(1)</script>" not in html


@pytest.mark.parametrize("key,expect_bearer", [("sb_secret_abc123", False), ("eyJhbGciOi.legacy.jwt", True)])
def test_supabase_key_headers(key, expect_bearer):
    s = SupabaseStore("https://abc.supabase.co", key)
    assert s._headers["apikey"] == key
    assert ("Authorization" in s._headers) is expect_bearer
