"""Tests for the chunking / extraction / ingestion logic (no network)."""
import pytest

from app.config import settings
from app.services import ingestion


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        assert ingestion.chunk_text("Hello world", size=800) == ["Hello world"]

    def test_empty_text(self):
        assert ingestion.chunk_text("   \n  ") == []

    def test_no_chunk_exceeds_size(self):
        text = " ".join(f"paragraph {i} with some words" for i in range(200))
        chunks = ingestion.chunk_text(text, size=200, overlap=20)
        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)

    def test_overlap_attaches_previous_tail(self):
        text = " ".join(f"word{i}" for i in range(400))
        chunks = ingestion.chunk_text(text, size=120, overlap=40)
        assert len(chunks) >= 2
        tail = chunks[0][-40:].lstrip()
        assert tail in chunks[1]

    def test_overlap_does_not_drop_text(self):
        words = [f"word{i:03d}" for i in range(100)]
        text = " ".join(words)
        chunks = ingestion.chunk_text(text, size=60, overlap=15)
        combined = " ".join(chunks)
        assert all(w in combined for w in words)
        assert all(len(c) <= 60 for c in chunks)

    def test_paragraphs_recombined_into_chunks(self):
        paragraphs = "\n\n".join(f"para {i} " + "x" * 30 for i in range(10))
        chunks = ingestion.chunk_text(paragraphs, size=120, overlap=10)
        assert any("para 0" in c and "para 1" in c for c in chunks)


class TestExtractText:
    def test_json_flattened(self):
        data = b'{"name": "Chitkara", "fees": [1000, 2000], "depth": {"a": "b"}}'
        text = ingestion.extract_text("data.json", data)
        assert "name: Chitkara" in text
        assert ". 1000" in text or "1000" in text
        assert "a: b" in text

    def test_json_invalid_falls_back_to_text(self):
        data = b"{ not valid json ]"
        assert "not valid json" in ingestion.extract_text("a.json", data)

    def test_md_text(self):
        assert ingestion.extract_text("faq.md", b"# Title\nbody") == "# Title\nbody"

    def test_unsupported_type(self):
        with pytest.raises(ValueError):
            ingestion.extract_text("notes.docx", b"x" * 10)


class TestIngestNamespaceDedup:
    def test_delete_filter_scoped_to_filename_and_namespace(self, monkeypatch):
        ops = {}

        class FakeCol:
            def delete_many(self, filt):
                ops["delete_filter"] = filt
                return type("R", (), {"deleted_count": 1})()

            def insert_one(self, doc):
                ops.setdefault("inserts", []).append(doc)
                return type("R", (), {"inserted_id": "id"})()

        class FakeDb:
            def __getitem__(self, name):
                return fake_col

        fake_col = FakeCol()
        monkeypatch.setattr(ingestion, "db", FakeDb())
        monkeypatch.setattr(
            ingestion, "generate_embedding", lambda txt: [0.1, 0.2, 0.3]
        )
        monkeypatch.setattr(settings, "CHUNK_SIZE", 40)
        monkeypatch.setattr(settings, "CHUNK_OVERLAP", 5)

        n = ingestion.ingest_document(
            "syllabus.txt", b"A" * 200, agent_ns="B.Tech_CSE"
        )
        assert n > 1
        assert ops["delete_filter"] == {
            "metadata.filename": "syllabus.txt",
            "metadata.agent_ns": "B.Tech_CSE",
        }
        assert len(ops["inserts"]) == n
        assert ops["inserts"][0]["metadata"]["agent_ns"] == "B.Tech_CSE"
        assert ops["inserts"][0]["metadata"]["filename"] == "syllabus.txt"