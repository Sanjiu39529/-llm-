"""无需外部服务的 Markdown 知识检索器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """可引用的一段业务知识。"""

    source: str
    title: str
    content: str
    score: float = 0.0


class MarkdownKnowledgeBase:
    """将 Markdown 按二级及以上标题切分，并进行确定性关键词召回。"""

    def __init__(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        self._chunks = chunks

    @classmethod
    def from_directory(cls, directory: Path) -> "MarkdownKnowledgeBase":
        chunks: list[KnowledgeChunk] = []
        if not directory.exists():
            return cls(())
        for path in sorted(directory.rglob("*.md")):
            chunks.extend(_split_markdown(path, directory.parent))
        return cls(tuple(chunks))

    def search(self, question: str, limit: int = 3) -> tuple[KnowledgeChunk, ...]:
        query_terms = _terms(question)
        if not query_terms:
            return ()
        matches: list[KnowledgeChunk] = []
        for chunk in self._chunks:
            chunk_terms = _terms(f"{chunk.title}\n{chunk.content}")
            overlap = query_terms & chunk_terms
            if not overlap:
                continue
            score = len(overlap) / len(query_terms)
            matches.append(
                KnowledgeChunk(chunk.source, chunk.title, chunk.content, score)
            )
        return tuple(
            sorted(matches, key=lambda item: (-item.score, item.source, item.title))[:limit]
        )


def _split_markdown(path: Path, root: Path) -> list[KnowledgeChunk]:
    title = path.stem
    lines: list[str] = []
    chunks: list[KnowledgeChunk] = []
    source = path.relative_to(root).as_posix()
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^#{1,3}\s+", line):
            if lines:
                chunks.append(KnowledgeChunk(source, title, "\n".join(lines).strip()))
            title = re.sub(r"^#{1,3}\s+", "", line).strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        chunks.append(KnowledgeChunk(source, title, "\n".join(lines).strip()))
    return [chunk for chunk in chunks if chunk.content]


def _terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    chinese_bigrams = {
        run[index : index + 2]
        for run in chinese_runs
        for index in range(len(run) - 1)
    }
    latin_words = set(re.findall(r"[a-z0-9_]{2,}", normalized))
    return chinese_bigrams | latin_words
