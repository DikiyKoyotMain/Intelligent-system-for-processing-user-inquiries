from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    updated_at: str
    language: str


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    updated_at: str
    language: str
    lexical_similarity: float


def split_into_chunks(text: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    if max_chars < 1:
        raise ValueError('max_chars должен быть положительным.')
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError('overlap_chars должен быть неотрицательным и меньше max_chars.')
    normalized = re.sub(r'\s+', ' ', text).strip()
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(' ', start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def load_documents(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f'Файл базы знаний не найден: {path}')
    documents = []
    seen_ids = set()
    required = ('id', 'title', 'content', 'source', 'updated_at', 'language')
    with path.open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Некорректный JSON в строке {line_number}.') from exc
            if not isinstance(item, dict):
                raise ValueError(f'Строка {line_number} должна содержать JSON-объект.')
            missing = [field for field in required if not isinstance(item.get(field), str) or not item[field].strip()]
            if missing:
                raise ValueError(f'В строке {line_number} отсутствуют текстовые поля: {missing}.')
            if item['id'] in seen_ids:
                raise ValueError(f"Повторяется id документа {item['id']!r}.")
            seen_ids.add(item['id'])
            documents.append(item)
    if not documents:
        raise ValueError('Файл базы знаний пуст.')
    return documents


def make_chunks(documents: Iterable[dict], max_chars: int = 900, overlap_chars: int = 120) -> list[KnowledgeChunk]:
    chunks = []
    for document in documents:
        texts = split_into_chunks(document['content'], max_chars=max_chars, overlap_chars=overlap_chars)
        for index, text in enumerate(texts, start=1):
            chunks.append(KnowledgeChunk(
                document_id=document['id'],
                chunk_id=f"{document['id']}:{index:04d}",
                title=document['title'],
                text=text,
                source=document['source'],
                updated_at=document['updated_at'],
                language=document['language'],
            ))
    if not chunks:
        raise ValueError('В документах нет содержимого для индексации.')
    return chunks


class KnowledgeRetriever:
    def __init__(self, chunks: list[KnowledgeChunk]):
        if not chunks:
            raise ValueError('Для поиска требуется хотя бы один фрагмент.')
        self.chunks = tuple(chunks)
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            strip_accents='unicode',
            sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform([chunk.text for chunk in self.chunks])

    @classmethod
    def from_jsonl(cls, path: str | Path, max_chars: int = 900, overlap_chars: int = 120) -> KnowledgeRetriever:
        documents = load_documents(Path(path))
        chunks = make_chunks(documents, max_chars=max_chars, overlap_chars=overlap_chars)
        return cls(chunks)

    def search(self, query: str, top_k: int = 5, language: str | None = None) -> list[RetrievalHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Поисковый запрос не должен быть пустым.')
        if top_k < 1:
            raise ValueError('top_k должен быть положительным.')
        query_vector = self.vectorizer.transform([query.strip()])
        scores = np.asarray((self.matrix @ query_vector.T).toarray()).ravel()
        candidates = [
            index for index, chunk in enumerate(self.chunks)
            if language is None or chunk.language.casefold() == language.casefold()
        ]
        candidates.sort(key=lambda index: (-float(scores[index]), self.chunks[index].chunk_id))
        results = []
        for index in candidates[:top_k]:
            chunk = self.chunks[index]
            results.append(RetrievalHit(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                text=chunk.text,
                source=chunk.source,
                updated_at=chunk.updated_at,
                language=chunk.language,
                lexical_similarity=float(scores[index]),
            ))
        return results
