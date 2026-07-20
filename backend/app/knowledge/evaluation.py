"""Small deterministic retrieval evaluation used by tests and local reviews."""

from dataclasses import dataclass

from backend.app.knowledge.retriever import MarkdownKnowledgeBase


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    question: str
    expected_source: str
    expected_title_contains: str | None = None


def evaluate_retrieval(
    knowledge_base: MarkdownKnowledgeBase,
    cases: tuple[RetrievalCase, ...],
    *,
    limit: int = 3,
) -> dict[str, float | int]:
    if not cases:
        return {"total": 0, "hits": 0, "hit_rate": 0.0, "mrr": 0.0}
    hits = 0
    reciprocal_rank = 0.0
    for case in cases:
        results = knowledge_base.search(case.question, limit=limit)
        rank = next(
            (
                index
                for index, chunk in enumerate(results, start=1)
                if chunk.source == case.expected_source
                and (
                    case.expected_title_contains is None
                    or case.expected_title_contains in chunk.title
                )
            ),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_rank += 1 / rank
    return {
        "total": len(cases),
        "hits": hits,
        "hit_rate": hits / len(cases),
        "mrr": reciprocal_rank / len(cases),
    }
