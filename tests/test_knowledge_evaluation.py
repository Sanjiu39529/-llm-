from pathlib import Path

from backend.app.knowledge.evaluation import RetrievalCase, evaluate_retrieval
from backend.app.knowledge.rag_answerer import OpenAICompatibleRagAnswerer
from backend.app.knowledge.retriever import KnowledgeChunk, MarkdownKnowledgeBase
import io
import json
import pytest


def test_project_knowledge_retrieval_has_stable_citations_and_hits() -> None:
    knowledge_base = MarkdownKnowledgeBase.from_directory(Path("docs/knowledge"))
    result = knowledge_base.search("GMV 的口径是什么？")

    assert result
    assert result[0].chunk_id
    assert result[0].citation(1)["source"] == "knowledge/电商指标口径.md"

    metrics = evaluate_retrieval(
        knowledge_base,
        (
            RetrievalCase("GMV 的口径是什么？", "knowledge/电商指标口径.md"),
            RetrievalCase("ROI 如何计算？", "knowledge/电商指标口径.md"),
        ),
    )
    assert metrics["hit_rate"] == 1.0
    assert metrics["mrr"] == 1.0


def test_rag_answer_rejects_citations_outside_retrieved_context(monkeypatch) -> None:
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    payload = {"choices": [{"message": {"content": "错误引用。[9]"}}]}
    monkeypatch.setattr(
        "backend.app.knowledge.rag_answerer.urlopen",
        lambda request, timeout: Response(json.dumps(payload).encode("utf-8")),
    )
    answerer = OpenAICompatibleRagAnswerer("https://example.test/v1", "key", "model")

    with pytest.raises(ValueError, match="invalid_citations"):
        answerer.answer("问题", (KnowledgeChunk("source", "title", "content"),))
